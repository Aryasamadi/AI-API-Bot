import os
import re
import json
import logging
import asyncio
import base64
import aiohttp
import aiosqlite
from urllib.parse import urlparse
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.chat_action import ChatActionSender

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

DB_PROVIDER = os.getenv("DB_PROVIDER", "cloudflare").lower()
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_D1_DATABASE_ID = os.getenv("CLOUDFLARE_D1_DATABASE_ID")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
CLOUD_API_URL = os.getenv("CLOUD_API_URL")
CLOUD_API_TOKEN = os.getenv("CLOUD_API_TOKEN")
CLOUD_QUERY_BODY = os.getenv("CLOUD_QUERY_BODY", '{"sql": "query", "params": []}')

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)
DB_PATH = "bot_advanced.db"

class DatabaseManager:
    def __init__(self):
        self.db_path = DB_PATH
        self.provider = DB_PROVIDER
        if self.provider == "cloudflare":
            self.use_cloud = bool(CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_D1_DATABASE_ID and CLOUDFLARE_API_TOKEN)
            if self.use_cloud:
                logging.info("☁️ Cloudflare D1 mode ACTIVE")
            else:
                logging.info("💾 Local SQLite mode")
        elif self.provider == "generic":
            self.use_cloud = bool(CLOUD_API_URL and CLOUD_API_TOKEN)
            if self.use_cloud:
                logging.info(f"☁️ Generic cloud DB mode ACTIVE ({CLOUD_API_URL})")
            else:
                logging.info("💾 Local SQLite mode")
        else:
            self.use_cloud = False
            logging.info("💾 Local SQLite mode")

    async def _cloud_request(self, query, params=()):
        if self.provider == "cloudflare":
            url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/d1/database/{CLOUDFLARE_D1_DATABASE_ID}/query"
            headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}
            payload = {"sql": query, "params": list(params)}
        elif self.provider == "generic":
            if not CLOUD_API_URL:
                raise Exception("CLOUD_API_URL not set")
            url = CLOUD_API_URL
            headers = {"Authorization": f"Bearer {CLOUD_API_TOKEN}", "Content-Type": "application/json"}
            try:
                template = json.loads(CLOUD_QUERY_BODY)
            except:
                template = {"sql": "query", "params": []}
            payload = template
            payload_str = json.dumps(payload)
            payload_str = payload_str.replace("'query'", json.dumps(query))
            payload_str = payload_str.replace("'params'", json.dumps(list(params)))
            payload = json.loads(payload_str)
        else:
            raise Exception("Unsupported DB_PROVIDER")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=10) as resp:
                    data = await resp.json()
                    if self.provider == "cloudflare":
                        if data.get("success"):
                            return data["result"][0] if data["result"] else None
                        else:
                            logging.error(f"Cloudflare error: {data.get('errors')}")
                            return None
                    else:
                        if "results" in data:
                            return data
                        elif "data" in data:
                            return data
                        else:
                            return data
        except Exception as e:
            logging.error(f"Cloud request failed: {e}")
            return None

    async def execute(self, query, params=()):
        if self.use_cloud:
            res = await self._cloud_request(query, params)
            if res and res.get("meta"):
                return {"lastrowid": res["meta"].get("last_row_id"), "rowcount": res["meta"].get("changes", 0)}
            return {"lastrowid": None, "rowcount": 0}
        else:
            async with aiosqlite.connect(self.db_path) as conn:
                cursor = await conn.execute(query, params)
                await conn.commit()
                return {"lastrowid": cursor.lastrowid, "rowcount": cursor.rowcount}

    async def fetchall(self, query, params=()):
        if self.use_cloud:
            res = await self._cloud_request(query, params)
            if res and "results" in res:
                return [tuple(row.values()) for row in res["results"]]
            return []
        else:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(query, params) as cursor:
                    return await cursor.fetchall()

    async def fetchone(self, query, params=()):
        if self.use_cloud:
            res = await self._cloud_request(query, params)
            if res and "results" in res and len(res["results"]) > 0:
                return tuple(res["results"][0].values())
            return None
        else:
            async with aiosqlite.connect(self.db_path) as conn:
                async with conn.execute(query, params) as cursor:
                    return await cursor.fetchone()

    async def fetchval(self, query, params=()):
        row = await self.fetchone(query, params)
        return row[0] if row else 0

    async def clear_history(self):
        await self.execute("DELETE FROM history")

    async def truncate_all_tables(self):
        tables = ["users", "settings", "routers", "models", "history"]
        for table in tables:
            await self.execute(f"DELETE FROM {table}")
        if not self.use_cloud:
            for table in tables:
                await self.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}'")

    async def get_stats(self):
        if self.use_cloud:
            users = await self.fetchval("SELECT COUNT(*) FROM users")
            models = await self.fetchval("SELECT COUNT(*) FROM models")
            routers = await self.fetchval("SELECT COUNT(*) FROM routers")
            tokens = await self.fetchval("SELECT COUNT(*) FROM routers WHERE api_key IS NOT NULL AND api_key != ''")
        else:
            row = await self.fetchone("""
                SELECT 
                    (SELECT COUNT(*) FROM users),
                    (SELECT COUNT(*) FROM models),
                    (SELECT COUNT(*) FROM routers),
                    (SELECT COUNT(*) FROM routers WHERE api_key IS NOT NULL AND api_key != '')
            """)
            if row:
                users, models, routers, tokens = row
            else:
                users = models = routers = tokens = 0
        return users, models, routers, tokens

    async def get_all_data(self):
        routers = await self.fetchall("SELECT id, domain, base_url, api_key FROM routers ORDER BY id")
        result = []
        for r in routers:
            r_id, domain, base_url, api_key = r
            models = await self.fetchall("SELECT id, model_name FROM models WHERE router_id = ? ORDER BY id", (r_id,))
            result.append({
                "id": r_id,
                "domain": domain,
                "base_url": base_url,
                "api_key": api_key,
                "models": models
            })
        return result

db = DatabaseManager()

MODEL_EMOJI_MAP = {
    "gpt": "🧠", "deepseek": "🐟", "claude": "🤖", "gemini": "🌟",
    "llama": "🦙", "mistral": "🌪️", "qwen": "🐉", "command": "⚡",
    "dalle": "🎨", "whisper": "🎤",
}
FALLBACK_EMOJIS = ["🧠", "🤖", "🚀", "💡", "⚡", "🔥", "🌟", "💎",
    "📡", "🛸", "🧩", "🎯", "🏆", "🎓", "🧬", "🔮",
    "🌀", "🌈", "💫", "🎨", "🦾", "🧿", "⚙️", "📊"]

def get_model_emoji(model_name: str, model_id: int) -> str:
    name_lower = model_name.lower()
    for key, emoji in MODEL_EMOJI_MAP.items():
        if key in name_lower:
            return emoji
    return FALLBACK_EMOJIS[model_id % len(FALLBACK_EMOJIS)]

def shorten_model_name(name: str, max_len: int = 25) -> str:
    if len(name) <= max_len:
        return name
    if '/' in name:
        parts = name.split('/')
        short = parts[-1]
        if len(short) <= max_len:
            return short
    for sep in ('-', '.'):
        if sep in name:
            base = name.split(sep)[0]
            if len(base) <= max_len:
                return base
    return name[:max_len] + '…'

