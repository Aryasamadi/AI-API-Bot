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
shared_http_session: aiohttp.ClientSession = None

class DatabaseManager:
    def __init__(self):
        self.db_path = DB_PATH
        self.provider = DB_PROVIDER
        self._local_conn = None
        self.user_langs = {}

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

    async def get_conn(self):
        if not self._local_conn:
            self._local_conn = await aiosqlite.connect(self.db_path)
        return self._local_conn

    async def _safe_local_execute(self, action, query, params):
        for attempt in range(3):
            try:
                conn = await self.get_conn()
                if action == "execute":
                    cursor = await conn.execute(query, params)
                    await conn.commit()
                    return {"lastrowid": cursor.lastrowid, "rowcount": cursor.rowcount}
                elif action == "fetchall":
                    async with conn.execute(query, params) as cursor:
                        return await cursor.fetchall()
                elif action == "fetchone":
                    async with conn.execute(query, params) as cursor:
                        return await cursor.fetchone()
            except Exception as e:
                logging.warning(f"SQLite error (attempt {attempt+1}/3): {e}")
                if self._local_conn:
                    try:
                        await self._local_conn.close()
                    except:
                        pass
                    self._local_conn = None
                if attempt == 2:
                    logging.error(f"SQLite fatal error on {action}: {query} | {e}")
                    if action == "execute":
                        return {"lastrowid": None, "rowcount": 0}
                    elif action == "fetchall":
                        return []
                    elif action == "fetchone":
                        return None

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
            async with shared_http_session.post(url, headers=headers, json=payload, timeout=10) as resp:
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
            return await self._safe_local_execute("execute", query, params)

    async def fetchall(self, query, params=()):
        if self.use_cloud:
            res = await self._cloud_request(query, params)
            if res and "results" in res:
                return [tuple(row.values()) for row in res["results"]]
            return []
        else:
            return await self._safe_local_execute("fetchall", query, params)

    async def fetchone(self, query, params=()):
        if self.use_cloud:
            res = await self._cloud_request(query, params)
            if res and "results" in res and len(res["results"]) > 0:
                return tuple(res["results"][0].values())
            return None
        else:
            return await self._safe_local_execute("fetchone", query, params)

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
    "de": {
        "name": "🇩🇪 Deutsch",
        "welcome_new": "Bitte wählen Sie Ihre Sprache:",
        "welcome_back": "Willkommen zurück, {name}!",
        "welcome_first": "👋 Willkommen! Verwenden Sie /help, um verfügbare Befehle zu sehen.",
        "locked": "⛔ Unbefugt. Bitte geben Sie das Passwort ein:",
        "pwd_ok": "✅ Passwort akzeptiert! Weiterchatten...",
        "pwd_err": "⛔ Bitte geben Sie das richtige Passwort ein:",
        "pwd_none": "🔓 Passwortanforderung entfernt. Bot ist öffentlich.",
        "pwd_set": "✅ Neues Passwort gesetzt: `{}`",
        "admin_only": "❌ Nur für Administratoren.",
        "type_here": "Schreiben Sie Ihre Nachricht...",
        "select_model": "Wählen Sie ein KI-Modell, um einen NEUEN Chat zu starten:",
        "no_models_admin": "⚠️ Keine Modelle verfügbar.",
        "no_models_user": "⚠️ Keine Modelle verfügbar.",
        "chat_started": "✅ Verbunden mit {}.\nSenden Sie Ihre Nachricht:",
        "invalid_url": "❌ Ungültiges URL-Format. Bitte senden Sie eine gültige Basis-URL (http/https):",
        "admin_menu": "⚙️ Erweitertes Admin-Panel – verwenden Sie das Menü unten:",
        "title_routers": "🗂 Liste aller verfügbaren API-Router:",
        "title_settings": "⚙️ Bot-Einstellungen & Datenbankverwaltung:",
        "btn_routers": "🗂 API-Liste",
        "btn_add_router": "➕ Router Hinzufügen",
        "btn_settings": "⚙️ Einstellungen",
        "btn_database": "🗄️ Datenbank",
        "btn_stats": "📊 Statistiken & Status",
        "btn_set_pwd": "🔐 Passwort Setzen",
        "btn_set_channel": "📢 Kanal Erzwingen",
        "btn_broadcast": "📢 Rundsendung",
        "btn_back": "🔙 Zurück",
        "btn_back_main": "🏠 Hauptmenü",
        "send_pwd_prompt": "Neues Passwort senden (oder 'none' für öffentlich):",
        "send_limit_prompt": "Geben Sie nun die Anzahl der erlaubten Nachrichten für unbefugte Benutzer ein (z. B. 5):",
        "send_broadcast": "Senden Sie Ihre Rundsendungsnachricht:",
        "broadcast_done": "✅ An {} Benutzer gesendet.",
        "send_url": "Senden Sie die Basis-URL (z. B. https://api.openai.com/v1):",
        "url_detected": "Domain: {}\nSenden Sie nun den API-Schlüssel (Token):",
        "send_model": "API-Schlüssel gespeichert.\nSenden Sie nun den genauen Modellnamen:",
        "send_model_for_router": "Senden Sie den genauen Modellnamen, um ihn diesem Router hinzuzufügen:",
        "router_added": "✅ Router und Modell erfolgreich hinzugefügt!",
        "router_details": "📌 **Router:** {}\n\n🌐 Basis-URL: `{}`\n\n🔑 Token: `{}`\n\n📦 **Modelle (zum Kopieren antippen):**\n{}",
        "btn_add_mod": "➕ Modell Hinzufügen",
        "btn_del_mod": "🗑 Modell Löschen",
        "btn_del_router": "🗑 Router Löschen",
        "del_confirm_msg": "⚠️ Sind Sie sicher, dass Sie diesen Router und seine Modelle löschen möchten?",
        "btn_yes": "✅ Ja",
        "btn_no": "❌ Nein",
        "del_success": "✅ Gelöscht.",
        "pls_select_model": "Bitte wählen Sie ein gültiges Modell aus der Liste aus.",
        "invalid_command": "❌ Bitte verwenden Sie gültige logische Befehle.",
        "send_channel_prompt": "Kanal-Benutzernamen senden (z. B. @AI_Channel) oder 'none' (für mehrere mit Komma trennen):",
        "channel_set": "✅ Kanal (Kanäle) zum Beitreten festgelegt auf: `{}`",
        "channel_none": "🔓 Kanalbeitritt erzwingen deaktiviert.",
        "must_join": "⛔ Sie müssen unserem/n Kanal/Kanälen beitreten, um den Bot zu nutzen:\n{channels}",
        "btn_join_channel": "🔗 Kanal Beitreten",
        "btn_check_join": "🔄 Mitgliedschaft Prüfen",
        "join_ok": "✅ Mitgliedschaft bestätigt! Sie können den Bot jetzt nutzen.",
        "join_fail": "❌ Sie sind noch nicht allen erforderlichen Kanälen beigetreten!",
        "send_del_model": "Senden Sie den genauen Namen des Modells, das Sie löschen möchten:",
        "model_deleted": "✅ Modell erfolgreich gelöscht.",
        "model_not_found": "❌ Modell nicht gefunden.",
        "btn_user_mode": "👤 Benutzermodus",
        "btn_clear_cache": "🧹 Cache Leeren (nur Verlauf)",
        "btn_clear_all": "🗑️ Komplette Datenbank Löschen",
        "clear_cache_confirm": "🧹 Dies löscht den gesamten Chatverlauf (Nachrichten) aller Benutzer.\n❓ Sind Sie sicher?",
        "clear_cache_done": "✅ Chatverlauf gelöscht.",
        "clear_all_confirm": "🗑️ Dies löscht ALLE Daten:\n- Benutzer\n- Einstellungen\n- Router\n- Modelle\n- Chatverlauf\n\n❓ Sind Sie sicher?",
        "clear_all_done": "✅ Alle Daten wurden gelöscht.",
        "clear_cancelled": "❌ Vorgang abgebrochen.",
        "btn_admin_panel": "⚙️ Admin-Panel",
        "no_cloud_db": "⚠️ Keine externe Cloud-Datenbank konfiguriert. Lokales SQLite wird verwendet.",
        "no_routers": "⚠️ Es wurden noch keine API-Router hinzugefügt.",
        "help_user": "📖 Verfügbare Befehle\n\n🚀 /start • start ➜ Start\n🌐 /lang • lang ➜ Sprache\n🤖 /model • model ➜ Chat leeren & neues Modell wählen\n📞 /man • man ➜ Admin kontaktieren\n❓ /help • help ➜ Hilfe\n\n✨ Wählen und starten 🚀",
        "help_admin": "🌐 /lang • lang ➜ Sprache\n👤 /user • user ➜ Benutzermodus\n🤖 /model • model ➜ Cache & Modelle leeren\n📞 /man • man ➜ Admin kontaktieren\n❓ /help • help ➜ Hilfe\n✨ Wählen und starten 🚀",
        "stats_text": "📊 **Bot-Statistiken**\n\n👤 Benutzer: `{users}`\n📢 Pflichtkanal: `{channel}`\n🤖 Modelle: `{models}`\n🗂️ Router: `{routers}`\n🔑 Tokens: `{tokens}`\n🔐 Passwort: `{pwd_status}`",
        "btn_view_data": "📋 Alle Daten Anzeigen",
        "all_data_title": "📋 **Alle Router, Modelle und Tokens**\n\n",
        "data_router_header": "\n📍 **Router #{id}** – `{domain}`\n🌐 Basis-URL: `{base_url}`\n🔑 Token: `{api_key}`\n📦 Modelle:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (keine Modelle)\n",
        "unknown_command": "❌ Unbekannter Befehl",
        "blocked_unauthorized": "⛔ Sie haben Ihre {limit} kostenlosen Anfragen verbraucht. Bitte geben Sie das Passwort ein:",
        "forward_to_admin": "Unbekannter Befehl von @{username} (ID: {user_id}): {text}",
        "model_added_continue": "✅ Modell hinzugefügt. Geben Sie den nächsten Modellnamen ein oder drücken Sie 'Fertig'.",
        "finish": "✅ Fertig",
        "router_added_continue": "✅ Modell hinzugefügt. Geben Sie den nächsten Modellnamen ein oder drücken Sie 'Fertig'.",
        "add_router_done": "✅ Router und Modelle erfolgreich registriert.",
        "loading_data": "⏳ Daten werden geladen... {progress}%",
        "data_loaded": "✅ Daten erfolgreich geladen.",
        "error_occurred": "❌ Beim Laden der Daten ist ein Fehler aufgetreten. Bitte versuchen Sie es später noch einmal.",
        "error_detail": "❌ Fehlerdetails: {error}",
        "limit_blocked": "⛔ Sie haben Ihre {limit} kostenlosen Anfragen verbraucht. Bitte geben Sie das Passwort ein:",
        "contact_intro": "Bitte schreiben Sie Ihr Anliegen als vollständige Nachricht an den Administrator:",
        "contact_confirm": "✅ Ihre Nachricht wurde gesendet. Wir werden so schnell wie möglich antworten. Um erneut Kontakt aufzunehmen, senden Sie /man.",
        "contact_end_auto": "✅ Gesendet. Wir werden so schnell wie möglich antworten.\nUm erneut Kontakt aufzunehmen, senden Sie /man.",
        "contact_forward": "Nachricht von Benutzer {name} (ID: {user_id}):\n{text}",
        "contact_button": "📞 Admin Kontaktieren",
        "contact_admin_reply": "📩 Antwort vom Admin:\n{text}",
        "admin_reply_sent": "✅ Antwort an Benutzer gesendet.",
        "pwd_prompt_wrong": "⛔ Bitte geben Sie das richtige Passwort ein:",
        "invalid_model": "❌ Dieses Modell ist nicht mehr verfügbar. Bitte wählen Sie ein anderes."
},
    "ar": {
        "name": "🇸🇦 العربية",
        "welcome_new": "يرجى اختيار لغتك:",
        "welcome_back": "مرحباً بعودتك، {name}!",
        "welcome_first": "👋 مرحباً! استخدم /help لرؤية الأوامر المتاحة.",
        "locked": "⛔ غير مصرح لك. الرجاء إدخال كلمة المرور:",
        "pwd_ok": "✅ تم قبول كلمة المرور! تابع الدردشة...",
        "pwd_err": "⛔ الرجاء إدخال كلمة المرور الصحيحة:",
        "pwd_none": "🔓 تمت إزالة طلب كلمة المرور. البوت أصبح متاحاً للعامة.",
        "pwd_set": "✅ تم تعيين كلمة مرور جديدة: `{}`",
        "admin_only": "❌ للمشرفين فقط.",
        "type_here": "اكتب رسالتك...",
        "select_model": "اختر نموذج ذكاء اصطناعي لبدء دردشة جديدة:",
        "no_models_admin": "⚠️ لا توجد نماذج متاحة.",
        "no_models_user": "⚠️ لا توجد نماذج متاحة.",
        "chat_started": "✅ متصل بـ {}.\nأرسل رسالتك:",
        "invalid_url": "❌ صيغة الرابط غير صحيحة. يرجى إرسال رابط صحيح (http/https):",
        "admin_menu": "⚙️ لوحة تحكم المشرف المتقدمة – استخدم القائمة أدناه:",
        "title_routers": "🗂 قائمة بجميع موجهات API المتاحة:",
        "title_settings": "⚙️ إعدادات البوت وإدارة قاعدة البيانات :",
        "btn_routers": "🗂 قائمة API",
        "btn_add_router": "➕ إضافة موجه",
        "btn_settings": "⚙️ الإعدادات",
        "btn_database": "🗄️ قاعدة البيانات",
        "btn_stats": "📊 الإحصائيات والحالة",
        "btn_set_pwd": "🔐 تعيين كلمة المرور",
        "btn_set_channel": "📢 فرض الانضمام",
        "btn_broadcast": "📢 إذاعة",
        "btn_back": "🔙 رجوع",
        "btn_back_main": "🏠 القائمة الرئيسية",
        "send_pwd_prompt": "أرسل كلمة المرور الجديدة (أو 'none' لجعل البوت عاماً):",
        "send_limit_prompt": "الآن أدخل عدد الرسائل المسموح بها للمستخدمين غير المصرح لهم (مثال: 5):",
        "send_broadcast": "أرسل رسالة الإذاعة:",
        "broadcast_done": "✅ تم الإرسال إلى {} مستخدم.",
        "send_url": "أرسل الرابط الأساسي Base URL (مثال: https://api.openai.com/v1):",
        "url_detected": "النطاق: {}\nالآن أرسل مفتاح API (التوكن):",
        "send_model": "تم حفظ مفتاح API.\nالآن أرسل اسم النموذج بالضبط:",
        "send_model_for_router": "أرسل اسم النموذج بالضبط لإضافته إلى هذا الموجه:",
        "router_added": "✅ تم إضافة الموجه والنموذج بنجاح!",
        "router_details": "📌 **الموجه:** {}\n\n🌐 الرابط: `{}`\n\n🔑 التوكن: `{}`\n\n📦 **النماذج (انقر للنسخ):**\n{}",
        "btn_add_mod": "➕ إضافة نموذج",
        "btn_del_mod": "🗑 حذف نموذج",
        "btn_del_router": "🗑 حذف الموجه",
        "del_confirm_msg": "⚠️ هل أنت متأكد أنك تريد حذف هذا الموجه ونماذجه؟",
        "btn_yes": "✅ نعم",
        "btn_no": "❌ لا",
        "del_success": "✅ تم الحذف.",
        "pls_select_model": "يرجى اختيار نموذج صالح من القائمة.",
        "invalid_command": "❌ يرجى استخدام أوامر منطقية صالحة.",
        "send_channel_prompt": "أرسل معرف القناة (مثال: @AI_Channel) أو 'none' (لعدة قنوات، افصل بينها بفاصلة):",
        "channel_set": "✅ تم تعيين القناة/القنوات المطلوبة إلى: `{}`",
        "channel_none": "🔓 تم تعطيل فرض الانضمام للقناة.",
        "must_join": "⛔ يجب عليك الانضمام إلى قناتنا/قنواتنا لاستخدام البوت:\n{channels}",
        "btn_join_channel": "🔗 الانضمام للقناة",
        "btn_check_join": "🔄 التحقق من العضوية",
        "join_ok": "✅ تم التحقق من العضوية! يمكنك الآن استخدام البوت.",
        "join_fail": "❌ لم تنضم إلى جميع القنوات المطلوبة بعد!",
        "send_del_model": "أرسل الاسم الدقيق للنموذج الذي تريد حذفه:",
        "model_deleted": "✅ تم حذف النموذج بنجاح.",
        "model_not_found": "❌ لم يتم العثور على النموذج.",
        "btn_user_mode": "👤 وضع المستخدم",
        "btn_clear_cache": "🧹 مسح ذاكرة التخزين (السجل فقط)",
        "btn_clear_all": "🗑️ مسح قاعدة البيانات بالكامل",
        "clear_cache_confirm": "🧹 سيؤدي هذا إلى حذف سجل الدردشة (الرسائل) لجميع المستخدمين.\n❓ هل أنت متأكد؟",
        "clear_cache_done": "✅ تم مسح سجل الدردشة.",
        "clear_all_confirm": "🗑️ سيؤدي هذا إلى حذف كافة البيانات:\n- المستخدمون\n- الإعدادات\n- الموجهات\n- النماذج\n- سجل الدردشة\n\n❓ هل أنت متأكد؟",
        "clear_all_done": "✅ تم مسح كافة البيانات.",
        "clear_cancelled": "❌ تم إلغاء العملية.",
        "btn_admin_panel": "⚙️ لوحة المشرف",
        "no_cloud_db": "⚠️ لم يتم تكوين قاعدة بيانات سحابية خارجية. يتم استخدام SQLite المحلي.",
        "no_routers": "⚠️ لم يتم إضافة موجهات API بعد.",
        "help_user": "📖 الأوامر المتاحة\n\n🚀 /start • start ➜ البداية\n🌐 /lang • lang ➜ اللغة\n🤖 /model • model ➜ مسح الدردشة واختيار نموذج\n📞 /man • man ➜ الاتصال بالمشرف\n❓ /help • help ➜ مساعدة\n\n✨ اختر وابدأ 🚀",
        "help_admin": "🌐 /lang • lang ➜ اللغة\n👤 /user • user ➜ وضع المستخدم\n🤖 /model • model ➜ مسح السجل والنماذج\n📞 /man • man ➜ الاتصال بالمشرف\n❓ /help • help ➜ مساعدة\n✨ اختر وابدأ 🚀",
        "stats_text": "📊 **إحصائيات البوت**\n\n👤 المستخدمون: `{users}`\n📢 القناة المفروضة: `{channel}`\n🤖 النماذج: `{models}`\n🗂️ الموجهات: `{routers}`\n🔑 التوكنز: `{tokens}`\n🔐 كلمة المرور: `{pwd_status}`",
        "btn_view_data": "📋 عرض كافة البيانات",
        "all_data_title": "📋 **كافة الموجهات، النماذج، والتوكنز**\n\n",
        "data_router_header": "\n📍 **الموجه #{id}** – `{domain}`\n🌐 الرابط: `{base_url}`\n🔑 التوكن: `{api_key}`\n📦 النماذج:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (لا توجد نماذج)\n",
        "unknown_command": "❌ أمر غير معروف",
        "blocked_unauthorized": "⛔ لقد استنفدت طلباتك المجانية الـ {limit}. يرجى إدخال كلمة المرور:",
        "forward_to_admin": "أمر غير معروف من @{username} (الآي دي: {user_id}): {text}",
        "model_added_continue": "✅ تم إضافة النموذج. أدخل اسم النموذج التالي، أو اضغط على 'إنهاء'.",
        "finish": "✅ إنهاء",
        "router_added_continue": "✅ تم إضافة النموذج. أدخل اسم النموذج التالي، أو اضغط على 'إنهاء'.",
        "add_router_done": "✅ تم تسجيل الموجه والنماذج بنجاح.",
        "loading_data": "⏳ جاري تحميل البيانات... {progress}%",
        "data_loaded": "✅ تم تحميل البيانات بنجاح.",
        "error_occurred": "❌ حدث خطأ أثناء تحميل البيانات. يرجى المحاولة مرة أخرى لاحقاً.",
        "error_detail": "❌ تفاصيل الخطأ: {error}",
        "limit_blocked": "⛔ لقد استنفدت طلباتك المجانية الـ {limit}. يرجى إدخال كلمة المرور:",
        "contact_intro": "يرجى كتابة طلبك كرسالة كاملة ليتم إرسالها إلى المشرف:",
        "contact_confirm": "✅ تم إرسال رسالتك. سنرد في أقرب وقت ممكن. للمراسلة مرة أخرى، أرسل /man.",
        "contact_end_auto": "✅ تم الإرسال. سنرد في أقرب وقت ممكن.\nللمراسلة مرة أخرى، أرسل /man.",
        "contact_forward": "رسالة من المستخدم {name} (الآي دي: {user_id}):\n{text}",
        "contact_button": "📞 الاتصال بالمشرف",
        "contact_admin_reply": "📩 رد من المشرف:\n{text}",
        "admin_reply_sent": "✅ تم إرسال الرد إلى المستخدم.",
        "pwd_prompt_wrong": "⛔ الرجاء إدخال كلمة المرور الصحيحة:",
        "invalid_model": "❌ هذا النموذج لم يعد متاحاً. يرجى اختيار نموذج آخر."
},
    "zh": {
        "name": "🇨🇳 中文",
        "welcome_new": "请选择您的语言：",
        "welcome_back": "欢迎回来，{name}！",
        "welcome_first": "👋 欢迎！使用 /help 查看可用命令。",
        "locked": "⛔ 未经授权。请输入密码：",
        "pwd_ok": "✅ 密码验证通过！继续聊天...",
        "pwd_err": "⛔ 请输入正确的密码：",
        "pwd_none": "🔓 密码要求已移除。机器人现已公开。",
        "pwd_set": "✅ 新密码已设置：`{}`",
        "admin_only": "❌ 仅限管理员。",
        "type_here": "输入您的消息...",
        "select_model": "选择一个AI模型以开始新聊天：",
        "no_models_admin": "⚠️ 没有可用的模型。",
        "no_models_user": "⚠️ 没有可用的模型。",
        "chat_started": "✅ 已连接到 {}。\n发送您的消息：",
        "invalid_url": "❌ URL格式无效。请发送有效的 Base URL (http/https)：",
        "admin_menu": "⚙️ 高级管理面板 – 请使用以下菜单：",
        "title_routers": "🗂 所有可用的 API 路由列表：",
        "title_settings": "⚙️ 机器人设置与数据库管理：",
        "btn_routers": "🗂 API 列表",
        "btn_add_router": "➕ 添加路由",
        "btn_settings": "⚙️ 设置",
        "btn_database": "🗄️ 数据库",
        "btn_stats": "📊 统计与状态",
        "btn_set_pwd": "🔐 设置密码",
        "btn_set_channel": "📢 强制加入频道",
        "btn_broadcast": "📢 广播",
        "btn_back": "🔙 返回",
        "btn_back_main": "🏠 主菜单",
        "send_pwd_prompt": "发送新密码（或发送 'none' 以公开）：",
        "send_limit_prompt": "现在输入允许未授权用户发送的消息数量（例如，5）：",
        "send_broadcast": "发送您的广播消息：",
        "broadcast_done": "✅ 已发送给 {} 位用户。",
        "send_url": "发送 Base URL (例如，https://api.openai.com/v1)：",
        "url_detected": "域名：{}\n现在发送 API Key (Token)：",
        "send_model": "API Key 已保存。\n现在发送准确的模型名称：",
        "send_model_for_router": "发送准确的模型名称以添加到此路由：",
        "router_added": "✅ 路由和模型已成功添加！",
        "router_details": "📌 **路由：** {}\n\n🌐 Base URL：`{}`\n\n🔑 Token：`{}`\n\n📦 **模型（点击复制）：**\n{}",
        "btn_add_mod": "➕ 添加模型",
        "btn_del_mod": "🗑 删除模型",
        "btn_del_router": "🗑 删除路由",
        "del_confirm_msg": "⚠️ 您确定要删除此路由及其模型吗？",
        "btn_yes": "✅ 是",
        "btn_no": "❌ 否",
        "del_success": "✅ 已删除。",
        "pls_select_model": "请从列表中选择一个有效的模型。",
        "invalid_command": "❌ 请使用有效的逻辑命令。",
        "send_channel_prompt": "发送频道用户名（例如，@AI_Channel）或 'none'（多个频道请用逗号分隔）：",
        "channel_set": "✅ 强制加入的频道已设置为：`{}`",
        "channel_none": "🔓 已禁用强制加入频道。",
        "must_join": "⛔ 您必须加入我们的频道才能使用该机器人：\n{channels}",
        "btn_join_channel": "🔗 加入频道",
        "btn_check_join": "🔄 检查会员资格",
        "join_ok": "✅ 会员资格已验证！您现在可以使用该机器人了。",
        "join_fail": "❌ 您尚未加入所有必需的频道！",
        "send_del_model": "发送您想要删除的模型的准确名称：",
        "model_deleted": "✅ 模型删除成功。",
        "model_not_found": "❌ 未找到模型。",
        "btn_user_mode": "👤 用户模式",
        "btn_clear_cache": "🧹 清除缓存 (仅限历史记录)",
        "btn_clear_all": "🗑️ 完整数据库擦除",
        "clear_cache_confirm": "🧹 这将删除所有用户的聊天记录。\n❓ 您确定吗？",
        "clear_cache_done": "✅ 聊天记录已清除。",
        "clear_all_confirm": "🗑️ 这将删除所有数据：\n- 用户\n- 设置\n- 路由\n- 模型\n- 聊天记录\n\n❓ 您确定吗？",
        "clear_all_done": "✅ 所有数据已被擦除。",
        "clear_cancelled": "❌ 操作已取消。",
        "btn_admin_panel": "⚙️ 管理面板",
        "no_cloud_db": "⚠️ 未配置外部云数据库。使用本地 SQLite。",
        "no_routers": "⚠️ 尚未添加任何 API 路由。",
        "help_user": "📖 可用命令\n\n🚀 /start • start ➜ 开始\n🌐 /lang • lang ➜ 语言\n🤖 /model • model ➜ 清除聊天并选择新模型\n📞 /man • man ➜ 联系管理员\n❓ /help • help ➜ 帮助\n\n✨ 选择并开始 🚀",
        "help_admin": "🌐 /lang • lang ➜ 语言\n👤 /user • user ➜ 用户模式\n🤖 /model • model ➜ 清除缓存与模型\n📞 /man • man ➜ 联系管理员\n❓ /help • help ➜ 帮助\n✨ 选择并开始 🚀",
        "stats_text": "📊 **机器人统计信息**\n\n👤 用户：`{users}`\n📢 强制加入频道：`{channel}`\n🤖 模型：`{models}`\n🗂️ 路由：`{routers}`\n🔑 Tokens：`{tokens}`\n🔐 密码：`{pwd_status}`",
        "btn_view_data": "📋 查看所有数据",
        "all_data_title": "📋 **所有路由、模型和 Tokens**\n\n",
        "data_router_header": "\n📍 **路由 #{id}** – `{domain}`\n🌐 Base URL：`{base_url}`\n🔑 Token：`{api_key}`\n📦 模型：\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (无模型)\n",
        "unknown_command": "❌ 未知命令",
        "blocked_unauthorized": "⛔ 您已用完 {limit} 次免费请求。请输入密码：",
        "forward_to_admin": "来自 @{username} (ID: {user_id}) 的未知命令：{text}",
        "model_added_continue": "✅ 模型已添加。输入下一个模型名称，或按“完成”按钮。",
        "finish": "✅ 完成",
        "router_added_continue": "✅ 模型已添加。输入下一个模型名称，或按“完成”按钮。",
        "add_router_done": "✅ 路由和模型已成功注册。",
        "loading_data": "⏳ 正在加载数据... {progress}%",
        "data_loaded": "✅ 数据加载成功。",
        "error_occurred": "❌ 加载数据时发生错误。请稍后再试。",
        "error_detail": "❌ 错误详情：{error}",
        "limit_blocked": "⛔ 您已用完 {limit} 次免费请求。请输入密码：",
        "contact_intro": "请将您的请求作为完整消息写给管理员：",
        "contact_confirm": "✅ 您的消息已发送。我们将尽快回复。若需再次联系，请发送 /man。",
        "contact_end_auto": "✅ 已发送。我们将尽快回复。\n若需再次联系，请发送 /man。",
        "contact_forward": "来自用户 {name} (ID: {user_id}) 的消息：\n{text}",
        "contact_button": "📞 联系管理员",
        "contact_admin_reply": "📩 来自管理员的回复：\n{text}",
        "admin_reply_sent": "✅ 已回复给用户。",
        "pwd_prompt_wrong": "⛔ 请输入正确的密码：",
        "invalid_model": "❌ 此模型已不再可用。请选择其他模型。"
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
    lang = db.user_langs.get(user_id)
    if not lang:
        row = await db.fetchone("SELECT lang FROM users WHERE user_id = ?", (user_id,))
        lang = row[0] if row and row[0] in LANGS else "en"
        db.user_langs[user_id] = lang
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
    ordered_langs = ["en", "fa", "ar", "ru", "de", "zh"]
    for k in ordered_langs:
        if k in LANGS:
            builder.button(text=LANGS[k]["name"], callback_data=f"setlang_{k}")
    builder.adjust(1)
    return builder.as_markup()

async def admin_panel_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_routers"), callback_data="admin_routers")
    builder.button(text=await get_text(user_id, "btn_add_router"), callback_data="admin_add_router")
    builder.button(text=await get_text(user_id, "btn_settings"), callback_data="admin_settings_menu")
    builder.button(text=await get_text(user_id, "btn_user_mode"), callback_data="admin_switch_user")
    builder.adjust(2, 1, 1)
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

@router.message(Command("start"))
@router.message(F.text.lower().in_({"start", "/start"}))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    chat_mode[message.from_user.id] = False
    await db.execute("UPDATE users SET current_model_id = NULL WHERE user_id = ?", (message.from_user.id,))
    await db.execute("DELETE FROM history WHERE user_id = ?", (message.from_user.id,))
    user_exists = await db.fetchone("SELECT lang FROM users WHERE user_id = ?", (message.from_user.id,))
    if not user_exists:
        await db.execute("INSERT OR IGNORE INTO users (user_id, lang, msg_count) VALUES (?, ?, 0)", (message.from_user.id, "en"))
        welcome_first = await get_text(message.from_user.id, "welcome_first")
        await message.answer(welcome_first)
        await message.answer("Please select your language:", reply_markup=lang_keyboard())
    else:
        welcome_txt = await get_text(message.from_user.id, "welcome_back")
        await message.answer(welcome_txt.format(name=message.from_user.first_name))
        await show_user_panel(message, message.from_user.id)

@router.message(Command("lang"))
@router.message(F.text.lower().in_({"lang", "/lang"}))
async def cmd_lang(message: Message, state: FSMContext):
    await state.clear()
    chat_mode[message.from_user.id] = False
    await message.answer("Please select your language:", reply_markup=lang_keyboard())

@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    await db.execute("""
        INSERT INTO users (user_id, lang) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang
    """, (callback.from_user.id, lang))
    db.user_langs[callback.from_user.id] = lang
    await callback.message.delete()
    chat_mode[callback.from_user.id] = False
    await show_user_panel(callback.message, callback.from_user.id)

@router.message(Command("user"))
@router.message(F.text.lower().in_({"user", "/user"}))
async def cmd_user(message: Message, state: FSMContext):
    await state.clear()
    chat_mode[message.from_user.id] = False
    await show_user_panel(message, message.from_user.id)

@router.callback_query(F.data == "check_join_channel")
async def check_join_callback(callback: CallbackQuery):
    joined, channels = await check_channel_join(callback.from_user.id)
    if joined:
        ok_txt = await get_text(callback.from_user.id, "join_ok")
        await callback.answer(ok_txt, show_alert=True)
        await callback.message.delete()
        chat_mode[callback.from_user.id] = False
        await show_user_panel(callback.message, callback.from_user.id)
    else:
        fail_txt = await get_text(callback.from_user.id, "join_fail")
        await callback.answer(fail_txt, show_alert=True)

@router.callback_query(F.data == "go_admin_panel")
async def go_admin_panel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(await get_text(callback.from_user.id, "admin_only"), show_alert=True)
        return
    await state.clear()
    chat_mode[callback.from_user.id] = False
    admin_text = await get_text(callback.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("selmod_"))
async def select_model(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    model_id = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    row = await db.fetchone("""
        SELECT m.model_name, r.id
        FROM models m
        JOIN routers r ON m.router_id = r.id
        WHERE m.id = ? AND r.api_key IS NOT NULL AND r.api_key != ''
    """, (model_id,))
    
    if not row:
        await callback.answer(await get_text(user_id, "invalid_model"), show_alert=True)
        await show_user_panel(callback, user_id, edit=True)
        return
    
    model_name = row[0]
    await db.execute("UPDATE users SET current_model_id = ? WHERE user_id = ?", (model_id, user_id))
    await db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    chat_mode[user_id] = True
    chat_start_txt = await get_text(user_id, "chat_started")
    await callback.message.answer(chat_start_txt.format(model_name))
    await callback.answer()

@router.message(Command("model"))
@router.message(F.text.lower().in_({"model", "/model"}))
async def cmd_model_exit(message: Message, state: FSMContext):
    await state.clear()
    chat_mode[message.from_user.id] = False
    await db.execute("DELETE FROM history WHERE user_id = ?", (message.from_user.id,))
    await db.execute("UPDATE users SET current_model_id = NULL WHERE user_id = ?", (message.from_user.id,))
    await show_user_panel(message, message.from_user.id)

@router.message(Command("admin"))
@router.message(F.text.lower().in_({"admin", "/admin"}))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    chat_mode[message.from_user.id] = False
    if message.from_user.id != ADMIN_ID:
        err = await get_text(message.from_user.id, "admin_only")
        return await message.answer(err)
    admin_text = await get_text(message.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(message.from_user.id)
    await message.answer(admin_text, reply_markup=kb)

@router.message(Command("help"))
@router.message(F.text.lower().in_({"help", "/help"}))
async def cmd_help(message: Message, state: FSMContext):
    await state.clear()
    chat_mode[message.from_user.id] = False
    if message.from_user.id == ADMIN_ID:
        help_text = await get_text(message.from_user.id, "help_admin")
    else:
        help_text = await get_text(message.from_user.id, "help_user")
    await message.answer(help_text, parse_mode="Markdown")

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    chat_mode[callback.from_user.id] = False
    admin_text = await get_text(callback.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)

@router.callback_query(F.data == "admin_settings_menu")
async def admin_settings_menu(callback: CallbackQuery):
    chat_mode[callback.from_user.id] = False
    title = await get_text(callback.from_user.id, "title_settings")
    kb = await admin_settings_keyboard(callback.from_user.id)
    await callback.message.edit_text(title, reply_markup=kb)

@router.callback_query(F.data == "admin_database_menu")
async def admin_database_menu(callback: CallbackQuery):
    chat_mode[callback.from_user.id] = False
    title = "🗄️ " + await get_text(callback.from_user.id, "btn_database")
    kb = await admin_database_keyboard(callback.from_user.id)
    await callback.message.edit_text(title, reply_markup=kb)

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    chat_mode[callback.from_user.id] = False
    users, models, routers, tokens = await db.get_stats()
    pwd_row = await db.fetchone("SELECT value FROM settings WHERE key = 'global_password'")
    has_pwd = pwd_row and pwd_row[0] and pwd_row[0].lower() != 'none'
    pwd_status = "✅ Active" if has_pwd else "❌ Inactive"
    channel_row = await db.fetchone("SELECT value FROM settings WHERE key = 'force_channel'")
    channel = channel_row[0] if channel_row and channel_row[0] and channel_row[0].lower() != 'none' else "❌ Not set"
    lang = await db.fetchone("SELECT lang FROM users WHERE user_id = ?", (callback.from_user.id,))
    lang_code = lang[0] if lang and lang[0] in LANGS else "en"
    if lang_code == "fa":
        pwd_status = "✅ فعال" if has_pwd else "❌ غیرفعال"
        channel = channel if channel != "❌ Not set" else "❌ تنظیم نشده"
    elif lang_code == "ru":
        pwd_status = "✅ Активен" if has_pwd else "❌ Неактивен"
        channel = channel if channel != "❌ Not set" else "❌ Не установлен"
    elif lang_code == "ar":
        pwd_status = "✅ نشط" if has_pwd else "❌ غير نشط"
        channel = channel if channel != "❌ Not set" else "❌ لم يتم تعيينه"
    elif lang_code == "hi":
        pwd_status = "✅ सक्रिय" if has_pwd else "❌ निष्क्रिय"
        channel = channel if channel != "❌ Not set" else "❌ सेट नहीं"
    elif lang_code == "tr":
        pwd_status = "✅ Aktif" if has_pwd else "❌ Pasif"
        channel = channel if channel != "❌ Not set" else "❌ Ayarlanmamış"
    elif lang_code == "fr":
        pwd_status = "✅ Actif" if has_pwd else "❌ Inactif"
        channel = channel if channel != "❌ Not set" else "❌ Non défini"
    elif lang_code == "de":
        pwd_status = "✅ Aktiv" if has_pwd else "❌ Inaktiv"
        channel = channel if channel != "❌ Not set" else "❌ Nicht gesetzt"
    elif lang_code == "zh":
        pwd_status = "✅ 已启用" if has_pwd else "❌ 已禁用"
        channel = channel if channel != "❌ Not set" else "❌ 未设置"
    stats_text = await get_text(callback.from_user.id, "stats_text")
    stats_text = stats_text.format(
        users=users,
        channel=channel,
        models=models,
        routers=routers,
        tokens=tokens,
        pwd_status=pwd_status
    )
    btn_back = await get_text(callback.from_user.id, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_back, callback_data="admin_settings_menu")]])
    await callback.message.edit_text(stats_text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "admin_switch_user")
