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
        """Fetch all routers with their models and tokens for display."""
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
        "pwd_ok": "✅ Password accepted!",
        "pwd_err": "❌ Incorrect password.",
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
        "send_channel_prompt": "Send channel username (e.g., @AI_Channel) or 'none':",
        "channel_set": "✅ Force join channel set to: `{}`",
        "channel_none": "🔓 Force join disabled.",
        "must_join": "⛔ You must join our channel to use the bot:",
        "btn_join_channel": "🔗 Join Channel",
        "btn_check_join": "🔄 Check Membership",
        "join_ok": "✅ Membership verified! You can now use the bot.",
        "join_fail": "❌ You haven't joined the channel yet!",
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
        "help_user": "📖 Available Commands\n\n🚀 /start • start ➜ Start\n🌐 /lang • lang ➜ Language\n🤖 /model • model ➜ Clear chat & select new model\n❓ /help • help ➜ Help\n\n✨ Choose and start 🚀",
        "help_admin": "🌐 /lang • lang ➜ Language\n👤 /user • user ➜ User mode\n🤖 /model • model ➜ Clear cache & models\n❓ /help • help ➜ Help\n✨ Choose and start 🚀",
        "stats_text": "📊 **Bot Statistics**\n\n👤 Users: `{users}`\n📢 Force Channel(s): `{channel}`\n🤖 Models: `{models}`\n🗂️ Routers: `{routers}`\n🔑 Tokens: `{tokens}`\n🔐 Password: `{pwd_status}`",
        "btn_view_data": "📋 View All Data",
        "all_data_title": "📋 **All Routers, Models and Tokens**\n\n",
        "data_router_header": "📍 **Router #{id}** – `{domain}`\n🌐 Base URL: `{base_url}`\n🔑 Token: `{api_key}`\n📦 Models:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (no models)\n"
    },
    "fa": {
        "name": "🇮🇷🇦🇫 فارسی",
        "welcome_new": "لطفاً زبان خود را انتخاب کنید:",
        "welcome_back": "خوش برگشتی، {name}!",
        "welcome_first": "👋 خوش آمدی! برای دیدن راهنما از دستور /help استفاده کن.",
        "locked": "⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور را وارد کنید:",
        "pwd_ok": "✅ رمز عبور تایید شد!",
        "pwd_err": "❌ رمز اشتباه است.",
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
        "help_user": "📖 دستورات موجود\n\n🚀 /start • start➜ شروع\n🌐 /lang • lang ➜  زبان\n🤖 /model • model ➜ پاک‌سازی چت و انتخاب مدل جدید\n❓ /help • help ➜  راهنما\n\n✨ انتخاب کن و شروع کن 🚀",
        "help_admin": "🌐 /lang • lang ➜ زبان\n👤 /user • user ➜ کاربری\n🤖 /model • model ➜ پاک‌سازی کش و مدل‌ها\n❓ /help • help ➜ راهنما\n✨ انتخاب کن و شروع کن 🚀",
        "stats_text": "📊 **آمار ربات**\n\n👤 کاربران: `{users}`\n📢 کانال‌های اجباری: `{channel}`\n🤖 مدل‌ها: `{models}`\n🗂️ روترها: `{routers}`\n🔑 توکن‌ها: `{tokens}`\n🔐 رمز عبور: `{pwd_status}`",
        "btn_view_data": "📋 مشاهده داده‌ها",
        "all_data_title": "📋 **همه روترها، مدل‌ها و توکن‌ها**\n\n",
        "data_router_header": "📍 **روتر #{id}** – `{domain}`\n🌐 آدرس: `{base_url}`\n🔑 توکن: `{api_key}`\n📦 مدل‌ها:\n",
        "data_model_line": "   • `{name}`  {emoji}\n",
        "data_no_models": "   (هیچ مدلی وجود ندارد)\n"
    }
}

async def init_db():
    await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT, is_auth INTEGER DEFAULT 0, current_model_id INTEGER)")
    try:
        await db.execute("ALTER TABLE users ADD COLUMN current_model_id INTEGER")
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
    admin_set_channel = State()
    admin_broadcast = State()
    admin_clear_cache_confirm = State()
    admin_clear_all_confirm = State()

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
    builder.button(text=await get_text(user_id, "btn_clear_cache"), callback_data="admin_clear_cache")
    builder.button(text=await get_text(user_id, "btn_clear_all"), callback_data="admin_clear_all")
    builder.button(text=await get_text(user_id, "btn_view_data"), callback_data="admin_view_data")
    builder.button(text=await get_text(user_id, "btn_back"), callback_data="admin_settings_menu")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()

def cancel_admin_keyboard(user_id, text_back):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text_back, callback_data="admin_back")]])