LANGS = {
    "en": {
        "name": "🇬🇧 English",
        "welcome_new": "Please select your language:",
        "welcome_back": "Welcome back, {name}!",
        "welcome_first": "👋 Welcome! Use /help to see available commands.",
        "locked": "⛔ Unauthorized. Please enter the password:",
        "pwd_ok": "✅ Password accepted! Continue chatting...",
        "pwd_err": "⛔ Please enter the correct password:",
        "pwd_none": "🔓 Password requirement removed. Bot is public.",
        "pwd_set": "✅ New password set: `{}`",
        "admin_only": "❌ Admin only.",
        "type_here": "Type your message...",
        "select_model": "Select an AI model to start a NEW chat:",
        "no_models_admin": "⚠️ No models available.",
        "no_models_user": "⚠️ No models available.",
        "chat_started": "✅ Connected to {}.\nSend your message:",
        "invalid_url": "❌ Invalid URL format. Please send a valid Base URL (http/https):",
        "admin_menu": "⚙️ Advanced Admin Panel – use the menu below:",
        "title_routers": "🗂 List of all available API routers:",
        "title_settings": "⚙️ Bot settings & database management :",
        "btn_routers": "🗂 API List",
        "btn_add_router": "➕ Add Router",
        "btn_settings": "⚙️ Settings",
        "btn_database": "🗄️ Database",
        "btn_stats": "📊 Stats & Status",
        "btn_set_pwd": "🔐 Set Password",
        "btn_set_channel": "📢 Force Join",
        "btn_broadcast": "📢 Broadcast",
        "btn_back": "🔙 Back",
        "btn_back_main": "🏠 Main Menu",
        "send_pwd_prompt": "Send new password (or 'none' to make public):",
        "send_limit_prompt": "Now enter the number of messages allowed for unauthorized users (e.g., 5):",
        "send_broadcast": "Send your broadcast message:",
        "broadcast_done": "✅ Sent to {} users.",
        "send_url": "Send the Base URL (e.g., https://api.openai.com/v1):",
        "url_detected": "Domain: {}\nNow send the API Key (Token):",
        "send_model": "API Key saved.\nNow send the exact Model Name:",
        "send_model_for_router": "Send the exact Model Name to add to this router:",
        "router_added": "✅ Router and Model added successfully!",
        "router_details": "📌 **Router:** {}\n\n🌐 Base URL: `{}`\n\n🔑 Token: `{}`\n\n📦 **Models (tap to copy):**\n{}",
        "btn_add_mod": "➕ Add Model",
        "btn_del_mod": "🗑 Delete Model",
        "btn_del_router": "🗑 Delete Router",
        "del_confirm_msg": "⚠️ Are you sure you want to delete this router and its models?",
        "btn_yes": "✅ Yes",
        "btn_no": "❌ No",
        "del_success": "✅ Deleted.",
        "pls_select_model": "Please select a valid model from the list.",
        "invalid_command": "❌ Please use valid logical commands.",
        "send_channel_prompt": "Send channel username (e.g., @AI_Channel) or 'none' (for multiple, separate with comma):",
        "channel_set": "✅ Force join channel(s) set to: `{}`",
        "channel_none": "🔓 Force join disabled.",
        "must_join": "⛔ You must join our channel(s) to use the bot:\n{channels}",
        "btn_join_channel": "🔗 Join Channel",
        "btn_check_join": "🔄 Check Membership",
        "join_ok": "✅ Membership verified! You can now use the bot.",
        "join_fail": "❌ You haven't joined all required channels yet!",
        "send_del_model": "Send the exact name of the model you want to delete:",
        "model_deleted": "✅ Model deleted successfully.",
        "model_not_found": "❌ Model not found.",
        "btn_user_mode": "👤 User Mode",
        "btn_clear_cache": "🧹 Clear Cache (history only)",
        "btn_clear_all": "🗑️ Full Database Wipe",
        "clear_cache_confirm": "🧹 This will delete all chat history (messages) from all users.\n❓ Are you sure?",
        "clear_cache_done": "✅ Chat history cleared.",
        "clear_all_confirm": "🗑️ This will delete ALL data:\n- Users\n- Settings\n- Routers\n- Models\n- Chat history\n\n❓ Are you sure?",
        "clear_all_done": "✅ All data has been wiped.",
        "clear_cancelled": "❌ Operation cancelled.",
        "btn_admin_panel": "⚙️ Admin Panel",
        "no_cloud_db": "⚠️ No external cloud database is configured. Using local SQLite.",
        "no_routers": "⚠️ No API routers have been added yet.",
        "help_user": "📖 Available Commands\n\n🚀 /start • start ➜ Start\n🌐 /lang • lang ➜ Language\n🤖 /model • model ➜ Clear chat & select new model\n📞 /man • man ➜ Contact admin\n❓ /help • help ➜ Help\n\n✨ Choose and start 🚀",
        "help_admin": "🌐 /lang • lang ➜ Language\n👤 /user • user ➜ User mode\n🤖 /model • model ➜ Clear cache & models\n📞 /man • man ➜ Contact admin\n❓ /help • help ➜ Help\n✨ Choose and start 🚀",
        "stats_text": "📊 **Bot Statistics**\n\n👤 Users: `{users}`\n📢 Force Channel(s): `{channel}`\n🤖 Models: `{models}`\n🗂️ Routers: `{routers}`\n🔑 Tokens: `{tokens}`\n🔐 Password: `{pwd_status}`",
        "btn_view_data": "📋 View All Data",
        "all_data_title": "📋 **All Routers, Models and Tokens**\n\n",
        "data_router_header": "\n📍 **Router #{id}** – `{domain}`\n🌐 Base URL: `{base_url}`\n🔑 Token: `{api_key}`\n📦 Models:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (no models)\n",
        "unknown_command": "❌ Unknown command",
        "blocked_unauthorized": "⛔ You have used your {limit} free requests. Please enter the password:",
        "forward_to_admin": "Unknown command from @{username} (ID: {user_id}): {text}",
        "model_added_continue": "✅ Model added. Enter next model name, or press 'Finish' button.",
        "finish": "✅ Finish",
        "router_added_continue": "✅ Model added. Enter next model name, or press 'Finish' button.",
        "add_router_done": "✅ Router and models registered successfully.",
        "loading_data": "⏳ Loading data... {progress}%",
        "data_loaded": "✅ Data loaded successfully.",
        "error_occurred": "❌ An error occurred while loading data. Please try again later.",
        "error_detail": "❌ Error details: {error}",
        "limit_blocked": "⛔ You have used your {limit} free requests. Please enter the password:",
        "contact_intro": "Please write your request as a complete message to the administrator:",
        "contact_confirm": "✅ Your message was sent. We will respond as soon as possible. To contact again, send /man.",
        "contact_end_auto": "✅ Sent. We will respond as soon as possible.\nTo contact again, send /man.",
        "contact_forward": "Message from user {name} (ID: {user_id}):\n{text}",
        "contact_button": "📞 Contact Admin",
        "contact_admin_reply": "📩 Reply from admin:\n{text}",
        "admin_reply_sent": "✅ Reply sent to user.",
        "pwd_prompt_wrong": "⛔ Please enter the correct password:",
        "invalid_model": "❌ This model is no longer available. Please select another one."
    },
    "fa": {
        "name": "🇮🇷🇦🇫 فارسی",
        "welcome_new": "لطفاً زبان خود را انتخاب کنید:",
        "welcome_back": "خوش برگشتی، {name}!",
        "welcome_first": "👋 خوش آمدی! برای دیدن راهنما از دستور /help استفاده کن.",
        "locked": "⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور را وارد کنید:",
        "pwd_ok": "✅ رمز عبور تایید شد! به چت ادامه بده...",
        "pwd_err": "⛔ رمز عبور صحیح را وارد کنید:",
        "pwd_none": "🔓 قفل ربات برداشته شد. استفاده برای همه آزاد است.",
        "pwd_set": "✅ رمز عبور جدید تنظیم شد: `{}`",
        "admin_only": "❌ دسترسی فقط برای مدیریت.",
        "type_here": "پیام خود را بنویسید...",
        "select_model": "برای شروع یک چت جدید، مدل را انتخاب کنید:",
        "no_models_admin": "⚠️ هنوز هیچ مدلی وجود ندارد.",
        "no_models_user": "⚠️ هنوز هیچ مدلی وجود ندارد.",
        "chat_started": "✅ شما به {} متصل شدید.\nپیام خود را بفرستید:",
        "invalid_url": "❌ فرمت لینک اشتباه است. لطفاً یک URL معتبر بفرستید:",
        "admin_menu": "⚙️ پنل مدیریت پیشرفته ربات – از منو زیر استفاده کنید:",
        "title_routers": "🗂 لیست APIهای موجود در ربات :",
        "title_settings": "⚙️ تنظیمات ربات و مدیریت دیتابیس :",
        "btn_routers": "🗂 APIها",
        "btn_add_router": "➕ روتر جدید",
        "btn_settings": "⚙️ تنظیمات",
        "btn_database": "🗄️ دیتابیس",
        "btn_stats": "📊 آمار و وضعیت",
        "btn_set_pwd": "🔐 رمز عبور",
        "btn_set_channel": "📢 کانال اجباری",
        "btn_broadcast": "📢 پیام همگانی",
        "btn_back": "🔙 بازگشت",
        "btn_back_main": "🏠 منوی اصلی",
        "send_pwd_prompt": "رمز جدید را بفرستید (یا none برای آزادسازی):",
        "send_limit_prompt": "حالا تعداد پیام‌های مجاز برای کاربران بدون رمز را وارد کنید (مثلاً ۵):",
        "send_broadcast": "پیام همگانی خود را بفرستید:",
        "broadcast_done": "✅ به {} کاربر ارسال شد.",
        "send_url": "آدرس Base URL را بفرستید:",
        "url_detected": "دامنه: {}\nحالا کلید API (توکن) را بفرستید:",
        "send_model": "توکن ذخیره شد.\nحالا نام دقیق مدل را بفرستید:",
        "send_model_for_router": "نام دقیق مدل را برای افزودن به این روتر بفرستید:",
        "router_added": "✅ روتر و مدل با موفقیت اضافه شدند!",
        "router_details": "📌 **روتر:** {}\n\n🌐 آدرس: `{}`\n\n🔑 توکن: `{}`\n\n📦 **مدل‌ها (برای کپی، روی هر کدام بزنید):**\n{}",
        "btn_add_mod": "➕ مدل",
        "btn_del_mod": "🗑 حذف مدل",
        "btn_del_router": "🗑 حذف روتر",
        "del_confirm_msg": "⚠️ آیا از حذف این روتر مطمئن هستید؟",
        "btn_yes": "✅ بله",
        "btn_no": "❌ خیر",
        "del_success": "✅ حذف شد.",
        "pls_select_model": "لطفاً یک مدل معتبر انتخاب کنید.",
        "invalid_command": "❌ لطفاً از دستورات منطقی استفاده کنید.",
        "send_channel_prompt": "آیدی کانال را با @ بفرستید (یا none برای غیرفعال‌سازی). برای چند کانال با کاما جدا کنید:",
        "channel_set": "✅ کانال‌های اجباری تنظیم شدند: `{}`",
        "channel_none": "🔓 کانال اجباری غیرفعال شد.",
        "must_join": "⛔ برای استفاده از ربات، باید در کانال‌های زیر عضو باشید:\n{channels}",
        "btn_join_channel": "🔗 عضویت در کانال",
        "btn_check_join": "🔄 بررسی عضویت",
        "join_ok": "✅ عضویت در همه کانال‌ها تایید شد! حالا می‌توانید استفاده کنید.",
        "join_fail": "❌ شما هنوز در همه کانال‌ها عضو نشده‌اید!",
        "send_del_model": "نام دقیق مدلی که می‌خواهید حذف کنید را بفرستید:",
        "model_deleted": "✅ مدل با موفقیت حذف شد.",
        "model_not_found": "❌ مدلی با این نام یافت نشد.",
        "btn_user_mode": "👤 حالت کاربری",
        "btn_clear_cache": "🧹 پاک‌سازی کش (فقط تاریخچه)",
        "btn_clear_all": "🗑️ پاک‌سازی کامل دیتابیس",
        "clear_cache_confirm": "🧹 این کار تمام تاریخچه چت (پیام‌ها) را از همه کاربران حذف می‌کند.\n❓ مطمئن هستید؟",
        "clear_cache_done": "✅ تاریخچه چت پاک شد.",
        "clear_all_confirm": "🗑️ این کار تمام داده‌ها را حذف می‌کند:\n- کاربران\n- تنظیمات\n- روترها\n- مدل‌ها\n- تاریخچه چت\n\n❓ مطمئن هستید؟",
        "clear_all_done": "✅ تمام داده‌ها پاک شدند.",
        "clear_cancelled": "❌ عملیات لغو شد.",
        "btn_admin_panel": "⚙️ پنل مدیریت",
        "no_cloud_db": "⚠️ هیچ دیتابیس ابری پیکربندی نشده است. از حافظه محلی SQLite استفاده می‌شود.",
        "no_routers": "⚠️ هنوز هیچ API ثبت نشده است.",
        "help_user": "📖 دستورات موجود\n\n🚀 /start • start➜ شروع\n🌐 /lang • lang ➜ زبان\n🤖 /model • model ➜ پاک‌سازی چت و انتخاب مدل جدید\n📞 /man • man ➜ تماس با مدیر\n❓ /help • help ➜ راهنما\n\n✨ انتخاب کن و شروع کن 🚀",
        "help_admin": "🌐 /lang • lang ➜ زبان\n👤 /user • user ➜ کاربری\n🤖 /model • model ➜ پاک‌سازی کش و مدل‌ها\n📞 /man • man ➜ تماس با مدیر\n❓ /help • help ➜ راهنما\n✨ انتخاب کن و شروع کن 🚀",
        "stats_text": "📊 **آمار ربات**\n\n👤 کاربران: `{users}`\n📢 کانال‌های اجباری: `{channel}`\n🤖 مدل‌ها: `{models}`\n🗂️ روترها: `{routers}`\n🔑 توکن‌ها: `{tokens}`\n🔐 رمز عبور: `{pwd_status}`",
        "btn_view_data": "📋 مشاهده داده‌ها",
        "all_data_title": "📋 **همه روترها، مدل‌ها و توکن‌ها**\n\n",
        "data_router_header": "\n📍 **روتر #{id}** – `{domain}`\n🌐 آدرس: `{base_url}`\n🔑 توکن: `{api_key}`\n📦 مدل‌ها:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (هیچ مدلی وجود ندارد)\n",
        "unknown_command": "❌ دستور ناشناس",
        "blocked_unauthorized": "⛔ شما از {limit} بار درخواست رایگان خود را استفاده کردید. رمز عبور را وارد کنید:",
        "forward_to_admin": "دستور ناشناس از @{username} (شناسه: {user_id}): {text}",
        "model_added_continue": "✅ مدل اضافه شد. نام مدل بعدی را وارد کنید، یا دکمهٔ «پایان» را بزنید.",
        "finish": "✅ پایان",
        "router_added_continue": "✅ مدل اضافه شد. نام مدل بعدی را وارد کنید، یا دکمهٔ «پایان» را بزنید.",
        "add_router_done": "✅ روتر و مدل‌ها با موفقیت ثبت شدند.",
        "loading_data": "⏳ در حال بارگذاری داده‌ها... {progress}%",
        "data_loaded": "✅ داده‌ها با موفقیت بارگذاری شدند.",
        "error_occurred": "❌ خطایی در بارگذاری داده‌ها رخ داد. لطفاً بعداً تلاش کنید.",
        "error_detail": "❌ جزئیات خطا: {error}",
        "limit_blocked": "⛔ شما از {limit} بار درخواست رایگان خود را استفاده کردید. رمز عبور را وارد کنید:",
        "contact_intro": "لطفاً درخواست خود را در قالب یک پیام کامل برای مدیر بنویسید:",
        "contact_confirm": "✅ پیام شما ارسال شد. در اسرع وقت پاسخ خواهیم داد. برای ارتباط مجدد /man را ارسال کنید.",
        "contact_end_auto": "ارسال شد ✅ در اسرع وقت پاسخ خواهیم داد.\nبرای ارتباط مجدد /man را ارسال کنید.",
        "contact_forward": "پیام از کاربر {name} (شناسه: {user_id}):\n{text}",
        "contact_button": "📞 تماس با مدیر",
        "contact_admin_reply": "📩 پاسخ از مدیر:\n{text}",
        "admin_reply_sent": "✅ پاسخ به کاربر ارسال شد.",
        "pwd_prompt_wrong": "⛔ رمز عبور صحیح را وارد کنید:",
        "invalid_model": "❌ این مدل دیگر در دسترس نیست. لطفاً مدل دیگری انتخاب کنید."
    },
    "ru": {
        "name": "🇷🇺 Русский",
        "welcome_new": "Пожалуйста, выберите язык:",
        "welcome_back": "С возвращением, {name}!",
        "welcome_first": "👋 Добро пожаловать! Используйте /help для списка команд.",
        "locked": "⛔ Доступ ограничен. Введите пароль:",
        "pwd_ok": "✅ Пароль принят! Продолжайте общение...",
        "pwd_err": "⛔ Введите правильный пароль:",
        "pwd_none": "🔓 Пароль удален. Бот общедоступен.",
        "pwd_set": "✅ Новый пароль: `{}`",
        "admin_only": "❌ Только для админа.",
        "type_here": "Введите сообщение...",
        "select_model": "Выберите модель для нового чата:",
        "no_models_admin": "⚠️ Нет доступных моделей.",
        "no_models_user": "⚠️ Нет доступных моделей.",
        "chat_started": "✅ Подключено к {}.\nОтправьте сообщение:",
        "invalid_url": "❌ Неверный URL.",
        "admin_menu": "⚙️ Расширенная панель администратора – используйте меню:",
        "title_routers": "🗂 Список всех доступных API-роутеров:",
        "title_settings": "⚙️ Настройки бота и управление базой данных :",
        "btn_routers": "🗂 Список API",
        "btn_add_router": "➕ Добавить роутер",
        "btn_settings": "⚙️ Настройки",
        "btn_database": "🗄️ База данных",
        "btn_stats": "📊 Статистика и статус",
        "btn_set_pwd": "🔐 Пароль",
        "btn_set_channel": "📢 Канал",
        "btn_broadcast": "📢 Рассылка",
        "btn_back": "🔙 Назад",
        "btn_back_main": "🏠 Главное меню",
        "send_pwd_prompt": "Введите новый пароль (или none):",
        "send_limit_prompt": "Теперь введите количество сообщений для неавторизованных пользователей (например, 5):",
        "send_broadcast": "Введите сообщение для рассылки:",
        "broadcast_done": "✅ Отправлено: {}.",
        "send_url": "Введите Base URL:",
        "url_detected": "Домен: {}\nВведите API ключ:",
        "send_model": "Введите название модели:",
        "send_model_for_router": "Отправьте точное имя модели для добавления к этому роутеру:",
        "router_added": "✅ Успешно!",
        "router_details": "📌 **Роутер:** {}\n\n🌐 URL: `{}`\n\n🔑 Токен: `{}`\n\n📦 **Модели (нажмите для копирования):**\n{}",
        "btn_add_mod": "➕ Модель",
        "btn_del_mod": "🗑 Удалить",
        "btn_del_router": "🗑 Роутер",
        "del_confirm_msg": "⚠️ Вы уверены?",
        "btn_yes": "✅ Да",
        "btn_no": "❌ Нет",
        "del_success": "✅ Удалено.",
        "pls_select_model": "Выберите модель.",
        "invalid_command": "❌ Неверная команда.",
        "send_channel_prompt": "Отправьте юзернейм канала (@channel) или none (для нескольких через запятую):",
        "channel_set": "✅ Канал(ы) установлен: `{}`",
        "channel_none": "🔓 Подписка отключена.",
        "must_join": "⛔ Подпишитесь на каналы:\n{channels}",
        "btn_join_channel": "🔗 Подписаться",
        "btn_check_join": "🔄 Проверить",
        "join_ok": "✅ Проверка пройдена!",
        "join_fail": "❌ Вы еще не подписались на все каналы!",
        "send_del_model": "Точное имя модели для удаления:",
        "model_deleted": "✅ Удалена.",
        "model_not_found": "❌ Не найдена.",
        "btn_user_mode": "👤 Режим пользователя",
        "btn_clear_cache": "🧹 Очистить кэш (только историю)",
        "btn_clear_all": "🗑️ Полная очистка БД",
        "clear_cache_confirm": "🧹 Это удалит всю историю чатов (сообщения) всех пользователей.\n❓ Вы уверены?",
        "clear_cache_done": "✅ История чатов очищена.",
        "clear_all_confirm": "🗑️ Это удалит ВСЕ данные:\n- Пользователи\n- Настройки\n- Роутеры\n- Модели\n- История чатов\n\n❓ Вы уверены?",
        "clear_all_done": "✅ Все данные удалены.",
        "clear_cancelled": "❌ Отменено.",
        "btn_admin_panel": "⚙️ Панель администратора",
        "no_cloud_db": "⚠️ Внешняя облачная БД не настроена. Используется локальный SQLite.",
        "no_routers": "⚠️ API-роутеры ещё не добавлены.",
        "help_user": "📖 Доступные команды\n\n🚀 /start • start ➜ Начать\n🌐 /lang • lang ➜ Язык\n🤖 /model • model ➜ Очистить чат и выбрать модель\n📞 /man • man ➜ Связаться с администратором\n❓ /help • help ➜ Помощь\n\n✨ Выбери и начни 🚀",
        "help_admin": "🌐 /lang • lang ➜ Язык\n👤 /user • user ➜ Пользовательский режим\n🤖 /model • model ➜ Очистить кэш и модели\n📞 /man • man ➜ Связаться с администратором\n❓ /help • help ➜ Помощь\n✨ Выбери и начни 🚀",
        "stats_text": "📊 **Статистика бота**\n\n👤 Пользователи: `{users}`\n📢 Канал(ы): `{channel}`\n🤖 Модели: `{models}`\n🗂️ Роутеры: `{routers}`\n🔑 Токены: `{tokens}`\n🔐 Пароль: `{pwd_status}`",
        "btn_view_data": "📋 Просмотр данных",
        "all_data_title": "📋 **Все роутеры, модели и токены**\n\n",
        "data_router_header": "\n📍 **Роутер #{id}** – `{domain}`\n🌐 URL: `{base_url}`\n🔑 Токен: `{api_key}`\n📦 Модели:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (нет моделей)\n",
        "unknown_command": "❌ Неизвестная команда",
        "blocked_unauthorized": "⛔ Вы использовали {limit} бесплатных запросов. Введите пароль:",
        "forward_to_admin": "Неизвестная команда от @{username} (ID: {user_id}): {text}",
        "model_added_continue": "✅ Модель добавлена. Введите следующее имя модели или нажмите кнопку «Готово».",
        "finish": "✅ Готово",
        "router_added_continue": "✅ Модель добавлена. Введите следующее имя модели или нажмите кнопку «Готово».",
        "add_router_done": "✅ Роутер и модели успешно зарегистрированы.",
        "loading_data": "⏳ Загрузка данных... {progress}%",
        "data_loaded": "✅ Данные успешно загружены.",
        "error_occurred": "❌ Произошла ошибка при загрузке данных. Попробуйте позже.",
        "error_detail": "❌ Детали ошибки: {error}",
        "limit_blocked": "⛔ Вы использовали {limit} бесплатных запросов. Введите пароль:",
        "contact_intro": "Пожалуйста, напишите ваш запрос в виде полного сообщения администратору:",
        "contact_confirm": "✅ Ваше сообщение отправлено. Мы ответим в ближайшее время. Для повторного обращения отправьте /man.",
        "contact_end_auto": "Отправлено ✅ Мы ответим в ближайшее время.\nДля повторного обращения отправьте /man.",
        "contact_forward": "Сообщение от пользователя {name} (ID: {user_id}):\n{text}",
        "contact_button": "📞 Связаться с администратором",
        "contact_admin_reply": "📩 Ответ от администратора:\n{text}",
        "admin_reply_sent": "✅ Ответ отправлен пользователю.",
        "pwd_prompt_wrong": "⛔ Введите правильный пароль:",
        "invalid_model": "❌ Эта модель больше недоступна. Пожалуйста, выберите другую."
    },
    "ar": {
        "name": "🇸🇦 العربية",
        "welcome_new": "يرجى اختيار لغتك:",
        "welcome_back": "أهلاً بك مجدداً، {name}!",
        "welcome_first": "👋 مرحباً! استخدم /help لعرض الأوامر.",
        "locked": "⛔ غير مصرح. أدخل كلمة المرور:",
        "pwd_ok": "✅ تم القبول! استمر في المحادثة...",
        "pwd_err": "⛔ أدخل كلمة المرور الصحيحة:",
        "pwd_none": "🔓 تمت إزالة كلمة المرور.",
        "pwd_set": "✅ كلمة المرور الجديدة: `{}`",
        "admin_only": "❌ للمسؤولين فقط.",
        "type_here": "اكتب رسالتك...",
        "select_model": "اختر نموذج لبدء محادثة جديدة:",
        "no_models_admin": "⚠️ لا توجد نماذج متاحة.",
        "no_models_user": "⚠️ لا توجد نماذج متاحة.",
        "chat_started": "✅ متصل بـ {}.\nأرسل رسالتك:",
        "invalid_url": "❌ رابط غير صالح.",
        "admin_menu": "⚙️ لوحة إدارة متقدمة – استخدم القائمة أدناه:",
        "title_routers": "🗂 قائمة جميع موجهات API المتاحة:",
        "title_settings": "⚙️ إعدادات البوت وإدارة قاعدة البيانات :",
        "btn_routers": "🗂 قائمة API",
        "btn_add_router": "➕ إضافة موجه",
        "btn_settings": "⚙️ الإعدادات",
        "btn_database": "🗄️ قاعدة البيانات",
        "btn_stats": "📊 الإحصائيات والحالة",
        "btn_set_pwd": "🔐 كلمة المرور",
        "btn_set_channel": "📢 قناة إجبارية",
        "btn_broadcast": "📢 إرسال للكل",
        "btn_back": "🔙 رجوع",
        "btn_back_main": "🏠 القائمة الرئيسية",
        "send_pwd_prompt": "أدخل كلمة المرور الجديدة (أو none):",
        "send_limit_prompt": "الآن أدخل عدد الرسائل المسموح بها للمستخدمين غير المصرح لهم (مثال: 5):",
        "send_broadcast": "أدخل رسالة البث:",
        "broadcast_done": "✅ تم الإرسال إلى {}.",
        "send_url": "أدخل Base URL:",
        "url_detected": "النطاق: {}\nأدخل مفتاح API:",
        "send_model": "أدخل اسم النموذج:",
        "send_model_for_router": "أرسل الاسم الدقيق للنموذج لإضافته إلى هذا الموجه:",
        "router_added": "✅ تمت الإضافة!",
        "router_details": "📌 **الموجه:** {}\n\n🌐 الرابط: `{}`\n\n🔑 الرمز: `{}`\n\n📦 **النماذج (انقر للنسخ):**\n{}",
        "btn_add_mod": "➕ إضافة نموذج",
        "btn_del_mod": "🗑 حذف نموذج",
        "btn_del_router": "🗑 حذف الموجه",
        "del_confirm_msg": "⚠️ هل أنت متأكد؟",
        "btn_yes": "✅ نعم",
        "btn_no": "❌ لا",
        "del_success": "✅ تم الحذف.",
        "pls_select_model": "يرجى اختيار نموذج.",
        "invalid_command": "❌ أمر غير صالح.",
        "send_channel_prompt": "أرسل معرف القناة (@channel) أو none (للقنوات المتعددة، افصل بفواصل):",
        "channel_set": "✅ تم تعيين القناة(ات): `{}`",
        "channel_none": "🔓 تم إلغاء القناة الإجبارية.",
        "must_join": "⛔ يجب الاشتراك في القنوات التالية:\n{channels}",
        "btn_join_channel": "🔗 اشترك",
        "btn_check_join": "🔄 تحقق",
        "join_ok": "✅ تم التحقق!",
        "join_fail": "❌ لم تشترك في جميع القنوات بعد!",
        "send_del_model": "أرسل الاسم الدقيق للنموذج:",
        "model_deleted": "✅ تم الحذف.",
        "model_not_found": "❌ غير موجود.",
        "btn_user_mode": "👤 وضع المستخدم",
        "btn_clear_cache": "🧹 مسح الكاش (التاريخ فقط)",
        "btn_clear_all": "🗑️ مسح قاعدة البيانات بالكامل",
        "clear_cache_confirm": "🧹 سيتم حذف كل سجل المحادثات (الرسائل) من جميع المستخدمين.\n❓ هل أنت متأكد؟",
        "clear_cache_done": "✅ تم مسح تاريخ المحادثات.",
        "clear_all_confirm": "🗑️ سيتم حذف كل البيانات:\n- المستخدمين\n- الإعدادات\n- الموجهات\n- النماذج\n- سجل المحادثات\n\n❓ هل أنت متأكد؟",
        "clear_all_done": "✅ تم مسح كل البيانات.",
        "clear_cancelled": "❌ ألغي.",
        "btn_admin_panel": "⚙️ لوحة الإدارة",
        "no_cloud_db": "⚠️ لم يتم تكوين قاعدة بيانات سحابية خارجية. يتم استخدام SQLite المحلي.",
        "no_routers": "⚠️ لم تتم إضافة أي موجه API بعد.",
        "help_user": "📖 الأوامر المتاحة\n\n🚀 /start • start➜ البدء\n🌐 /lang • lang ➜ اللغة\n🤖 /model • model ➜ مسح المحادثة واختيار نموذج جديد\n📞 /man • man ➜ تواصل مع المدير\n❓ /help • help ➜ المساعدة\n\n✨ اختر وابدأ 🚀",
        "help_admin": "🌐 /lang • lang ➜ اللغة\n👤 /user • user ➜ وضع المستخدم\n🤖 /model • model ➜ مسح الكاش والنماذج\n📞 /man • man ➜ تواصل مع المدير\n❓ /help • help ➜ المساعدة\n✨ اختر وابدأ 🚀",
        "stats_text": "📊 **إحصائيات البوت**\n\n👤 المستخدمون: `{users}`\n📢 القناة(ات) الإجبارية: `{channel}`\n🤖 النماذج: `{models}`\n🗂️ الموجهات: `{routers}`\n🔑 الرموز: `{tokens}`\n🔐 كلمة المرور: `{pwd_status}`",
        "btn_view_data": "📋 عرض البيانات",
        "all_data_title": "📋 **جميع الموجهات والنماذج والرموز**\n\n",
        "data_router_header": "\n📍 **الموجه #{id}** – `{domain}`\n🌐 الرابط: `{base_url}`\n🔑 الرمز: `{api_key}`\n📦 النماذج:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (لا توجد نماذج)\n",
        "unknown_command": "❌ أمر غير معروف",
        "blocked_unauthorized": "⛔ لقد استخدمت {limit} طلب مجاني. أدخل كلمة المرور:",
        "forward_to_admin": "أمر غير معروف من @{username} (ID: {user_id}): {text}",
        "model_added_continue": "✅ تمت إضافة النموذج. أدخل اسم النموذج التالي، أو اضغط على زر «إنهاء».",
        "finish": "✅ إنهاء",
        "router_added_continue": "✅ تمت إضافة النموذج. أدخل اسم النموذج التالي، أو اضغط على زر «إنهاء».",
        "add_router_done": "✅ تم تسجيل الموجه والنماذج بنجاح.",
        "loading_data": "⏳ جاري تحميل البيانات... {progress}%",
        "data_loaded": "✅ تم تحميل البيانات بنجاح.",
        "error_occurred": "❌ حدث خطأ أثناء تحميل البيانات. يرجى المحاولة لاحقاً.",
        "error_detail": "❌ تفاصيل الخطأ: {error}",
        "limit_blocked": "⛔ لقد استخدمت {limit} طلب مجاني. أدخل كلمة المرور:",
        "contact_intro": "يرجى كتابة طلبك كرسالة كاملة للمسؤول:",
        "contact_confirm": "✅ تم إرسال رسالتك. سوف نرد في أقرب وقت. للتواصل مرة أخرى، أرسل /man.",
        "contact_end_auto": "تم الإرسال ✅ سوف نرد في أقرب وقت.\nللتواصل مرة أخرى، أرسل /man.",
        "contact_forward": "رسالة من المستخدم {name} (ID: {user_id}):\n{text}",
        "contact_button": "📞 اتصل بالمسؤول",
        "contact_admin_reply": "📩 رد من المسؤول:\n{text}",
        "admin_reply_sent": "✅ تم إرسال الرد إلى المستخدم.",
        "pwd_prompt_wrong": "⛔ أدخل كلمة المرور الصحيحة:",
        "invalid_model": "❌ هذا النموذج غير متوفر الآن. يرجى اختيار نموذج آخر."
    },
    "hi": {
        "name": "🇮🇳 हिन्दी",
        "welcome_new": "कृपया अपनी भाषा चुनें:",
        "welcome_back": "वापसी पर स्वागत है, {name}!",
        "welcome_first": "👋 स्वागत है! कमांड देखने के लिए /help का उपयोग करें।",
        "locked": "🔑 पासवर्ड दर्ज करें:",
        "pwd_ok": "✅ पासवर्ड स्वीकृत! चैट जारी रखें...",
        "pwd_err": "⛔ सही पासवर्ड दर्ज करें:",
        "pwd_none": "🔓 पासवर्ड हटाया गया।",
        "pwd_set": "✅ नया पासवर्ड: `{}`",
        "admin_only": "❌ केवल व्यवस्थापक।",
        "type_here": "संदेश लिखें...",
        "select_model": "नया चैट शुरू करने के लिए मॉडल चुनें:",
        "no_models_admin": "⚠️ कोई मॉडल उपलब्ध नहीं।",
        "no_models_user": "⚠️ कोई मॉडल उपलब्ध नहीं।",
        "chat_started": "✅ {} से कनेक्टेड।\nसंदेश भेजें:",
        "invalid_url": "❌ अमान्य URL۔",
        "admin_menu": "⚙️ उन्नत व्यवस्थापक पैनल – नीचे मेनू का उपयोग करें:",
        "title_routers": "🗂 सभी उपलब्ध API राउटरों की सूची:",
        "title_settings": "⚙️ बॉट सेटिंग्स और डेटाबेस प्रबंधन :",
        "btn_routers": "🗂 API सूची",
        "btn_add_router": "➕ राउटर जोड़ें",
        "btn_settings": "⚙️ सेटिंग्स",
        "btn_database": "🗄️ डेटाबेस",
        "btn_stats": "📊 आँकड़े और स्थिति",
        "btn_set_pwd": "🔐 पासवर्ड",
        "btn_set_channel": "📢 चैनल",
        "btn_broadcast": "📢 प्रसारण",
        "btn_back": "🔙 पीछे",
        "btn_back_main": "🏠 मुख्य मेनू",
        "send_pwd_prompt": "नया पासवर्ड भेजें (या none):",
        "send_limit_prompt": "अब अनधिकृत उपयोगकर्ताओं के लिए अनुमत संदेशों की संख्या दर्ज करें (उदा. 5):",
        "send_broadcast": "संदेश भेजें:",
        "broadcast_done": "✅ {} को भेजा गया।",
        "send_url": "Base URL भेजें:",
        "url_detected": "डोमेन: {}\nAPI कुंजी भेजें:",
        "send_model": "मॉडल का नाम भेजें:",
        "send_model_for_router": "इस राउटर में जोड़ने के लिए सटीक मॉडल नाम भेजें:",
        "router_added": "✅ जोड़ा गया!",
        "router_details": "📌 **राउटर:** {}\n\n🌐 URL: `{}`\n\n🔑 टोकन: `{}`\n\n📦 **मॉडल (कॉपी करने के लिए टैप करें):**\n{}",
        "btn_add_mod": "➕ मॉडल",
        "btn_del_mod": "🗑 मॉडल हटाएं",
        "btn_del_router": "🗑 राउटर हटाएं",
        "del_confirm_msg": "⚠️ क्या आप सुनिश्चित हैं?",
        "btn_yes": "✅ हाँ",
        "btn_no": "❌ नहीं",
        "del_success": "✅ हटा दिया गया।",
        "pls_select_model": "मॉडल चुनें।",
        "invalid_command": "❌ अमान्य कमांड।",
        "send_channel_prompt": "चैनल का नाम (@channel) या none (कई के लिए कॉमा से अलग करें):",
        "channel_set": "✅ चैनल सेट: `{}`",
        "channel_none": "🔓 चैनल बंद।",
        "must_join": "⛔ कृपया निम्न चैनलों से जुड़ें:\n{channels}",
        "btn_join_channel": "🔗 जुड़ें",
        "btn_check_join": "🔄 जांचें",
        "join_ok": "✅ सदस्यता सत्यापित!",
        "join_fail": "❌ आप अभी तक सभी चैनलों से नहीं जुड़े हैं!",
        "send_del_model": "हटाने के लिए सटीक मॉडल नाम:",
        "model_deleted": "✅ हटाया गया।",
        "model_not_found": "❌ नहीं मिला।",
        "btn_user_mode": "👤 उपयोगकर्ता मोड",
        "btn_clear_cache": "🧹 कैश साफ़ करें (केवल इतिहास)",
        "btn_clear_all": "🗑️ पूर्ण डेटाबेस साफ़ करें",
        "clear_cache_confirm": "🧹 यह सभी उपयोगकर्ताओं की चैट इतिहास (संदेश) हटा देगा।\n❓ क्या आप निश्चित हैं?",
        "clear_cache_done": "✅ चैट इतिहास साफ़ हो गया।",
        "clear_all_confirm": "🗑️ यह सभी डेटा हटा देगा:\n- उपयोगकर्ता\n- सेटिंग्स\n- राउटर\n- मॉडल\n- चैट इतिहास\n\n❓ क्या आप निश्चित हैं?",
        "clear_all_done": "✅ सभी डेटा साफ़ हो गए।",
        "clear_cancelled": "❌ रद्द।",
        "btn_admin_panel": "⚙️ व्यवस्थापक पैनल",
        "no_cloud_db": "⚠️ कोई बाहरी क्लाउड डेटाबेस कॉन्फ़िगर नहीं है। स्थानीय SQLite का उपयोग होगा।",
        "no_routers": "⚠️ अभी तक कोई API राउटर नहीं जोड़ा गया।",
        "help_user": "📖 उपलब्ध कमांड\n\n🚀 /start • start➜ शुरू करें\n🌐 /lang • lang ➜ भाषा\n🤖 /model • model ➜ चैट साफ़ करें और नया मॉडल चुनें\n📞 /man • man ➜ व्यवस्थापक से संपर्क करें\n❓ /help • help ➜ सहायता\n\n✨ चुनें और शुरू करें 🚀",
        "help_admin": "🌐 /lang • lang ➜ भाषा\n👤 /user • user ➜ उपयोगकर्ता मोड\n🤖 /model • model ➜ कैश और मॉडल साफ़ करें\n📞 /man • man ➜ व्यवस्थापक से संपर्क करें\n❓ /help • help ➜ सहायता\n✨ चुनें और शुरू करें 🚀",
        "stats_text": "📊 **बॉट आँकड़े**\n\n👤 उपयोगकर्ता: `{users}`\n📢 अनिवार्य चैनल: `{channel}`\n🤖 मॉडल: `{models}`\n🗂️ राउटर: `{routers}`\n🔑 टोकन: `{tokens}`\n🔐 पासवर्ड: `{pwd_status}`",
        "btn_view_data": "📋 डेटा देखें",
        "all_data_title": "📋 **सभी राउटर, मॉडल और टोकन**\n\n",
        "data_router_header": "\n📍 **राउटर #{id}** – `{domain}`\n🌐 URL: `{base_url}`\n🔑 टोकन: `{api_key}`\n📦 मॉडल:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (कोई मॉडल नहीं)\n",
        "unknown_command": "❌ अज्ञात कमांड",
        "blocked_unauthorized": "⛔ आपने {limit} निःशुल्क अनुरोधों का उपयोग कर लिया है। कृपया पासवर्ड दर्ज करें:",
        "forward_to_admin": "@{username} (ID: {user_id}) से अज्ञात कमांड: {text}",
        "model_added_continue": "✅ मॉडल जोड़ा गया। अगला मॉडल नाम दर्ज करें, या 'समाप्त' बटन दबाएँ।",
        "finish": "✅ समाप्त",
        "router_added_continue": "✅ मॉडल जोड़ा गया। अगला मॉडल नाम दर्ज करें, या 'समाप्त' बटन दबाएँ।",
        "add_router_done": "✅ राउटर और मॉडल सफलतापूर्वक पंजीकृत हो गए।",
        "loading_data": "⏳ डेटा लोड हो रहा है... {progress}%",
        "data_loaded": "✅ डेटा सफलतापूर्वक लोड हो गया।",
        "error_occurred": "❌ डेटा लोड करते समय त्रुटि हुई। कृपया बाद में प्रयास करें।",
        "error_detail": "❌ त्रुटि विवरण: {error}",
        "limit_blocked": "⛔ आपने {limit} निःशुल्क अनुरोधों का उपयोग कर लिया है। कृपया पासवर्ड दर्ज करें:",
        "contact_intro": "कृपया अपना अनुरोध व्यवस्थापक को पूर्ण संदेश के रूप में लिखें:",
        "contact_confirm": "✅ आपका संदेश भेज दिया गया है। हम जल्द से जल्द जवाब देंगे। पुनः संपर्क के लिए /man भेजें।",
        "contact_end_auto": "भेजा गया ✅ हम जल्द से जल्द जवाब देंगे।\nपुनः संपर्क के लिए /man भेजें।",
        "contact_forward": "उपयोगकर्ता {name} (ID: {user_id}) से संदेश:\n{text}",
        "contact_button": "📞 व्यवस्थापक से संपर्क करें",
        "contact_admin_reply": "📩 व्यवस्थापक का उत्तर:\n{text}",
        "admin_reply_sent": "✅ उत्तर उपयोगकर्ता को भेज दिया गया।",
        "pwd_prompt_wrong": "⛔ सही पासवर्ड दर्ज करें:",
        "invalid_model": "❌ यह मॉडल अब उपलब्ध नहीं है। कृपया दूसरा मॉडल चुनें。"
    },
    "tr": {
        "name": "🇹🇷 Türkçe",
        "welcome_new": "Lütfen dilinizi seçin:",
        "welcome_back": "Tekrar hoş geldiniz, {name}!",
        "welcome_first": "👋 Hoş geldiniz! Komutları görmek için /help kullanın.",
        "locked": "⛔ Şifreyi girin:",
        "pwd_ok": "✅ Şifre kabul edildi! Sohbete devam edin...",
        "pwd_err": "⛔ Doğru şifreyi girin:",
        "pwd_none": "🔓 Şifre kaldırıldı.",
        "pwd_set": "✅ Yeni şifre: `{}`",
        "admin_only": "❌ Sadece yönetici.",
        "type_here": "Mesajınızı yazın...",
        "select_model": "Yeni bir sohbet için model seçin:",
        "no_models_admin": "⚠️ Mevcut model yok.",
        "no_models_user": "⚠️ Mevcut model yok.",
        "chat_started": "✅ {} bağlanıldı.\nMesajınızı gönderin:",
        "invalid_url": "❌ Geçersiz URL.",
        "admin_menu": "⚙️ Gelişmiş Yönetici Paneli – menüyü kullanın:",
        "title_routers": "🗂 Mevcut tüm API yönlendiricilerinin listesi:",
        "title_settings": "⚙️ Bot ayarları ve veritabanı yönetimi :",
        "btn_routers": "🗂 API Listesi",
        "btn_add_router": "➕ Yönlendirici",
        "btn_settings": "⚙️ Ayarlar",
        "btn_database": "🗄️ Veritabanı",
        "btn_stats": "📊 İstatistik ve Durum",
        "btn_set_pwd": "🔐 Şifre",
        "btn_set_channel": "📢 Kanal",
        "btn_broadcast": "📢 Duyuru",
        "btn_back": "🔙 Geri",
        "btn_back_main": "🏠 Ana Menü",
        "send_pwd_prompt": "Yeni şifre (veya none):",
        "send_limit_prompt": "Şimdi yetkisiz kullanıcılar için izin verilen mesaj sayısını girin (ör. 5):",
        "send_broadcast": "Duyuru gönderin:",
        "broadcast_done": "✅ {} kişiye gönderildi.",
        "send_url": "Base URL:",
        "url_detected": "Alan adı: {}\nAPI Anahtarı:",
        "send_model": "Model adını gönderin:",
        "send_model_for_router": "Bu yönlendiriciye eklemek için tam model adını gönderin:",
        "router_added": "✅ Eklendi!",
        "router_details": "📌 **Yönlendirici:** {}\n\n🌐 URL: `{}`\n\n🔑 Token: `{}`\n\n📦 **Modeller (kopyalamak için tıklayın):**\n{}",
        "btn_add_mod": "➕ Model",
        "btn_del_mod": "🗑 Model Sil",
        "btn_del_router": "🗑 Yönlendirici Sil",
        "del_confirm_msg": "⚠️ Emin misiniz?",
        "btn_yes": "✅ Evet",
        "btn_no": "❌ Hayır",
        "del_success": "✅ Silindi.",
        "pls_select_model": "Model seçin.",
        "invalid_command": "❌ Geçersiz komut.",
        "send_channel_prompt": "Kanal adını (@channel) veya none (birden fazla için virgülle ayırın):",
        "channel_set": "✅ Kanal(lar) ayarlandı: `{}`",
        "channel_none": "🔓 Zorunlu kanal iptal edildi.",
        "must_join": "⛔ Lütfen aşağıdaki kanallara katılın:\n{channels}",
        "btn_join_channel": "🔗 Katıl",
        "btn_check_join": "🔄 Kontrol Et",
        "join_ok": "✅ Katılım onaylandı!",
        "join_fail": "❌ Henüz tüm kanallara katılmadınız!",
        "send_del_model": "Tam model adını gönderin:",
        "model_deleted": "✅ Silindi.",
        "model_not_found": "❌ Bulunamadı.",
        "btn_user_mode": "👤 Kullanıcı Modu",
        "btn_clear_cache": "🧹 Önbelleği temizle (sadece geçmiş)",
        "btn_clear_all": "🗑️ Veritabanını tamamen temizle",
        "clear_cache_confirm": "🧹 Bu, tüm kullanıcıların sohbet geçmişini (mesajlar) siler.\n❓ Emin misiniz?",
        "clear_cache_done": "✅ Sohbet geçmişi temizlendi.",
        "clear_all_confirm": "🗑️ Bu, TÜM verileri siler:\n- Kullanıcılar\n- Ayarlar\n- Yönlendiriciler\n- Modeller\n- Sohbet geçmişi\n\n❓ Emin misiniz?",
        "clear_all_done": "✅ Tüm veriler temizlendi.",
        "clear_cancelled": "❌ İptal.",
        "btn_admin_panel": "⚙️ Yönetici Paneli",
        "no_cloud_db": "⚠️ Harici bulut veritabanı yapılandırılmamış. Yerel SQLite kullanılıyor.",
        "no_routers": "⚠️ Henüz hiç API yönlendiricisi eklenmemiş.",
        "help_user": "📖 Mevcut Komutlar\n\n🚀 /start • start➜ Başlat\n🌐 /lang • lang ➜ Dil\n🤖 /model • model ➜ Sohbeti temizle ve yeni model seç\n📞 /man • man ➜ Yöneticiyle iletişime geç\n❓ /help • help ➜ Yardım\n\n✨ Seç ve başla 🚀",
        "help_admin": "🌐 /lang • lang ➜ Dil\n👤 /user • user ➜ Kullanıcı modu\n🤖 /model • model ➜ Önbellek ve modelleri temizle\n📞 /man • man ➜ Yöneticiyle iletişime geç\n❓ /help • help ➜ Yardım\n✨ Seç ve başla 🚀",
        "stats_text": "📊 **Bot İstatistikleri**\n\n👤 Kullanıcılar: `{users}`\n📢 Zorunlu Kanal(lar): `{channel}`\n🤖 Modeller: `{models}`\n🗂️ Yönlendiriciler: `{routers}`\n🔑 Tokenlar: `{tokens}`\n🔐 Şifre: `{pwd_status}`",
        "btn_view_data": "📋 Verileri Görüntüle",
        "all_data_title": "📋 **Tüm Yönlendiriciler, Modeller ve Tokenlar**\n\n",
        "data_router_header": "\n📍 **Yönlendirici #{id}** – `{domain}`\n🌐 URL: `{base_url}`\n🔑 Token: `{api_key}`\n📦 Modeller:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (model yok)\n",
        "unknown_command": "❌ Bilinmeyen komut",
        "blocked_unauthorized": "⛔ {limit} ücretsiz istek hakkınızı kullandınız. Lütfen şifreyi girin:",
        "forward_to_admin": "@{username} (ID: {user_id}) adlı kullanıcıdan bilinmeyen komut: {text}",
        "model_added_continue": "✅ Model eklendi. Sonraki model adını girin veya 'Bitir' butonuna basın.",
        "finish": "✅ Bitir",
        "router_added_continue": "✅ Model eklendi. Sonraki model adını girin veya 'Bitir' butonuna basın.",
        "add_router_done": "✅ Yönlendirici ve modeller başarıyla kaydedildi.",
        "loading_data": "⏳ Veri yükleniyor... {progress}%",
        "data_loaded": "✅ Veriler başarıyla yüklendi.",
        "error_occurred": "❌ Veri yüklenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin.",
        "error_detail": "❌ Hata ayrıntıları: {error}",
        "limit_blocked": "⛔ {limit} ücretsiz istek hakkınızı kullandınız. Lütfen şifreyi girin:",
        "contact_intro": "Lütfen talebinizi yöneticiye tam bir mesaj olarak yazın:",
        "contact_confirm": "✅ Mesajınız gönderildi. En kısa sürede cevap vereceğiz. Tekrar iletişim için /man gönderin.",
        "contact_end_auto": "Gönderildi ✅ En kısa sürede cevap vereceğiz.\nTekrar iletişim için /man gönderin.",
        "contact_forward": "{name} kullanıcısından (ID: {user_id}) mesaj:\n{text}",
        "contact_button": "📞 Yöneticiyle iletişime geç",
        "contact_admin_reply": "📩 Yöneticiden yanıt:\n{text}",
        "admin_reply_sent": "✅ Yanıt kullanıcıya gönderildi.",
        "pwd_prompt_wrong": "⛔ Doğru şifreyi girin:",
        "invalid_model": "❌ Bu model artık mevcut değil. Lütfen başka bir model seçin."
    },
    "fr": {
        "name": "🇫🇷 Français",
        "welcome_new": "Choisissez votre langue :",
        "welcome_back": "Bon retour, {name} !",
        "welcome_first": "👋 Bienvenue ! Utilisez /help pour voir les commandes.",
        "locked": "⛔ Entrez le mot de passe :",
        "pwd_ok": "✅ Mot de passe accepté ! Continuez la discussion...",
        "pwd_err": "⛔ Veuillez entrer le mot de passe correct :",
        "pwd_none": "🔓 MDP supprimé.",
        "pwd_set": "✅ Nouveau MDP : `{}`",
        "admin_only": "❌ Admin uniquement.",
        "type_here": "Tapez votre message...",
        "select_model": "Sélectionnez un modèle pour commencer :",
        "no_models_admin": "⚠️ Aucun modèle disponible.",
        "no_models_user": "⚠️ Aucun modèle disponible.",
        "chat_started": "✅ Connecté à {}.\nEnvoyez votre message :",
        "invalid_url": "❌ URL invalide.",
        "admin_menu": "⚙️ Panneau d'administration avancé – utilisez le menu ci-dessous :",
        "title_routers": "🗂 Liste de tous les routeurs API disponibles :",
        "title_settings": "⚙️ Paramètres du bot et gestion de la base de données :",
        "btn_routers": "🗂 Liste API",
        "btn_add_router": "➕ Routeur",
        "btn_settings": "⚙️ Paramètres",
        "btn_database": "🗄️ Base de données",
        "btn_stats": "📊 Statistiques et statut",
        "btn_set_pwd": "🔐 MDP",
        "btn_set_channel": "📢 Canal",
        "btn_broadcast": "📢 Diffusion",
        "btn_back": "🔙 Retour",
        "btn_back_main": "🏠 Menu",
        "send_pwd_prompt": "Nouveau mot de passe (ou none) :",
        "send_limit_prompt": "Entrez maintenant le nombre de messages autorisés pour les utilisateurs non autorisés (ex. 5) :",
        "send_broadcast": "Envoyez le message :",
        "broadcast_done": "✅ Envoyé à {}.",
        "send_url": "URL de base :",
        "url_detected": "Domaine : {}\nClé API :",
        "send_model": "Nom du modèle :",
        "send_model_for_router": "Envoyez le nom exact du modèle à ajouter à ce routeur :",
        "router_added": "✅ Ajouté !",
        "router_details": "📌 **Routeur :** {}\n\n🌐 URL : `{}`\n\n🔑 Jeton : `{}`\n\n📦 **Modèles (appuyez pour copier) :**\n{}",
        "btn_add_mod": "➕ Modèle",
        "btn_del_mod": "🗑 Supprimer",
        "btn_del_router": "🗑 Supprimer Routeur",
        "del_confirm_msg": "⚠️ Sûr ?",
        "btn_yes": "✅ Oui",
        "btn_no": "❌ Non",
        "del_success": "✅ Supprimé.",
        "pls_select_model": "Choisissez un modèle.",
        "invalid_command": "❌ Commande invalide.",
        "send_channel_prompt": "Envoyez le nom du canal (@canal) ou none (pour plusieurs, séparez par des virgules) :",
        "channel_set": "✅ Canal(aux) défini(s) : `{}`",
        "channel_none": "🔓 Canal désactivé.",
        "must_join": "⛔ Veuillez rejoindre les canaux suivants :\n{channels}",
        "btn_join_channel": "🔗 Rejoindre",
        "btn_check_join": "🔄 Vérifier",
        "join_ok": "✅ Abonnement vérifié !",
        "join_fail": "❌ Vous n'avez pas rejoint tous les canaux !",
        "send_del_model": "Nom exact du modèle :",
        "model_deleted": "✅ Supprimé.",
        "model_not_found": "❌ Introuvable.",
        "btn_user_mode": "👤 Mode utilisateur",
        "btn_clear_cache": "🧹 Vider le cache (historique uniquement)",
        "btn_clear_all": "🗑️ Nettoyage complet de la base",
        "clear_cache_confirm": "🧹 Cela supprimera tout l'historique des conversations (messages) de tous les utilisateurs.\n❓ Êtes-vous sûr ?",
        "clear_cache_done": "✅ Historique des conversations effacé.",
        "clear_all_confirm": "🗑️ Cela supprimera TOUTES les données :\n- Utilisateurs\n- Paramètres\n- Routeurs\n- Modèles\n- Historique des chats\n\n❓ Êtes-vous sûr ?",
        "clear_all_done": "✅ Toutes les données ont été effacées.",
        "clear_cancelled": "❌ Annulé.",
        "btn_admin_panel": "⚙️ Panneau d'administration",
        "no_cloud_db": "⚠️ Aucune base de données cloud externe configurée. Utilisation de SQLite local.",
        "no_routers": "⚠️ Aucun routeur API n'a encore été ajouté.",
        "help_user": "📖 Commandes disponibles\n\n🚀 /start • start➜ Démarrer\n🌐 /lang • lang ➜ Langue\n🤖 /model • model ➜ Effacer le chat et choisir un nouveau modèle\n📞 /man • man ➜ Contacter l'administrateur\n❓ /help • help ➜ Aide\n\n✨ Choisissez et commencez 🚀",
        "help_admin": "🌐 /lang • lang ➜ Langue\n👤 /user • user ➜ Mode utilisateur\n🤖 /model • model ➜ Vider le cache et les modèles\n📞 /man • man ➜ Contacter l'administrateur\n❓ /help • help ➜ Aide\n✨ Choisissez et commencez 🚀",
        "stats_text": "📊 **Statistiques du bot**\n\n👤 Utilisateurs : `{users}`\n📢 Canal(aux) obligatoire(s) : `{channel}`\n🤖 Modèles : `{models}`\n🗂️ Routeurs : `{routers}`\n🔑 Jetons : `{tokens}`\n🔐 Mot de passe : `{pwd_status}`",
        "btn_view_data": "📋 Voir les données",
        "all_data_title": "📋 **Tous les routeurs, modèles et jetons**\n\n",
        "data_router_header": "\n📍 **Routeur #{id}** – `{domain}`\n🌐 URL : `{base_url}`\n🔑 Jeton : `{api_key}`\n📦 Modèles :\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (aucun modèle)\n",
        "unknown_command": "❌ Commande inconnue",
        "blocked_unauthorized": "⛔ Vous avez utilisé vos {limit} demandes gratuites. Veuillez entrer le mot de passe :",
        "forward_to_admin": "Commande inconnue de @{username} (ID: {user_id}) : {text}",
        "model_added_continue": "✅ Modèle ajouté. Entrez le nom du modèle suivant, ou appuyez sur le bouton « Terminer ».",
        "finish": "✅ Terminer",
        "router_added_continue": "✅ Modèle ajouté. Entrez le nom du modèle suivant, ou appuyez sur le bouton « Terminer ».",
        "add_router_done": "✅ Routeur et modèles enregistrés avec succès.",
        "loading_data": "⏳ Chargement des données... {progress}%",
        "data_loaded": "✅ Données chargées avec succès.",
        "error_occurred": "❌ Une erreur est survenue lors du chargement des données. Veuillez réessayer plus tard.",
        "error_detail": "❌ Détails de l'erreur : {error}",
        "limit_blocked": "⛔ Vous avez utilisé vos {limit} demandes gratuites. Veuillez entrer le mot de passe :",
        "contact_intro": "Veuillez écrire votre demande sous forme de message complet à l'administrateur :",
        "contact_confirm": "✅ Votre message a été envoyé. Nous répondrons dans les plus brefs délais. Pour recontacter, envoyez /man.",
        "contact_end_auto": "Envoyé ✅ Nous répondrons dans les plus brefs délais.\nPour recontacter, envoyez /man.",
        "contact_forward": "Message de l'utilisateur {name} (ID: {user_id}) :\n{text}",
        "contact_button": "📞 Contacter l'administrateur",
        "contact_admin_reply": "📩 Réponse de l'administrateur :\n{text}",
        "admin_reply_sent": "✅ Réponse envoyée à l'utilisateur.",
        "pwd_prompt_wrong": "⛔ Veuillez entrer le mot de passe correct :",
        "invalid_model": "❌ Ce modèle n'est plus disponible. Veuillez en choisir un autre."
    },
    "de": {
        "name": "🇩🇪 Deutsch",
        "welcome_new": "Sprache wählen:",
        "welcome_back": "Willkommen, {name}!",
        "welcome_first": "👋 Willkommen! Nutze /help für Befehle.",
        "locked": "⛔ Passwort eingeben:",
        "pwd_ok": "✅ Passwort akzeptiert! Setzen Sie die Unterhaltung fort...",
        "pwd_err": "⛔ Bitte geben Sie das richtige Passwort ein:",
        "pwd_none": "🔓 Passwort entfernt.",
        "pwd_set": "✅ Neues Passwort: `{}`",
        "admin_only": "❌ Nur Admin.",
        "type_here": "Nachricht...",
        "select_model": "Modell für neuen Chat wählen:",
        "no_models_admin": "⚠️ Keine Modelle verfügbar.",
        "no_models_user": "⚠️ Keine Modelle verfügbar.",
        "chat_started": "✅ Verbunden mit {}.\nNachricht senden:",
        "invalid_url": "❌ Ungültige URL.",
        "admin_menu": "⚙️ Erweitertes Admin-Panel – Menü unten:",
        "title_routers": "🗂 Liste aller verfügbaren API-Router:",
        "title_settings": "⚙️ Bot-Einstellungen und Datenbankverwaltung :",
        "btn_routers": "🗂 API-Liste",
        "btn_add_router": "➕ Router",
        "btn_settings": "⚙️ Einstellungen",
        "btn_database": "🗄️ Datenbank",
        "btn_stats": "📊 Statistiken und Status",
        "btn_set_pwd": "🔐 Passwort",
        "btn_set_channel": "📢 Kanal",
        "btn_broadcast": "📢 Broadcast",
        "btn_back": "🔙 Zurück",
        "btn_back_main": "🏠 Hauptmenü",
        "send_pwd_prompt": "Neues Passwort (oder none):",
        "send_limit_prompt": "Geben Sie nun die Anzahl der Nachrichten ein, die für nicht autorisierte Benutzer erlaubt sind (z.B. 5):",
        "send_broadcast": "Nachricht senden:",
        "broadcast_done": "✅ An {} gesendet.",
        "send_url": "Base URL:",
        "url_detected": "Domain: {}\nAPI-Key:",
        "send_model": "Modellname:",
        "send_model_for_router": "Senden Sie den genauen Modellnamen, um ihn zu diesem Router hinzuzufügen:",
        "router_added": "✅ Hinzugefügt!",
        "router_details": "📌 **Router:** {}\n\n🌐 URL: `{}`\n\n🔑 Token: `{}`\n\n📦 **Modelle (zum Kopieren tippen):**\n{}",
        "btn_add_mod": "➕ Modell",
        "btn_del_mod": "🗑 Modell löschen",
        "btn_del_router": "🗑 Router löschen",
        "del_confirm_msg": "⚠️ Sicher?",
        "btn_yes": "✅ Ja",
        "btn_no": "❌ Nein",
        "del_success": "✅ Gelöscht.",
        "pls_select_model": "Modell wählen.",
        "invalid_command": "❌ Ungültig.",
        "send_channel_prompt": "Kanalname (@kanal) oder none (für mehrere mit Komma trennen):",
        "channel_set": "✅ Kanal(kanäle) gesetzt: `{}`",
        "channel_none": "🔓 Pflichtkanal deaktiviert.",
        "must_join": "⛔ Bitte den folgenden Kanälen beitreten:\n{channels}",
        "btn_join_channel": "🔗 Beitreten",
        "btn_check_join": "🔄 Prüfen",
        "join_ok": "✅ Mitgliedschaft geprüft!",
        "join_fail": "❌ Sie sind noch nicht allen Kanälen beigetreten!",
        "send_del_model": "Exakten Modellnamen:",
        "model_deleted": "✅ Gelöscht.",
        "model_not_found": "❌ Nicht gefunden.",
        "btn_user_mode": "👤 Benutzermodus",
        "btn_clear_cache": "🧹 Cache leeren (nur Verlauf)",
        "btn_clear_all": "🗑️ Vollständige Datenbanklöschung",
        "clear_cache_confirm": "🧹 Dies löscht den gesamten Chatverlauf (Nachrichten) aller Benutzer.\n❓ Sicher?",
        "clear_cache_done": "✅ Chatverlauf gelöscht.",
        "clear_all_confirm": "🗑️ Dies löscht ALLE Daten:\n- Benutzer\n- Einstellungen\n- Router\n- Modelle\n- Chatverlauf\n\n❓ Sicher?",
        "clear_all_done": "✅ Alle Daten gelöscht.",
        "clear_cancelled": "❌ Abgebrochen.",
        "btn_admin_panel": "⚙️ Admin-Panel",
        "no_cloud_db": "⚠️ Keine externe Cloud-DB konfiguriert. Lokale SQLite wird verwendet.",
        "no_routers": "⚠️ Es wurden noch keine API-Router hinzugefügt.",
        "help_user": "📖 Verfügbare Befehle\n\n🚀 /start • start➜ Start\n🌐 /lang • lang ➜ Sprache\n🤖 /model • model ➜ Chat löschen und neues Modell wählen\n📞 /man • man ➜ Administrator kontaktieren\n❓ /help • help ➜ Hilfe\n\n✨ Wähle und starte 🚀",
        "help_admin": "🌐 /lang • lang ➜ Sprache\n👤 /user • user ➜ Benutzermodus\n🤖 /model • model ➜ Cache und Modelle löschen\n📞 /man • man ➜ Administrator kontaktieren\n❓ /help • help ➜ Hilfe\n✨ Wähle und starte 🚀",
        "stats_text": "📊 **Bot-Statistiken**\n\n👤 Benutzer: `{users}`\n📢 Pflichtkanal(e): `{channel}`\n🤖 Modelle: `{models}`\n🗂️ Router: `{routers}`\n🔑 Tokens: `{tokens}`\n🔐 Passwort: `{pwd_status}`",
        "btn_view_data": "📋 Daten anzeigen",
        "all_data_title": "📋 **Alle Router, Modelle und Tokens**\n\n",
        "data_router_header": "\n📍 **Router #{id}** – `{domain}`\n🌐 URL: `{base_url}`\n🔑 Token: `{api_key}`\n📦 Modelle:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (keine Modelle)\n",
        "unknown_command": "❌ Unbekannter Befehl",
        "blocked_unauthorized": "⛔ Sie haben Ihre {limit} kostenlosen Anfragen aufgebraucht. Bitte geben Sie das Passwort ein:",
        "forward_to_admin": "Unbekannter Befehl von @{username} (ID: {user_id}): {text}",
        "model_added_continue": "✅ Modell hinzugefügt. Geben Sie den nächsten Modellnamen ein oder drücken Sie die Schaltfläche 'Fertig'.",
        "finish": "✅ Fertig",
        "router_added_continue": "✅ Modell hinzugefügt. Geben Sie den nächsten Modellnamen ein oder drücken Sie die Schaltfläche 'Fertig'.",
        "add_router_done": "✅ Router und Modelle erfolgreich registriert.",
        "loading_data": "⏳ Daten werden geladen... {progress}%",
        "data_loaded": "✅ Daten erfolgreich geladen.",
        "error_occurred": "❌ Beim Laden der Daten ist ein Fehler aufgetreten. Bitte versuchen Sie es später erneut.",
        "error_detail": "❌ Fehlerdetails: {error}",
        "limit_blocked": "⛔ Sie haben Ihre {limit} kostenlosen Anfragen aufgebraucht. Bitte geben Sie das Passwort ein:",
        "contact_intro": "Bitte schreiben Sie Ihre Anfrage als vollständige Nachricht an den Administrator:",
        "contact_confirm": "✅ Ihre Nachricht wurde gesendet. Wir werden so schnell wie möglich antworten. Für erneute Kontaktaufnahme senden Sie /man.",
        "contact_end_auto": "Gesendet ✅ Wir werden so schnell wie möglich antworten.\nFür erneute Kontaktaufnahme senden Sie /man.",
        "contact_forward": "Nachricht von Benutzer {name} (ID: {user_id}):\n{text}",
        "contact_button": "📞 Administrator kontaktieren",
        "contact_admin_reply": "📩 Antwort vom Administrator:\n{text}",
        "admin_reply_sent": "✅ Antwort an Benutzer gesendet.",
        "pwd_prompt_wrong": "⛔ Bitte geben Sie das richtige Passwort ein:",
        "invalid_model": "❌ Dieses Modell ist nicht mehr verfügbar. Bitte wählen Sie ein anderes."
    },
    "zh": {
        "name": "🇨🇳 中文",
        "welcome_new": "请选择语言：",
        "welcome_back": "欢迎，{name}！",
        "welcome_first": "👋 欢迎！使用 /help 查看命令。",
        "locked": "⛔ 请输入密码：",
        "pwd_ok": "✅ 密码正确！继续聊天...",
        "pwd_err": "⛔ 请输入正确的密码：",
        "pwd_none": "🔓 密码已移除。",
        "pwd_set": "✅ 新密码：`{}`",
        "admin_only": "❌ 仅限管理员。",
        "type_here": "输入消息...",
        "select_model": "选择模型以开始新聊天：",
        "no_models_admin": "⚠️ 没有可用模型。",
        "no_models_user": "⚠️ 没有可用模型。",
        "chat_started": "✅ 连接到 {}。\n发送您的消息：",
        "invalid_url": "❌ 无效 URL。",
        "admin_menu": "⚙️ 高级管理面板 – 使用下方菜单：",
        "title_routers": "🗂 所有可用 API 路由器列表：",
        "title_settings": "⚙️ 机器人设置与数据库管理 :",
        "btn_routers": "🗂 API 列表",
        "btn_add_router": "➕ 添加路由",
        "btn_settings": "⚙️ 设置",
        "btn_database": "🗄️ 数据库",
        "btn_stats": "📊 统计与状态",
        "btn_set_pwd": "🔐 密码",
        "btn_set_channel": "📢 频道",
        "btn_broadcast": "📢 广播",
        "btn_back": "🔙 返回",
        "btn_back_main": "🏠 主菜单",
        "send_pwd_prompt": "发送新密码（或 none）：",
        "send_limit_prompt": "现在输入未经授权用户允许的消息数量（例如：5）：",
        "send_broadcast": "发送广播：",
        "broadcast_done": "✅ 已发送给 {}。",
        "send_url": "Base URL：",
        "url_detected": "域：{}\nAPI 密钥：",
        "send_model": "模型名称：",
        "send_model_for_router": "发送要添加到此路由器的确切模型名称：",
        "router_added": "✅ 添加成功！",
        "router_details": "📌 **路由：** {}\n\n🌐 地址：`{}`\n\n🔑 密钥：`{}`\n\n📦 **模型（点击复制）：**\n{}",
        "btn_add_mod": "➕ 模型",
        "btn_del_mod": "🗑 删除模型",
        "btn_del_router": "🗑 删除路由",
        "del_confirm_msg": "⚠️ 确定吗？",
        "btn_yes": "✅ 是",
        "btn_no": "❌ 否",
        "del_success": "✅ 已删除。",
        "pls_select_model": "请选择模型。",
        "invalid_command": "❌ 无效命令。",
        "send_channel_prompt": "发送频道名 (@channel) 或 none（多个用逗号分隔）：",
        "channel_set": "✅ 频道已设置：`{}`",
        "channel_none": "🔓 强制订阅已关闭。",
        "must_join": "⛔ 请先加入以下频道：\n{channels}",
        "btn_join_channel": "🔗 加入频道",
        "btn_check_join": "🔄 检查",
        "join_ok": "✅ 验证通过！",
        "join_fail": "❌ 您尚未加入所有频道！",
        "send_del_model": "要删除的准确模型名称：",
        "model_deleted": "✅ 已删除。",
        "model_not_found": "❌ 找不到模型。",
        "btn_user_mode": "👤 用户模式",
        "btn_clear_cache": "🧹 清除缓存（仅历史）",
        "btn_clear_all": "🗑️ 完全清除数据库",
        "clear_cache_confirm": "🧹 这将删除所有用户的聊天历史（消息）。\n❓ 您确定吗？",
        "clear_cache_done": "✅ 聊天历史已清除。",
        "clear_all_confirm": "🗑️ 这将删除所有数据：\n- 用户\n- 设置\n- 路由器\n- 模型\n- 聊天记录\n\n❓ 您确定吗？",
        "clear_all_done": "✅ 所有数据已清除。",
        "clear_cancelled": "❌ 已取消。",
        "btn_admin_panel": "⚙️ 管理面板",
        "no_cloud_db": "⚠️ 未配置外部云数据库。使用本地 SQLite。",
        "no_routers": "⚠️ 尚未添加任何 API 路由器。",
        "help_user": "📖 可用命令\n\n🚀 /start • start➜ 开始\n🌐 /lang • lang ➜ 语言\n🤖 /model • model ➜ 清除聊天并选择新模型\n📞 /man • man ➜ 联系管理员\n❓ /help • help ➜ 帮助\n\n✨ 选择并开始 🚀",
        "help_admin": "🌐 /lang • lang ➜ 语言\n👤 /user • user ➜ 用户模式\n🤖 /model • model ➜ 清除缓存和模型\n📞 /man • man ➜ 联系管理员\n❓ /help • help ➜ 帮助\n✨ 选择并开始 🚀",
        "stats_text": "📊 **机器人统计**\n\n👤 用户：`{users}`\n📢 强制频道：`{channel}`\n🤖 模型：`{models}`\n🗂️ 路由器：`{routers}`\n🔑 令牌：`{tokens}`\n🔐 密码：`{pwd_status}`",
        "btn_view_data": "📋 查看数据",
        "all_data_title": "📋 **所有路由器、模型和令牌**\n\n",
        "data_router_header": "\n📍 **路由器 #{id}** – `{domain}`\n🌐 地址：`{base_url}`\n🔑 令牌：`{api_key}`\n📦 模型：\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (无模型)\n",
        "unknown_command": "❌ 未知命令",
        "blocked_unauthorized": "⛔ 您已用完 {limit} 次免费请求。请输入密码：",
        "forward_to_admin": "来自 @{username}（ID: {user_id}）的未知命令：{text}",
        "model_added_continue": "✅ 模型已添加。输入下一个模型名称，或按「完成」按钮。",
        "finish": "✅ 完成",
        "router_added_continue": "✅ 模型已添加。输入下一个模型名称，或按「完成」按钮。",
        "add_router_done": "✅ 路由和模型注册成功。",
        "loading_data": "⏳ 正在加载数据... {progress}%",
        "data_loaded": "✅ 数据加载成功。",
        "error_occurred": "❌ 加载数据时出错，请稍后重试。",
        "error_detail": "❌ 错误详情：{error}",
        "limit_blocked": "⛔ 您已用完 {limit} 次免费请求。请输入密码：",
        "contact_intro": "请将您的请求以完整消息的形式写给管理员：",
        "contact_confirm": "✅ 您的消息已发送。我们会尽快回复。如需再次联系，请发送 /man。",
        "contact_end_auto": "已发送 ✅ 我们会尽快回复。\n如需再次联系，请发送 /man。",
        "contact_forward": "来自用户 {name}（ID: {user_id}）的消息：\n{text}",
        "contact_button": "📞 联系管理员",
        "contact_admin_reply": "📩 管理员的回复：\n{text}",
        "admin_reply_sent": "✅ 回复已发送给用户。",
        "pwd_prompt_wrong": "⛔ 请输入正确的密码：",
        "invalid_model": "❌ 此模型不再可用。请选择其他模型。"
    }
}