async def admin_switch_user(callback: CallbackQuery):
    chat_mode[callback.from_user.id] = False
    await show_user_panel(callback, callback.from_user.id, is_admin_view=True, edit=True)
    await callback.answer()

@router.callback_query(F.data.startswith("userpage_"))
async def user_page_callback(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    chat_mode[callback.from_user.id] = False
    await show_user_panel(callback, callback.from_user.id, page=page, is_admin_view=False, edit=True)
    await callback.answer()

@router.callback_query(F.data == "admin_pwd")
async def admin_pwd_start(callback: CallbackQuery, state: FSMContext):
    chat_mode[callback.from_user.id] = False
    txt = await get_text(callback.from_user.id, "send_pwd_prompt")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_set_password)

@router.message(BotStates.admin_set_password)
async def admin_pwd_save(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    new_pwd = message.text.strip()
    if new_pwd.lower() == 'none':
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_password', 'none')")
        await db.execute("UPDATE users SET is_auth = 1")
        await db.execute("DELETE FROM settings WHERE key = 'unauth_limit'")
        res_txt = await get_text(message.from_user.id, "pwd_none")
        await message.answer(res_txt)
        await state.clear()
        await cmd_admin(message, state)
        return
    await state.update_data(temp_password=new_pwd)
    limit_prompt = await get_text(message.from_user.id, "send_limit_prompt")
    btn_back = await get_text(message.from_user.id, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_back, callback_data="admin_back")]])
    await message.answer(limit_prompt, reply_markup=kb)
    await state.set_state(BotStates.admin_set_limit)