async def show_user_panel(target, user_id, page=0, is_admin_view=False, edit=False):
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

    all_models = await db.fetchall("SELECT id, model_name FROM models ORDER BY id")
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
    user_exists = await db.fetchone("SELECT lang FROM users WHERE user_id = ?", (message.from_user.id,))
    if not user_exists:
        await db.execute("INSERT OR IGNORE INTO users (user_id, lang) VALUES (?, ?)", (message.from_user.id, "en"))
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
    await message.answer("Please select your language:", reply_markup=lang_keyboard())

@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    await db.execute("""
        INSERT INTO users (user_id, lang) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang
    """, (callback.from_user.id, lang))
    await callback.message.delete()
    await show_user_panel(callback.message, callback.from_user.id)

@router.message(Command("user"))
@router.message(F.text.lower().in_({"user", "/user"}))
async def cmd_user(message: Message, state: FSMContext):
    await state.clear()
    await show_user_panel(message, message.from_user.id)

@router.callback_query(F.data == "check_join_channel")
async def check_join_callback(callback: CallbackQuery):
    joined, channels = await check_channel_join(callback.from_user.id)
    if joined:
        ok_txt = await get_text(callback.from_user.id, "join_ok")
        await callback.answer(ok_txt, show_alert=True)
        await callback.message.delete()
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
    admin_text = await get_text(callback.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("selmod_"))
async def select_model(callback: CallbackQuery, state: FSMContext):
    model_id = callback.data.split("_")[1]
    user_id = callback.from_user.id
    row = await db.fetchone("SELECT model_name FROM models WHERE id = ?", (model_id,))
    if not row:
        await callback.answer(await get_text(user_id, "model_not_found"), show_alert=True)
        return
    model_name = row[0]
    is_authorized = await check_auth(user_id)
    if not is_authorized:
        locked_text = await get_text(user_id, "locked")
        await callback.answer(locked_text, show_alert=True)
        await callback.message.answer(locked_text)
        await state.set_state(BotStates.waiting_for_password)
        return
    await db.execute("UPDATE users SET current_model_id = ? WHERE user_id = ?", (model_id, user_id))
    await db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    chat_start_txt = await get_text(user_id, "chat_started")
    await callback.message.answer(chat_start_txt.format(model_name))
    await callback.answer()

@router.message(BotStates.waiting_for_password)
async def check_password_input(message: Message, state: FSMContext):
    pwd_row = await db.fetchone("SELECT value FROM settings WHERE key = 'global_password'")
    global_pwd = pwd_row[0] if pwd_row else ""
    if message.text == global_pwd or global_pwd.lower() == 'none':
        await db.execute("UPDATE users SET is_auth = 1 WHERE user_id = ?", (message.from_user.id,))
        success_text = await get_text(message.from_user.id, "pwd_ok")
        await message.answer(success_text)
        await state.clear()
        await show_user_panel(message, message.from_user.id)
    else:
        err_text = await get_text(message.from_user.id, "pwd_err")
        await message.answer(err_text)

@router.message(Command("model"))
@router.message(F.text.lower().in_({"model", "/model"}))
async def cmd_model_exit(message: Message, state: FSMContext):
    await state.clear()
    await db.execute("DELETE FROM history WHERE user_id = ?", (message.from_user.id,))
    await show_user_panel(message, message.from_user.id)

@router.message(Command("admin"))
@router.message(F.text.lower().in_({"admin", "/admin"}))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
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
    if message.from_user.id == ADMIN_ID:
        help_text = await get_text(message.from_user.id, "help_admin")
    else:
        help_text = await get_text(message.from_user.id, "help_user")
    await message.answer(help_text, parse_mode="Markdown")

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    admin_text = await get_text(callback.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)

@router.callback_query(F.data == "admin_settings_menu")
async def admin_settings_menu(callback: CallbackQuery):
    title = await get_text(callback.from_user.id, "title_settings")
    kb = await admin_settings_keyboard(callback.from_user.id)
    await callback.message.edit_text(title, reply_markup=kb)

@router.callback_query(F.data == "admin_database_menu")
async def admin_database_menu(callback: CallbackQuery):
    title = "🗄️ " + await get_text(callback.from_user.id, "btn_database")
    kb = await admin_database_keyboard(callback.from_user.id)
    await callback.message.edit_text(title, reply_markup=kb)

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
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
    await show_user_panel(callback, callback.from_user.id, is_admin_view=True, edit=True)
    await callback.answer()

@router.callback_query(F.data.startswith("userpage_"))
async def user_page_callback(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    is_admin = (callback.from_user.id == ADMIN_ID)
    await show_user_panel(callback, callback.from_user.id, page=page, is_admin_view=False, edit=True)
    await callback.answer()

@router.callback_query(F.data == "admin_pwd")
async def admin_pwd_start(callback: CallbackQuery, state: FSMContext):
    txt = await get_text(callback.from_user.id, "send_pwd_prompt")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_set_password)