async def init_db():
    await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT, is_auth INTEGER DEFAULT 0, current_model_id INTEGER, msg_count INTEGER DEFAULT 0)")
    try:
        await db.execute("ALTER TABLE users ADD COLUMN current_model_id INTEGER")
    except:
        pass
    try:
        await db.execute("ALTER TABLE users ADD COLUMN msg_count INTEGER DEFAULT 0")
    except:
        pass
    await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS routers (id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT, base_url TEXT, api_key TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS models (id INTEGER PRIMARY KEY AUTOINCREMENT, router_id INTEGER, model_name TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT)")

async def get_text(user_id, key):
    row = await db.fetchone("SELECT lang FROM users WHERE user_id = ?", (user_id,))
    lang = row[0] if row and row[0] in LANGS else "en"
    return LANGS[lang].get(key, LANGS["en"].get(key, key))

async def check_auth(user_id):
    if user_id == ADMIN_ID:
        return True
    return False

chat_mode = {}

async def is_user_authorized_for_chat(user_id):
    if user_id == ADMIN_ID:
        return True, None
    pwd_row = await db.fetchone("SELECT value FROM settings WHERE key = 'global_password'")
    global_pwd = pwd_row[0] if pwd_row else None
    if not global_pwd or global_pwd.lower() == 'none':
        return True, None
    auth_row = await db.fetchone("SELECT is_auth FROM users WHERE user_id = ?", (user_id,))
    if auth_row and auth_row[0] == 1:
        return True, None
    limit_row = await db.fetchone("SELECT value FROM settings WHERE key = 'unauth_limit'")
    limit = int(limit_row[0]) if limit_row and limit_row[0].isdigit() else 2
    row = await db.fetchone("SELECT msg_count FROM users WHERE user_id = ?", (user_id,))
    msg_count = row[0] if row else 0
    if msg_count < limit:
        await db.execute("UPDATE users SET msg_count = msg_count + 1 WHERE user_id = ?", (user_id,))
        return True, None
    else:
        if msg_count == limit:
            await db.execute("UPDATE users SET msg_count = msg_count + 1 WHERE user_id = ?", (user_id,))
        return False, (limit, msg_count)

async def check_channel_join(user_id):
    if user_id == ADMIN_ID:
        return True, None
    row = await db.fetchone("SELECT value FROM settings WHERE key = 'force_channel'")
    if not row or not row[0] or row[0].lower() == 'none':
        return True, None
    channels = [ch.strip() for ch in row[0].split(',') if ch.strip()]
    failed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ['left', 'kicked']:
                failed.append(ch)
        except:
            failed.append(ch)
    if failed:
        return False, failed
    return True, None

class BotStates(StatesGroup):
    waiting_for_password = State()
    admin_add_router_url = State()
    admin_add_router_key = State()
    admin_add_router_model = State()
    admin_add_model_only = State()
    admin_del_model_only = State()
    admin_set_password = State()
    admin_set_limit = State()
    admin_set_channel = State()
    admin_broadcast = State()
    admin_clear_cache_confirm = State()
    admin_clear_all_confirm = State()
    contact_admin = State()

def lang_keyboard():
    builder = InlineKeyboardBuilder()
    for k, v in LANGS.items():
        builder.button(text=v["name"], callback_data=f"setlang_{k}")
    builder.adjust(2)
    return builder.as_markup()

async def admin_panel_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_routers"), callback_data="admin_routers")
    builder.button(text=await get_text(user_id, "btn_add_router"), callback_data="admin_add_router")
    builder.button(text=await get_text(user_id, "btn_settings"), callback_data="admin_settings_menu")
    builder.button(text=await get_text(user_id, "btn_user_mode"), callback_data="admin_switch_user")
    builder.adjust(2, 2)
    return builder.as_markup()

async def admin_settings_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_database"), callback_data="admin_database_menu")
    builder.button(text=await get_text(user_id, "btn_stats"), callback_data="admin_stats")
    builder.button(text=await get_text(user_id, "btn_set_pwd"), callback_data="admin_pwd")
    builder.button(text=await get_text(user_id, "btn_set_channel"), callback_data="admin_channel")
    builder.button(text=await get_text(user_id, "btn_broadcast"), callback_data="admin_broadcast")
    builder.button(text=await get_text(user_id, "btn_back_main"), callback_data="admin_back")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()

async def admin_database_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_view_data"), callback_data="admin_view_data")
    builder.button(text=await get_text(user_id, "btn_clear_cache"), callback_data="admin_clear_cache")
    builder.button(text=await get_text(user_id, "btn_clear_all"), callback_data="admin_clear_all")
    builder.button(text=await get_text(user_id, "btn_back"), callback_data="admin_settings_menu")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()

def cancel_admin_keyboard(user_id, text_back):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text_back, callback_data="admin_back")]])