@router.message(BotStates.admin_set_limit)
async def admin_set_limit(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    limit_text = message.text.strip()
    if not limit_text.isdigit():
        await message.answer("❌ Please enter a valid number (e.g., 5).")
        return
    limit = int(limit_text)
    if limit < 0:
        await message.answer("❌ Limit cannot be negative. Please enter 0 or more.")
        return
    data = await state.get_data()
    password = data.get('temp_password')
    if not password:
        await message.answer("❌ Something went wrong. Please try again from the beginning.")
        await state.clear()
        return
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_password', ?)", (password,))
    await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('unauth_limit', ?)", (str(limit),))
    await db.execute("UPDATE users SET is_auth = 0")
    await db.execute("UPDATE users SET msg_count = 0")
    res_txt = await get_text(message.from_user.id, "pwd_set")
    res_txt = res_txt.format(password)
    await message.answer(res_txt)
    await state.clear()
    await cmd_admin(message, state)

@router.callback_query(F.data == "admin_channel")
async def admin_channel_start(callback: CallbackQuery, state: FSMContext):
    chat_mode[callback.from_user.id] = False
    txt = await get_text(callback.from_user.id, "send_channel_prompt")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_set_channel)

@router.message(BotStates.admin_set_channel)
async def admin_channel_save(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    new_channel = message.text.strip()
    if new_channel.lower() == 'none':
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_channel', 'none')")
        res_txt = await get_text(message.from_user.id, "channel_none")
    else:
        channels = [ch.strip() for ch in new_channel.split(',') if ch.strip()]
        formatted = ','.join([ch if ch.startswith('@') else '@'+ch for ch in channels])
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_channel', ?)", (formatted,))
        res_txt = await get_text(message.from_user.id, "channel_set")
        res_txt = res_txt.format(formatted)
    await message.answer(res_txt)
    await state.clear()
    await cmd_admin(message, state)

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    chat_mode[callback.from_user.id] = False
    txt = await get_text(callback.from_user.id, "send_broadcast")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_broadcast)