@router.message(BotStates.admin_set_password)
async def admin_pwd_save(message: Message, state: FSMContext):
    new_pwd = message.text.strip()
    if new_pwd.lower() == 'none':
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_password', 'none')")
        await db.execute("UPDATE users SET is_auth = 1")
        res_txt = await get_text(message.from_user.id, "pwd_none")
    else:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_password', ?)", (new_pwd,))
        await db.execute("UPDATE users SET is_auth = 0")
        res_txt = await get_text(message.from_user.id, "pwd_set")
        res_txt = res_txt.format(new_pwd)
    await message.answer(res_txt)
    await state.clear()
    await cmd_admin(message, state)

@router.callback_query(F.data == "admin_channel")
async def admin_channel_start(callback: CallbackQuery, state: FSMContext):
    txt = await get_text(callback.from_user.id, "send_channel_prompt")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_set_channel)

@router.message(BotStates.admin_set_channel)
async def admin_channel_save(message: Message, state: FSMContext):
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
    txt = await get_text(callback.from_user.id, "send_broadcast")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_broadcast)

@router.message(BotStates.admin_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
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
    await admin_database_menu(callback)

@router.callback_query(F.data == "clear_cache_no")
async def clear_cache_no(callback: CallbackQuery, state: FSMContext):
    cancel_txt = await get_text(callback.from_user.id, "clear_cancelled")
    await callback.answer(cancel_txt, show_alert=True)
    await state.clear()
    await admin_database_menu(callback)

@router.callback_query(F.data == "admin_clear_all")
async def admin_clear_all_start(callback: CallbackQuery, state: FSMContext):
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
    await admin_database_menu(callback)

@router.callback_query(F.data == "clear_all_no")
async def clear_all_no(callback: CallbackQuery, state: FSMContext):
    cancel_txt = await get_text(callback.from_user.id, "clear_cancelled")
    await callback.answer(cancel_txt, show_alert=True)
    await state.clear()
    await admin_database_menu(callback)

@router.callback_query(F.data == "admin_view_data")
async def admin_view_data(callback: CallbackQuery):
    data = await db.get_all_data()
    if not data:
        await callback.answer("⚠️ هیچ داده‌ای یافت نشد.", show_alert=True)
        return
    text = await get_text(callback.from_user.id, "all_data_title")
    for router in data:
        header = await get_text(callback.from_user.id, "data_router_header")
        header = header.format(id=router['id'], domain=router['domain'], base_url=router['base_url'], api_key=router['api_key'])
        text += header
        if router['models']:
            for m_id, m_name in router['models']:
                emoji = get_model_emoji(m_name, m_id)
                line = await get_text(callback.from_user.id, "data_model_line")
                line = line.format(name=m_name, emoji=emoji)
                text += line
        else:
            text += await get_text(callback.from_user.id, "data_no_models")
        text += "\n"
    if len(text) > 4000:
        file = BufferedInputFile(text.encode('utf-8'), filename="all_data.txt")
        await callback.message.answer_document(file, caption="📄 تمام داده‌ها به صورت فایل ارسال شد.")
    else:
        btn_back = await get_text(callback.from_user.id, "btn_back")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_back, callback_data="admin_database_menu")]])
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_routers")
async def admin_routers_list(callback: CallbackQuery):
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
async def admin_router_details(callback: CallbackQuery):
    r_id = callback.data.split("_")[1]
    r = await db.fetchone("SELECT domain, base_url, api_key FROM routers WHERE id = ?", (r_id,))
    models = await db.fetchall("SELECT id, model_name FROM models WHERE router_id = ?", (r_id,))
    if not r:
        return
    model_lines = []
    for m_id, m_name in models:
        emoji = get_model_emoji(m_name, m_id)
        model_lines.append(f"`{m_name}`  {emoji}")
    model_text = "\n".join(model_lines) if model_lines else "(no models)"
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
    r_id = callback.data.split("_")[1]
    await state.update_data(r_id=r_id)
    txt = await get_text(callback.from_user.id, "send_del_model")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    buttons = [[InlineKeyboardButton(text=btn_back, callback_data=f"router_{r_id}")]]
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(BotStates.admin_del_model_only)

@router.message(BotStates.admin_del_model_only)
async def admin_del_model_execute(message: Message, state: FSMContext):
    data = await state.get_data()
    model_name = message.text.strip()
    res = await db.execute("DELETE FROM models WHERE router_id = ? AND model_name = ?", (data['r_id'], model_name))
    deleted_count = res['rowcount']
    await db.execute("""
        UPDATE users SET current_model_id = NULL
        WHERE current_model_id NOT IN (SELECT id FROM models)
    """)
    if deleted_count > 0:
        txt = await get_text(message.from_user.id, "model_deleted")
    else:
        txt = await get_text(message.from_user.id, "model_not_found")
    await message.answer(txt)
    await state.clear()
    await cmd_admin(message, state)