async def show_user_panel(target, user_id, page=0, is_admin_view=False, edit=False):
    chat_mode[user_id] = False

    joined, channels = await check_channel_join(user_id)
    if not joined:
        txt = await get_text(user_id, "must_join")
        channel_list = "\n".join([f"• {ch}" for ch in channels])
        txt = txt.format(channels=channel_list)
        kb_buttons = []
        for ch in channels:
            kb_buttons.append([InlineKeyboardButton(text=f"🔗 {ch}", url=f"https://t.me/{ch.replace('@', '')}")])
        kb_buttons.append([InlineKeyboardButton(text=await get_text(user_id, "btn_check_join"), callback_data="check_join_channel")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        if edit and hasattr(target, 'message') and hasattr(target.message, 'edit_text'):
            await target.message.edit_text(txt, reply_markup=kb)
        else:
            await target.answer(txt, reply_markup=kb)
        return

    all_models = await db.fetchall("""
        SELECT m.id, m.model_name
        FROM models m
        JOIN routers r ON m.router_id = r.id
        WHERE r.api_key IS NOT NULL AND r.api_key != ''
        ORDER BY m.id
    """)
    total = len(all_models)
    per_page = 12
    max_page = max(0, (total - 1) // per_page) if total > 0 else 0
    if page < 0:
        page = 0
    if page > max_page:
        page = max_page

    start = page * per_page
    end = min(start + per_page, total)
    page_models = all_models[start:end]

    buttons = []
    for i in range(0, len(page_models), 2):
        row = []
        for m_id, m_name in page_models[i:i+2]:
            emoji = get_model_emoji(m_name, m_id)
            short_name = shorten_model_name(m_name)
            row.append(InlineKeyboardButton(text=f"{emoji} {short_name}", callback_data=f"selmod_{m_id}"))
        buttons.append(row)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"userpage_{page-1}"))
    if page < max_page:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"userpage_{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    if user_id == ADMIN_ID and not is_admin_view:
        admin_btn_text = await get_text(user_id, "btn_admin_panel")
        buttons.append([InlineKeyboardButton(text=admin_btn_text, callback_data="go_admin_panel")])
    elif is_admin_view:
        back_text = await get_text(user_id, "btn_back_main")
        buttons.append([InlineKeyboardButton(text=back_text, callback_data="admin_back")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    select_text = await get_text(user_id, "select_model")
    if total == 0:
        select_text = await get_text(user_id, "no_models_user") if not is_admin_view else await get_text(user_id, "no_models_admin")

    if edit:
        if hasattr(target, 'message') and hasattr(target.message, 'edit_text'):
            await target.message.edit_text(select_text, reply_markup=kb)
        else:
            await target.answer(select_text, reply_markup=kb)
    else:
        await target.answer(select_text, reply_markup=kb)
@router.callback_query(lambda c: c.data.startswith("addmod_"))
async def admin_add_mod(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    rid = int(callback.data.split("_")[1])
    await state.update_data(router_id=rid)
    txt = await get_text(ADMIN_ID, "send_model_for_router")
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=back_txt, callback_data=f"router_{rid}")]
    ])
    await callback.message.edit_text(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_add_model_only)