@router.message(BotStates.admin_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    count = 0
    users = await db.fetchall("SELECT user_id FROM users")
    for u in users:
        try:
            await bot.send_message(u[0], message.text)
            count += 1
        except:
            pass
    done_txt = await get_text(message.from_user.id, "broadcast_done")
    await message.answer(done_txt.format(count))
    await state.clear()
    await cmd_admin(message, state)

@router.callback_query(F.data == "admin_clear_cache")
async def admin_clear_cache_start(callback: CallbackQuery, state: FSMContext):
    chat_mode[callback.from_user.id] = False
    confirm_txt = await get_text(callback.from_user.id, "clear_cache_confirm")
    btn_yes = await get_text(callback.from_user.id, "btn_yes")
    btn_no = await get_text(callback.from_user.id, "btn_no")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_yes, callback_data="clear_cache_yes")],
        [InlineKeyboardButton(text=btn_no, callback_data="clear_cache_no")]
    ])
    await callback.message.edit_text(confirm_txt, reply_markup=kb)
    await state.set_state(BotStates.admin_clear_cache_confirm)

@router.callback_query(F.data == "clear_cache_yes")
async def clear_cache_yes(callback: CallbackQuery, state: FSMContext):
    await db.clear_history()
    done_txt = await get_text(callback.from_user.id, "clear_cache_done")
    await callback.answer(done_txt, show_alert=True)
    await state.clear()
    chat_mode[callback.from_user.id] = False
    await admin_database_menu(callback)