@router.callback_query(F.data.startswith("askdel_"))
async def admin_ask_delete(callback: CallbackQuery):
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
    r_id = callback.data.split("_")[1]
    await db.execute("DELETE FROM routers WHERE id = ?", (r_id,))
    await db.execute("DELETE FROM models WHERE router_id = ?", (r_id,))
    await db.execute("UPDATE users SET current_model_id = NULL WHERE current_model_id NOT IN (SELECT id FROM models)")
    msg = await get_text(callback.from_user.id, "del_success")
    await callback.answer(msg, show_alert=True)
    await admin_routers_list(callback)

@router.callback_query(F.data.startswith("addmod_"))
async def admin_add_model_only(callback: CallbackQuery, state: FSMContext):
    r_id = callback.data.split("_")[1]
    await state.update_data(r_id=r_id)
    txt = await get_text(callback.from_user.id, "send_model_for_router")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_back, callback_data=f"router_{r_id}")]
    ])
    await callback.message.edit_text(txt, reply_markup=kb)
    await state.set_state(BotStates.admin_add_model_only)

@router.message(BotStates.admin_add_model_only)
async def admin_save_model_only(message: Message, state: FSMContext):
    data = await state.get_data()
    r_id = data['r_id']
    model_name = message.text.strip()
    await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (r_id, model_name))
    # Show success message with "Finish" button
    txt = await get_text(message.from_user.id, "model_deleted")  # reuse but we'll change to a custom message
    # Actually we need a custom message: "✅ مدل اضافه شد. نام مدل بعدی را وارد کنید"
    # But we have to get the localized version. We'll use a hardcoded or add a new key.
    # For simplicity, we'll send a new message with a "Finish" button.
    finish_btn = InlineKeyboardButton(text="✅ پایان", callback_data=f"addmod_done_{r_id}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[finish_btn]])
    await message.answer("✅ مدل اضافه شد. نام مدل بعدی را وارد کنید", reply_markup=kb)
    # state remains

@router.callback_query(F.data.startswith("addmod_done_"))
async def admin_add_model_done(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    r_id = callback.data.split("_")[1]
    await callback.answer("✅ افزودن مدل‌ها تمام شد.")
    # Go back to router details
    await admin_router_details(callback)

@router.callback_query(F.data == "admin_add_router")
async def add_router_start(callback: CallbackQuery, state: FSMContext):
    txt = await get_text(callback.from_user.id, "send_url")
    btn_back = await get_text(callback.from_user.id, "btn_back_main")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_add_router_url)

@router.message(BotStates.admin_add_router_url)
async def add_router_url(message: Message, state: FSMContext):
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
    await state.update_data(api_key=message.text.strip())
    txt = await get_text(message.from_user.id, "send_model")
    btn_back = await get_text(message.from_user.id, "btn_back_main")
    await message.answer(txt, reply_markup=cancel_admin_keyboard(message.from_user.id, btn_back))
    await state.set_state(BotStates.admin_add_router_model)

@router.message(BotStates.admin_add_router_model)
async def add_router_model_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    model_name = message.text.strip()
    # If router not saved yet, save it now
    if 'router_saved' not in data or not data.get('router_saved'):
        res = await db.execute("INSERT INTO routers (domain, base_url, api_key) VALUES (?, ?, ?)",
                               (data['domain'], data['base_url'], data['api_key']))
        r_id = res['lastrowid']
        await state.update_data(router_id=r_id, router_saved=True)
    else:
        r_id = data['router_id']
    await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (r_id, model_name))
    # Show success with Finish button
    finish_btn = InlineKeyboardButton(text="✅ پایان", callback_data="add_router_done")
    kb = InlineKeyboardMarkup(inline_keyboard=[[finish_btn]])
    await message.answer("✅ مدل اضافه شد. نام مدل بعدی را وارد کنید", reply_markup=kb)
    # state remains

@router.callback_query(F.data == "add_router_done")
async def add_router_done(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("✅ ثبت روتر و مدل‌ها تمام شد.")
    await cmd_admin(callback.message, state)  # go to admin panel

@router.message()
async def process_user_chat(message: Message, state: FSMContext):
    user_id = message.from_user.id
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

    active_model = await db.fetchone("""
        SELECT m.model_name, r.base_url, r.api_key
        FROM users u
        JOIN models m ON u.current_model_id = m.id
        JOIN routers r ON m.router_id = r.id
        WHERE u.user_id = ?
    """, (user_id,))

    if not active_model:
        invalid_txt = await get_text(user_id, "invalid_command")
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
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=120) as resp:
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
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