@router.message(BotStates.admin_add_model_only)
async def admin_add_model_only_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    rid = data.get("router_id")
    if not rid:
        await state.clear()
        return
    model_name = message.text.strip()
    await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (rid, model_name))
    
    txt = await get_text(ADMIN_ID, "model_added_continue")
    finish_txt = await get_text(ADMIN_ID, "finish")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=finish_txt, callback_data=f"router_{rid}")]
    ])
    # The fix: Send a NEW message instead of editing, keeping the state active for unlimited adds
    await message.answer(txt, reply_markup=kb)
    # Note: State remains BotStates.admin_add_model_only so we can keep receiving models

@router.callback_query(lambda c: c.data.startswith("delmod_"))
async def admin_del_mod(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    rid = int(callback.data.split("_")[1])
    await state.update_data(router_id=rid)
    txt = await get_text(ADMIN_ID, "send_del_model")
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=back_txt, callback_data=f"router_{rid}")]
    ])
    await callback.message.edit_text(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_del_model_only)

@router.message(BotStates.admin_del_model_only)
async def admin_del_model_only_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    rid = data.get("router_id")
    if not rid:
        await state.clear()
        return
    model_name = message.text.strip()
    row = await db.fetchone("SELECT id FROM models WHERE router_id = ? AND model_name = ?", (rid, model_name))
    if row:
        await db.execute("DELETE FROM models WHERE id = ?", (row[0],))
        txt = await get_text(ADMIN_ID, "model_deleted")
    else:
        txt = await get_text(ADMIN_ID, "model_not_found")
    
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=back_txt, callback_data=f"router_{rid}")]
    ])
    await message.answer(txt, reply_markup=kb)
    await state.clear()