@router.callback_query(F.data == "clear_cache_no")
async def clear_cache_no(callback: CallbackQuery, state: FSMContext):
    cancel_txt = await get_text(callback.from_user.id, "clear_cancelled")
    await callback.answer(cancel_txt, show_alert=True)
    await state.clear()
    chat_mode[callback.from_user.id] = False
    await admin_database_menu(callback)

@router.callback_query(F.data == "admin_clear_all")
async def admin_clear_all_start(callback: CallbackQuery, state: FSMContext):
    chat_mode[callback.from_user.id] = False
    if not db.use_cloud:
        no_cloud_msg = await get_text(callback.from_user.id, "no_cloud_db")
        await callback.answer(no_cloud_msg, show_alert=True)
        return
    confirm_txt = await get_text(callback.from_user.id, "clear_all_confirm")
    btn_yes = await get_text(callback.from_user.id, "btn_yes")
    btn_no = await get_text(callback.from_user.id, "btn_no")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_yes, callback_data="clear_all_yes")],
        [InlineKeyboardButton(text=btn_no, callback_data="clear_all_no")]
    ])
    await callback.message.edit_text(confirm_txt, reply_markup=kb)
    await state.set_state(BotStates.admin_clear_all_confirm)

@router.callback_query(F.data == "clear_all_yes")
async def clear_all_yes(callback: CallbackQuery, state: FSMContext):
    await db.truncate_all_tables()
    done_txt = await get_text(callback.from_user.id, "clear_all_done")
    await callback.answer(done_txt, show_alert=True)
    await state.clear()
    chat_mode[callback.from_user.id] = False
    await admin_database_menu(callback)