@router.callback_query(lambda c: c.data == "admin_settings_menu")
async def admin_settings_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    txt = await get_text(ADMIN_ID, "title_settings")
    kb = await admin_settings_keyboard(ADMIN_ID)
    await callback.message.edit_text(txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "admin_database_menu")
async def admin_database_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    txt = await get_text(ADMIN_ID, "title_settings")
    kb = await admin_database_keyboard(ADMIN_ID)
    await callback.message.edit_text(txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "admin_back")
async def admin_back_main(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.clear()
    txt = await get_text(ADMIN_ID, "admin_menu")
    kb = await admin_panel_keyboard(ADMIN_ID)
    await callback.message.edit_text(txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "admin_pwd")
async def admin_pwd(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    txt = await get_text(ADMIN_ID, "send_pwd_prompt")
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = cancel_admin_keyboard(ADMIN_ID, back_txt)
    await callback.message.edit_text(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_set_password)

@router.message(BotStates.admin_set_password)
async def admin_pwd_step1(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    pwd = message.text.strip()
    if pwd.lower() == 'none':
        await db.execute("DELETE FROM settings WHERE key = 'global_password'")
        txt = await get_text(ADMIN_ID, "pwd_none")
        await message.answer(txt)
        await db.execute("DELETE FROM settings WHERE key = 'unauth_limit'")
        await state.clear()
        kb = await admin_settings_keyboard(ADMIN_ID)
        txt = await get_text(ADMIN_ID, "title_settings")
        await message.answer(txt, reply_markup=kb)
    else:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_password', ?)", (pwd,))
        txt = await get_text(ADMIN_ID, "pwd_set")
        await message.answer(txt.format(pwd))
        limit_prompt = await get_text(ADMIN_ID, "send_limit_prompt")
        await message.answer(limit_prompt)
        await state.set_state(BotStates.admin_set_limit)

@router.message(BotStates.admin_set_limit)
async def admin_pwd_step2(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    limit_str = message.text.strip()
    if not limit_str.isdigit():
        limit_str = "2"
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('unauth_limit', ?)", (limit_str,))
    await message.answer(f"✅ Limit set to {limit_str}")
    await state.clear()
    kb = await admin_settings_keyboard(ADMIN_ID)
    txt = await get_text(ADMIN_ID, "title_settings")
    await message.answer(txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "admin_channel")
async def admin_channel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    txt = await get_text(ADMIN_ID, "send_channel_prompt")
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = cancel_admin_keyboard(ADMIN_ID, back_txt)
    await callback.message.edit_text(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_set_channel)

@router.message(BotStates.admin_set_channel)
async def admin_channel_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    ch = message.text.strip()
    if ch.lower() == 'none':
        await db.execute("DELETE FROM settings WHERE key = 'force_channel'")
        txt = await get_text(ADMIN_ID, "channel_none")
    else:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_channel', ?)", (ch,))
        txt = await get_text(ADMIN_ID, "channel_set")
        txt = txt.format(ch)
    
    await message.answer(txt)
    await state.clear()
    kb = await admin_settings_keyboard(ADMIN_ID)
    menu_txt = await get_text(ADMIN_ID, "title_settings")
    await message.answer(menu_txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    txt = await get_text(ADMIN_ID, "send_broadcast")
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = cancel_admin_keyboard(ADMIN_ID, back_txt)
    await callback.message.edit_text(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_broadcast)

@router.message(BotStates.admin_broadcast)
async def admin_broadcast_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    users = await db.fetchall("SELECT user_id FROM users")
    count = 0
    for u in users:
        uid = u[0]
        if uid == ADMIN_ID: continue
        try:
            await message.copy_to(uid)
            count += 1
        except:
            pass
    txt = await get_text(ADMIN_ID, "broadcast_done")
    await message.answer(txt.format(count))
    await state.clear()
    kb = await admin_settings_keyboard(ADMIN_ID)
    menu_txt = await get_text(ADMIN_ID, "title_settings")
    await message.answer(menu_txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    users_row = await db.fetchone("SELECT COUNT(*) FROM users")
    users = users_row[0] if users_row else 0
    mods_row = await db.fetchone("SELECT COUNT(*) FROM models")
    mods = mods_row[0] if mods_row else 0
    r_row = await db.fetchone("SELECT COUNT(*) FROM routers")
    routers = r_row[0] if r_row else 0
    ch_row = await db.fetchone("SELECT value FROM settings WHERE key = 'force_channel'")
    channel = ch_row[0] if ch_row else "None"
    pwd_row = await db.fetchone("SELECT value FROM settings WHERE key = 'global_password'")
    pwd = pwd_row[0] if pwd_row else "None"
    
    txt = await get_text(ADMIN_ID, "stats_text")
    txt = txt.format(users=users, channel=channel, models=mods, routers=routers, tokens="Hidden", pwd_status=pwd)
    
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_txt, callback_data="admin_settings_menu")]])
    await callback.message.edit_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

@router.callback_query(lambda c: c.data == "admin_view_data")
async def admin_view_data(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    routers = await db.fetchall("SELECT id, domain, base_url, api_key FROM routers")
    txt = await get_text(ADMIN_ID, "all_data_title")
    for r in routers:
        rid, dom, burl, key = r
        r_header = await get_text(ADMIN_ID, "data_router_header")
        txt += r_header.format(id=rid, domain=dom, base_url=burl, api_key=key)
        
        models = await db.fetchall("SELECT id, model_name FROM models WHERE router_id = ?", (rid,))
        if models:
            for m in models:
                emoji = get_model_emoji(m[1], m[0])
                m_line = await get_text(ADMIN_ID, "data_model_line")
                txt += m_line.format(name=m[1], emoji=emoji)
        else:
            txt += await get_text(ADMIN_ID, "data_no_models")
            
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_txt, callback_data="admin_database_menu")]])
    await callback.message.edit_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

@router.callback_query(lambda c: c.data == "admin_clear_cache")
async def admin_clear_cache(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    txt = await get_text(ADMIN_ID, "clear_cache_confirm")
    yes_txt = await get_text(ADMIN_ID, "btn_yes")
    no_txt = await get_text(ADMIN_ID, "btn_no")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=yes_txt, callback_data="conf_clear_cache"),
         InlineKeyboardButton(text=no_txt, callback_data="admin_database_menu")]
    ])
    await callback.message.edit_text(txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "conf_clear_cache")
async def conf_clear_cache(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await db.execute("DELETE FROM history")
    txt = await get_text(ADMIN_ID, "clear_cache_done")
    await callback.answer(txt, show_alert=True)
    await admin_database_menu(callback)

@router.callback_query(lambda c: c.data == "admin_clear_all")
async def admin_clear_all(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    txt = await get_text(ADMIN_ID, "clear_all_confirm")
    yes_txt = await get_text(ADMIN_ID, "btn_yes")
    no_txt = await get_text(ADMIN_ID, "btn_no")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=yes_txt, callback_data="conf_clear_all"),
         InlineKeyboardButton(text=no_txt, callback_data="admin_database_menu")]
    ])
    await callback.message.edit_text(txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "conf_clear_all")
async def conf_clear_all(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await db.execute("DELETE FROM history")
    await db.execute("DELETE FROM models")
    await db.execute("DELETE FROM routers")
    await db.execute("DELETE FROM settings")
    await db.execute("DELETE FROM users WHERE user_id != ?", (ADMIN_ID,))
    txt = await get_text(ADMIN_ID, "clear_all_done")
    await callback.answer(txt, show_alert=True)
    await admin_database_menu(callback)
@router.callback_query(lambda c: c.data == "admin_routers")
async def admin_routers(callback: CallbackQuery, state: FSMContext = None):
    if state: await state.clear()
    user_id = callback.from_user.id
    if user_id != ADMIN_ID: return
    routers = await db.fetchall("SELECT id, domain FROM routers")
    if not routers:
        txt = await get_text(user_id, "no_routers")
        await callback.answer(txt, show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for rid, rdom in routers:
        builder.button(text=rdom, callback_data=f"router_{rid}")
    back_text = await get_text(user_id, "btn_back")
    builder.button(text=back_text, callback_data="admin_back")
    builder.adjust(1)
    title = await get_text(user_id, "title_routers")
    await callback.message.edit_text(title, reply_markup=builder.as_markup())

@router.callback_query(lambda c: c.data.startswith("router_"))
async def admin_router_details(callback: CallbackQuery, state: FSMContext = None):
    if state: await state.clear()
    user_id = callback.from_user.id
    if user_id != ADMIN_ID: return
    rid = int(callback.data.split("_")[1])
    r_row = await db.fetchone("SELECT domain, base_url, api_key FROM routers WHERE id = ?", (rid,))
    if not r_row: return
    domain, base_url, api_key = r_row
    models = await db.fetchall("SELECT id, model_name FROM models WHERE router_id = ?", (rid,))
    mods_text = ""
    if models:
        for m in models:
            emoji = get_model_emoji(m[1], m[0])
            mods_text += f"• `{m[1]}` {emoji}\n"
    else:
        mods_text = "None\n"
    txt = await get_text(user_id, "router_details")
    txt = txt.format(domain, base_url, api_key, mods_text)
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_add_mod"), callback_data=f"addmod_{rid}")
    builder.button(text=await get_text(user_id, "btn_del_mod"), callback_data=f"delmod_{rid}")
    builder.button(text=await get_text(user_id, "btn_del_router"), callback_data=f"delrouter_{rid}")
    builder.button(text=await get_text(user_id, "btn_back"), callback_data="admin_routers")
    builder.adjust(2, 1, 1)
    await callback.message.edit_text(txt, reply_markup=builder.as_markup(), parse_mode=ParseMode.MARKDOWN)

@router.callback_query(lambda c: c.data.startswith("delrouter_"))
async def admin_del_router(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    rid = int(callback.data.split("_")[1])
    txt = await get_text(ADMIN_ID, "del_confirm_msg")
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(ADMIN_ID, "btn_yes"), callback_data=f"confdelrouter_{rid}")
    builder.button(text=await get_text(ADMIN_ID, "btn_no"), callback_data=f"router_{rid}")
    builder.adjust(2)
    await callback.message.edit_text(txt, reply_markup=builder.as_markup())

@router.callback_query(lambda c: c.data.startswith("confdelrouter_"))
async def admin_conf_del_router(callback: CallbackQuery, state: FSMContext = None):
    if callback.from_user.id != ADMIN_ID: return
    rid = int(callback.data.split("_")[1])
    await db.execute("DELETE FROM models WHERE router_id = ?", (rid,))
    await db.execute("DELETE FROM routers WHERE id = ?", (rid,))
    await callback.answer(await get_text(ADMIN_ID, "del_success"), show_alert=True)
    await admin_routers(callback, state)
@router.callback_query(lambda c: c.data == "admin_add_router")
async def admin_add_router(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    txt = await get_text(ADMIN_ID, "send_url")
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = cancel_admin_keyboard(ADMIN_ID, back_txt)
    await callback.message.edit_text(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_add_router_url)

@router.message(BotStates.admin_add_router_url)
async def admin_add_router_url_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    url = message.text.strip()
    if not url.startswith("http"):
        txt = await get_text(ADMIN_ID, "invalid_url")
        await message.answer(txt)
        return
    parsed = urlparse(url)
    domain = parsed.netloc
    await state.update_data(router_url=url, router_domain=domain)
    
    txt = await get_text(ADMIN_ID, "url_detected")
    txt = txt.format(domain)
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = cancel_admin_keyboard(ADMIN_ID, back_txt)
    await message.answer(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_add_router_key)

@router.message(BotStates.admin_add_router_key)
async def admin_add_router_key_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    key = message.text.strip()
    await state.update_data(router_key=key)
    txt = await get_text(ADMIN_ID, "send_model")
    back_txt = await get_text(ADMIN_ID, "btn_back")
    kb = cancel_admin_keyboard(ADMIN_ID, back_txt)
    await message.answer(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_add_router_model)

@router.message(BotStates.admin_add_router_model)
async def admin_add_router_model_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    model_name = message.text.strip()
    data = await state.get_data()
    url = data.get("router_url")
    domain = data.get("router_domain")
    key = data.get("router_key")
    
    # Check if router exists or create it
    rid = data.get("router_id")
    if not rid:
        await db.execute("INSERT INTO routers (domain, base_url, api_key) VALUES (?, ?, ?)", (domain, url, key))
        # Get the new router id
        r_row = await db.fetchone("SELECT id FROM routers WHERE domain = ? AND base_url = ? AND api_key = ? ORDER BY id DESC LIMIT 1", (domain, url, key))
        if r_row:
            rid = r_row[0]
            await state.update_data(router_id=rid)
    
    if rid:
        await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (rid, model_name))
        
    txt = await get_text(ADMIN_ID, "router_added_continue")
    finish_txt = await get_text(ADMIN_ID, "finish")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=finish_txt, callback_data="admin_add_router_finish")]
    ])
    # The fix: Send a NEW message instead of editing, keeping the state active for unlimited adds
    await message.answer(txt, reply_markup=kb)