@router.callback_query(F.data == "clear_all_no")
async def clear_all_no(callback: CallbackQuery, state: FSMContext):
    cancel_txt = await get_text(callback.from_user.id, "clear_cancelled")
    await callback.answer(cancel_txt, show_alert=True)
    await state.clear()
    chat_mode[callback.from_user.id] = False
    await admin_database_menu(callback)

@router.callback_query(F.data == "admin_view_data")
async def admin_view_data(callback: CallbackQuery):
    chat_mode[callback.from_user.id] = False
    user_id = callback.from_user.id
    progress_msg = None
    try:
        progress_msg = await callback.message.answer(
            (await get_text(user_id, "loading_data")).format(progress=0)
        )
        total_steps = 20
        for i in range(1, total_steps + 1):
            progress = i * 5
            if progress > 100:
                progress = 100
            try:
                await progress_msg.edit_text(
                    (await get_text(user_id, "loading_data")).format(progress=progress)
                )
            except Exception:
                pass
            await asyncio.sleep(0.02)
        data = await db.get_all_data()
        if not data:
            await progress_msg.edit_text("⚠️ " + await get_text(user_id, "no_routers"))
            return
        text = await get_text(user_id, "all_data_title")
        for router in data:
            header = await get_text(user_id, "data_router_header")
            header = header.format(id=router['id'], domain=router['domain'], base_url=router['base_url'], api_key=router['api_key'])
            text += header
            if router['models']:
                for m_id, m_name in router['models']:
                    emoji = get_model_emoji(m_name, m_id)
                    line = await get_text(user_id, "data_model_line")
                    line = line.format(name=m_name, emoji=emoji)
                    text += line
            else:
                text += await get_text(user_id, "data_no_models")
            text += "\n"
        await progress_msg.delete()
        if len(text) > 4000:
            file = BufferedInputFile(text.encode('utf-8'), filename="all_data.txt")
            await callback.message.answer_document(file, caption="📄 " + await get_text(user_id, "data_loaded"))
        else:
            btn_back = await get_text(user_id, "btn_back")
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_back, callback_data="admin_database_menu")]])
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
        await callback.answer()
    except Exception as e:
        logging.exception(f"Error in admin_view_data for user {user_id}: {e}")
        if progress_msg:
            try:
                await progress_msg.delete()
            except:
                pass
        error_txt = await get_text(user_id, "error_occurred")
        detail_txt = await get_text(user_id, "error_detail")
        detail_txt = detail_txt.format(error=str(e)[:200])
        await callback.message.answer(error_txt)
        await callback.message.answer(detail_txt)
        await callback.answer()

@router.callback_query(F.data == "admin_routers")
async def admin_routers_list(callback: CallbackQuery):
    chat_mode[callback.from_user.id] = False
    routers = await db.fetchall("SELECT id, domain FROM routers")
    if not routers:
        no_routers_text = await get_text(callback.from_user.id, "no_routers")
        btn_back = await get_text(callback.from_user.id, "btn_back_main")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_back, callback_data="admin_back")]])
        await callback.message.edit_text(no_routers_text, reply_markup=kb)
        return
    buttons = []
    for r_id, domain in routers:
        buttons.append([InlineKeyboardButton(text=domain, callback_data=f"router_{r_id}")])
    btn_back = await get_text(callback.from_user.id, "btn_back_main")
    buttons.append([InlineKeyboardButton(text=btn_back, callback_data="admin_back")])
    title = await get_text(callback.from_user.id, "title_routers")
    await callback.message.edit_text(title, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("router_"))
async def admin_router_details(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    chat_mode[callback.from_user.id] = False
    r_id = callback.data.split("_")[1]
    r = await db.fetchone("SELECT domain, base_url, api_key FROM routers WHERE id = ?", (r_id,))
    models = await db.fetchall("SELECT id, model_name FROM models WHERE router_id = ?", (r_id,))
    if not r:
        return
    model_lines = []
    for i, (m_id, m_name) in enumerate(models):
        emoji = get_model_emoji(m_name, m_id)
        prefix = "  └" if i == len(models) - 1 else "  ├"
        model_lines.append(f"{prefix} {emoji} `{m_name}`")
    model_text = "\n".join(model_lines) if model_lines else "  └ ⚠️ (no models)"
    txt_template = await get_text(callback.from_user.id, "router_details")
    msg = txt_template.format(r[0], r[1], r[2], model_text)
    btn_add = await get_text(callback.from_user.id, "btn_add_mod")
    btn_del_mod = await get_text(callback.from_user.id, "btn_del_mod")
    btn_del = await get_text(callback.from_user.id, "btn_del_router")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    buttons = [
        [InlineKeyboardButton(text=btn_add, callback_data=f"addmod_{r_id}"),
         InlineKeyboardButton(text=btn_del_mod, callback_data=f"delmodprompt_{r_id}")],
        [InlineKeyboardButton(text=btn_del, callback_data=f"askdel_{r_id}")],
        [InlineKeyboardButton(text=btn_back, callback_data="admin_routers")]
    ]
    await callback.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("delmodprompt_"))
async def admin_del_model_prompt(callback: CallbackQuery, state: FSMContext):
    chat_mode[callback.from_user.id] = False
    r_id = callback.data.split("_")[1]
    await state.update_data(r_id=r_id)
    txt = await get_text(callback.from_user.id, "send_del_model")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    buttons = [[InlineKeyboardButton(text=btn_back, callback_data=f"router_{r_id}")]]
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(BotStates.admin_del_model_only)

@router.message(BotStates.admin_del_model_only)
async def admin_del_model_execute(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    data = await state.get_data()
    model_name = message.text.strip()
    res = await db.execute("DELETE FROM models WHERE router_id = ? AND model_name = ?", (data['r_id'], model_name))
    deleted_count = res['rowcount']
    await db.execute("UPDATE users SET current_model_id = NULL WHERE current_model_id NOT IN (SELECT id FROM models)")
    if deleted_count > 0:
        txt = await get_text(message.from_user.id, "model_deleted")
    else:
        txt = await get_text(message.from_user.id, "model_not_found")
    await message.answer(txt)
    await state.clear()
    await cmd_admin(message, state)

@router.callback_query(F.data.startswith("askdel_"))
async def admin_ask_delete(callback: CallbackQuery):
    chat_mode[callback.from_user.id] = False
    r_id = callback.data.split("_")[1]
    msg = await get_text(callback.from_user.id, "del_confirm_msg")
    btn_yes = await get_text(callback.from_user.id, "btn_yes")
    btn_no = await get_text(callback.from_user.id, "btn_no")
    buttons = [
        [InlineKeyboardButton(text=btn_yes, callback_data=f"confirmdel_{r_id}")],
        [InlineKeyboardButton(text=btn_no, callback_data=f"router_{r_id}")]
    ]
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("confirmdel_"))
async def admin_confirm_delete(callback: CallbackQuery):
    chat_mode[callback.from_user.id] = False
    r_id = callback.data.split("_")[1]
    await db.execute("DELETE FROM routers WHERE id = ?", (r_id,))
    await db.execute("DELETE FROM models WHERE router_id = ?", (r_id,))
    await db.execute("UPDATE users SET current_model_id = NULL WHERE current_model_id NOT IN (SELECT id FROM models)")
    msg = await get_text(callback.from_user.id, "del_success")
    await callback.answer(msg, show_alert=True)
    await admin_routers_list(callback)

@router.callback_query(F.data.startswith("addmod_"))
async def admin_add_model_only(callback: CallbackQuery, state: FSMContext):
    chat_mode[callback.from_user.id] = False
    r_id = callback.data.split("_")[1]
    await state.update_data(r_id=r_id)
    txt = await get_text(callback.from_user.id, "send_model_for_router")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_back, callback_data=f"router_{r_id}")]
    ])
    await callback.message.answer(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_add_model_only)
    await callback.answer()

@router.message(BotStates.admin_add_model_only)
async def admin_save_model_only(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    data = await state.get_data()
    r_id = data['r_id']
    model_name = message.text.strip()
    await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (r_id, model_name))
    finish_btn = InlineKeyboardButton(
        text=await get_text(message.from_user.id, "finish"),
        callback_data=f"router_{r_id}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[finish_btn]])
    await message.answer(
        await get_text(message.from_user.id, "model_added_continue"),
        reply_markup=kb
    )

@router.callback_query(F.data == "admin_add_router")
async def add_router_start(callback: CallbackQuery, state: FSMContext):
    chat_mode[callback.from_user.id] = False
    txt = await get_text(callback.from_user.id, "send_url")
    btn_back = await get_text(callback.from_user.id, "btn_back_main")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_add_router_url)