@router.callback_query(lambda c: c.data == "admin_add_router_finish")
async def admin_add_router_finish(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await state.clear()
    txt = await get_text(ADMIN_ID, "add_router_done")
    await callback.answer(txt, show_alert=True)
    await admin_routers(callback)

async def send_to_openai(messages, base_url, api_key, model_name):
    # Prepare payload for standard OpenAI completion endpoint
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": True
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    url = base_url
    if not url.endswith("/"):
        url += "/"
    if not url.endswith("chat/completions"):
        url += "chat/completions"
        
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                yield f"Error: HTTP {response.status}\n{text}"
                return
            
            async for line in response.content:
                line = line.decode('utf-8').strip()
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        if "choices" in data and len(data["choices"]) > 0:
                            delta = data["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                    except:
                        pass

@router.message(F.text)
async def handle_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    current_state = await state.get_state()
    if current_state:
        # Avoid processing when in other states
        return

    # Normal chat processing
    auth_ok, reason = await is_user_authorized_for_chat(user_id)
    if not auth_ok:
        if isinstance(reason, tuple):
            limit, _ = reason
            txt = await get_text(user_id, "limit_blocked")
            txt = txt.format(limit=limit)
            await message.answer(txt)
        else:
            txt = await get_text(user_id, "locked")
            await message.answer(txt)
        await state.set_state(BotStates.waiting_for_password)
        return

    joined, channels = await check_channel_join(user_id)
    if not joined:
        txt = await get_text(user_id, "must_join")
        channel_list = "\n".join([f"• {ch}" for ch in channels])
        txt = txt.format(channels=channel_list)
        kb_buttons = []
        for ch in channels:
            kb_buttons.append([InlineKeyboardButton(text=f"🔗 {ch}", url=f"https://t.me/{ch.replace('@', '')}")])
        kb_buttons.append([InlineKeyboardButton(text=await get_text(user_id, "btn_check_join"), callback_data="check_join_channel")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        await message.answer(txt, reply_markup=kb)
        return

    if not chat_mode.get(user_id, False):
        await show_user_panel(message, user_id)
        return

    row = await db.fetchone("SELECT current_model_id FROM users WHERE user_id = ?", (user_id,))
    if not row or not row[0]:
        await show_user_panel(message, user_id)
        return
        
    m_id = row[0]
    m_row = await db.fetchone("""
        SELECT m.model_name, r.base_url, r.api_key
        FROM models m
        JOIN routers r ON m.router_id = r.id
        WHERE m.id = ?
    """, (m_id,))
    
    if not m_row:
        err = await get_text(user_id, "invalid_model")
        await message.answer(err)
        return
        
    model_name, base_url, api_key = m_row
    
    # Fetch history
    history = await db.fetchall("SELECT role, content FROM history WHERE user_id = ? ORDER BY id ASC LIMIT 50", (user_id,))
    messages = [{"role": role, "content": content} for role, content in history]
    messages.append({"role": "user", "content": message.text})
    
    await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, 'user', ?)", (user_id, message.text))
    
    temp_msg = await message.answer("⏳ ...")
    
    full_response = ""
    last_edit_time = time.time()
    
    try:
        async for chunk in send_to_openai(messages, base_url, api_key, model_name):
            full_response += chunk
            current_time = time.time()
            if current_time - last_edit_time > 1.5 and full_response.strip():
                try:
                    await temp_msg.edit_text(full_response + " ⏳")
                    last_edit_time = current_time
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                except Exception:
                    pass
        
        if full_response.strip():
            try:
                await temp_msg.edit_text(full_response, parse_mode=ParseMode.MARKDOWN)
            except:
                await temp_msg.edit_text(full_response)
            
            await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, 'assistant', ?)", (user_id, full_response))
        else:
            await temp_msg.edit_text("❌ No response from the model.")
            
    except Exception as e:
        await temp_msg.edit_text(f"❌ Error: {str(e)}")

@router.message(BotStates.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    user_id = message.from_user.id
    pwd_row = await db.fetchone("SELECT value FROM settings WHERE key = 'global_password'")
    global_pwd = pwd_row[0] if pwd_row else None
    
    if global_pwd and message.text.strip() == global_pwd:
        await db.execute("UPDATE users SET is_auth = 1 WHERE user_id = ?", (user_id,))
        await state.clear()
        txt = await get_text(user_id, "pwd_ok")
        await message.answer(txt)
    else:
        txt = await get_text(user_id, "pwd_prompt_wrong")
        await message.answer(txt)

@router.message()
async def process_unknown(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        if message.text and message.text.startswith("/"):
            err = await get_text(user_id, "unknown_command")
            await message.answer(err)
            fwd = await get_text(ADMIN_ID, "forward_to_admin")
            fwd = fwd.format(username=message.from_user.username or message.from_user.first_name, user_id=user_id, text=message.text)
            try:
                await bot.send_message(ADMIN_ID, fwd)
            except:
                pass

async def main():
    await init_db()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