@router.message(BotStates.admin_add_router_url)
async def add_router_url(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        err_txt = await get_text(message.from_user.id, "invalid_url")
        btn_back = await get_text(message.from_user.id, "btn_back_main")
        return await message.answer(err_txt, reply_markup=cancel_admin_keyboard(message.from_user.id, btn_back))
    domain = urlparse(url).netloc or url
    await state.update_data(base_url=url, domain=domain)
    txt = await get_text(message.from_user.id, "url_detected")
    btn_back = await get_text(message.from_user.id, "btn_back_main")
    await message.answer(txt.format(domain), reply_markup=cancel_admin_keyboard(message.from_user.id, btn_back))
    await state.set_state(BotStates.admin_add_router_key)

@router.message(BotStates.admin_add_router_key)
async def add_router_key(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    await state.update_data(api_key=message.text.strip())
    
    await message.answer(await get_text(message.from_user.id, "send_model"))
    
    await state.set_state(BotStates.admin_add_router_model)

@router.message(BotStates.admin_add_router_model)
async def add_router_model_finish(message: Message, state: FSMContext):
    chat_mode[message.from_user.id] = False
    data = await state.get_data()
    model_name = message.text.strip()
    
    if 'router_saved' not in data or not data.get('router_saved'):
        res = await db.execute("INSERT INTO routers (domain, base_url, api_key) VALUES (?, ?, ?)",
                               (data['domain'], data['base_url'], data['api_key']))
        r_id = res['lastrowid']
        await state.update_data(router_id=r_id, router_saved=True)
    else:
        r_id = data['router_id']
        
    await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (r_id, model_name))
    
    finish_btn = InlineKeyboardButton(text=await get_text(message.from_user.id, "finish"), callback_data=f"router_{r_id}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[finish_btn]])
    
    await message.answer(await get_text(message.from_user.id, "router_added_continue"), reply_markup=kb)


@router.message(Command("man"))
@router.message(Command("contactadmin"))
async def cmd_contact_admin(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()
    chat_mode[user_id] = False
    await state.set_state(BotStates.contact_admin)
    intro = await get_text(user_id, "contact_intro")
    await message.answer(intro)

@router.callback_query(F.data == "contact_admin")
async def contact_admin_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.clear()
    chat_mode[user_id] = False
    await state.set_state(BotStates.contact_admin)
    intro = await get_text(user_id, "contact_intro")
    await callback.message.answer(intro)
    await callback.answer()

@router.message()
async def process_user_chat(message: Message, state: FSMContext):
    user_id = message.from_user.id

    current_state = await state.get_state()
    if current_state == BotStates.contact_admin:
        text = message.text or message.caption or "[non-text message]"
        forward_text = await get_text(ADMIN_ID, "contact_forward")
        forward_text = forward_text.format(name=message.from_user.full_name, user_id=user_id, text=text)
        await bot.send_message(ADMIN_ID, forward_text)
        end_msg = await get_text(user_id, "contact_end_auto")
        await message.answer(end_msg)
        await state.clear()
        await show_user_panel(message, user_id)
        return

    if message.from_user.id == ADMIN_ID and message.reply_to_message:
        replied = message.reply_to_message
        if replied.text and ("User ID:" in replied.text or "شناسه:" in replied.text or "ID:" in replied.text):
            text = replied.text
            match = re.search(r'(?:User ID|شناسه|ID):\s*(\d+)', text)
            if match:
                target_user_id = int(match.group(1))
                reply_text = await get_text(target_user_id, "contact_admin_reply")
                reply_text = reply_text.format(text=message.text)
                await bot.send_message(target_user_id, reply_text)
                confirm_text = await get_text(ADMIN_ID, "admin_reply_sent")
                await message.reply(confirm_text)
                return

    allowed, limit_data = await is_user_authorized_for_chat(user_id)
    if not allowed:
        limit, msg_count = limit_data
        pwd_row = await db.fetchone("SELECT value FROM settings WHERE key = 'global_password'")
        global_pwd = pwd_row[0] if pwd_row else None
        if global_pwd and message.text and message.text.strip() == global_pwd:
            await db.execute("UPDATE users SET is_auth = 1, msg_count = 0 WHERE user_id = ?", (user_id,))
            await message.answer(await get_text(user_id, "pwd_ok"))
            if not chat_mode.get(user_id, False):
                await show_user_panel(message, user_id)
            return
        else:
            if message.text and not message.text.startswith('/') and msg_count > limit:
                await message.answer(await get_text(user_id, "pwd_err"))
                block_msg = await get_text(user_id, "limit_blocked")
                block_msg = block_msg.format(limit=limit)
                contact_btn = InlineKeyboardButton(
                    text=await get_text(user_id, "contact_button"),
                    callback_data="contact_admin"
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[[contact_btn]])
                await message.answer(block_msg, reply_markup=kb)
            else:
                block_msg = await get_text(user_id, "limit_blocked")
                block_msg = block_msg.format(limit=limit)
                contact_btn = InlineKeyboardButton(
                    text=await get_text(user_id, "contact_button"),
                    callback_data="contact_admin"
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[[contact_btn]])
                await message.answer(block_msg, reply_markup=kb)
            return

    if not chat_mode.get(user_id, False):
        unknown_txt = await get_text(user_id, "unknown_command")
        await message.answer(unknown_txt)
        await show_user_panel(message, user_id)
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
        chat_mode[user_id] = False
        return

    active_model = await db.fetchone("""
        SELECT m.model_name, r.base_url, r.api_key
        FROM users u
        JOIN models m ON u.current_model_id = m.id
        JOIN routers r ON m.router_id = r.id
        WHERE u.user_id = ? AND r.api_key IS NOT NULL AND r.api_key != ''
    """, (user_id,))

    if not active_model:
        chat_mode[user_id] = False
        invalid_txt = await get_text(user_id, "invalid_model")
        await message.answer(invalid_txt)
        await show_user_panel(message, user_id)
        return

    m_name, url_base, key = active_model
    url = url_base.strip().rstrip('/')
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    content_text = message.text or message.caption or ""
    image_base64 = None

    if message.document:
        try:
            file_info = await bot.get_file(message.document.file_id)
            downloaded = await bot.download_file(file_info.file_path)
            file_bytes = downloaded.read()
            try:
                file_str = file_bytes.decode('utf-8')
                content_text += f"\n\n--- File Content of {message.document.file_name} ---\n{file_str}"
            except UnicodeDecodeError:
                content_text += f"\n\n[Received a binary document file: {message.document.file_name}]"
        except Exception as e:
            content_text += f"\n\n[Failed to read file: {e}]"
    elif message.photo:
        try:
            file_info = await bot.get_file(message.photo[-1].file_id)
            downloaded = await bot.download_file(file_info.file_path)
            image_base64 = base64.b64encode(downloaded.read()).decode('utf-8')
        except Exception as e:
            content_text += f"\n\n[Failed to process image: {e}]"
    elif message.video or message.audio or message.voice:
        content_text += f"\n\n[Received a media file]"

    if not content_text and not image_base64:
        content_text = "."

    rows = await db.fetchall("SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))
    messages = [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    if image_base64:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": content_text or "Please analyze this image"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
            ]
        })
    else:
        messages.append({"role": "user", "content": content_text})

    db_content = content_text[:1000] + (" [Image Attached]" if image_base64 else "")
    await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "user", db_content))

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": m_name, "messages": messages}

    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        try:
            async with shared_http_session.post(url, headers=headers, json=payload, timeout=120) as resp:
                resp_data = await resp.json(content_type=None)
                if resp.status == 200 and 'choices' in resp_data:
                    reply_text = resp_data['choices'][0]['message']['content']
                else:
                    reply_text = f"❌ Error API: {resp_data.get('error', {}).get('message', 'Unknown')}"
        except Exception as e:
            reply_text = f"❌ Server connection failed. Detail: {e}"

    if len(reply_text) > 4000:
        text_file = BufferedInputFile(reply_text.encode('utf-8'), filename="response.txt")
        await message.answer_document(text_file, caption="📄 The response was too long, so it's sent as a file.")
    else:
        await message.answer(reply_text)

    await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "assistant", reply_text[:2000] if len(reply_text) > 2000 else reply_text))

async def main():
    global shared_http_session
    shared_http_session = aiohttp.ClientSession()
    try:
        await init_db()
        await dp.start_polling(bot)
    finally:
        await shared_http_session.close()

if __name__ == "__main__":
    asyncio.run(main())
