import os
import json
import logging
import asyncio
import aiohttp
import aiosqlite
from urllib.parse import urlparse
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

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
        elif self.provider == "generic":
            self.use_cloud = bool(CLOUD_API_URL and CLOUD_API_TOKEN)
        else:
            self.use_cloud = False

    async def _cloud_request(self, query, params=()):
        if self.provider == "cloudflare":
            url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/d1/database/{CLOUDFLARE_D1_DATABASE_ID}/query"
            headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}
            payload = {"sql": query, "params": list(params)}
        elif self.provider == "generic":
            url = CLOUD_API_URL
            headers = {"Authorization": f"Bearer {CLOUD_API_TOKEN}", "Content-Type": "application/json"}
            try:
                template = json.loads(CLOUD_QUERY_BODY)
            except:
                template = {"sql": "query", "params": []}
            payload_str = json.dumps(template).replace('"query"', json.dumps(query)).replace('"params"', json.dumps(list(params)))
            payload = json.loads(payload_str)
        else:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=10) as resp:
                    data = await resp.json()
                    if self.provider == "cloudflare":
                        return data["result"][0] if data.get("success") and data.get("result") else None
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

db = DatabaseManager()

MODEL_EMOJI_MAP = {
    "gpt": "🧠", "deepseek": "🐟", "claude": "🤖", "gemini": "🌟",
    "llama": "🦙", "mistral": "🌪️", "qwen": "🐉", "command": "⚡",
    "dalle": "🎨", "whisper": "🎤",
}
FALLBACK_EMOJIS = ["🧠", "🤖", "🚀", "💡", "⚡", "🔥", "🌟", "💎", "📡", "🛸", "🧩", "🎯"]

def get_model_emoji(model_name: str, model_id: int) -> str:
    name_lower = model_name.lower()
    for key, emoji in MODEL_EMOJI_MAP.items():
        if key in name_lower:
            return emoji
    return FALLBACK_EMOJIS[model_id % len(FALLBACK_EMOJIS)]

def shorten_model_name(name: str, max_len: int = 25) -> str:
    if len(name) <= max_len: return name
    if '/' in name:
        parts = name.split('/')
        if len(parts[-1]) <= max_len: return parts[-1]
    return name[:max_len] + '…'

LANGS = {
    "en": {"name":"🇬🇧 English","welcome_new":"Select your language:","welcome_back":"Welcome back, {name}!","welcome_first":"👋 Welcome! Use /help to see available commands.","locked":"⛔ Unauthorized. Please enter the password:","pwd_ok":"✅ Password accepted! Continue chatting...","pwd_err":"⛔ Please enter the correct password:","pwd_none":"🔓 Password requirement removed. Bot is public.","pwd_set":"✅ New password set: `{}`","admin_only":"❌ Admin only.","type_here":"Type your message...","select_model":"Select an AI model to start a NEW chat:","no_models_admin":"⚠️ No models available.","no_models_user":"⚠️ No models available.","chat_started":"✅ Connected to {}.\nSend your message:","invalid_url":"❌ Invalid URL format. Please send a valid Base URL (http/https):","admin_menu":"⚙️ Advanced Admin Panel – use the menu below:","btn_routers":"🗂 API List","btn_add_router":"➕ Add Router","btn_settings":"⚙️ Settings","btn_database":"🗄️ Database","btn_stats":"📊 Stats & Status","btn_set_pwd":"🔐 Set Password","btn_set_channel":"📢 Force Join","btn_broadcast":"📢 Broadcast","btn_back":"🔙 Back","btn_back_main":"🏠 Main Menu","send_pwd_prompt":"Send new password (or 'none' to make public):","send_limit_prompt":"Enter the number of messages allowed for unauthorized users (e.g., 5):","send_broadcast":"Send your broadcast message:","broadcast_done":"✅ Sent to {} users.","send_url":"Send the Base URL (e.g., https://api.openai.com/v1):","url_detected":"Domain: {}\nNow send the API Key (Token):","send_model":"API Key saved.\nNow send the exact Model Name:","send_model_for_router":"Send the exact Model Name to add to this router:","router_added":"✅ Router and Model added successfully!","router_details":"📌 **Router:** {}\n🌐 Base URL: `{}`\n🔑 Token: `{}`\n📦 **Models:**\n{}","btn_add_mod":"➕ Add Model","btn_del_mod":"🗑 Delete Model","btn_del_router":"🗑 Delete Router","del_confirm_msg":"⚠️ Are you sure you want to delete this router and its models?","btn_yes":"✅ Yes","btn_no":"❌ No","del_success":"✅ Deleted.","pls_select_model":"Please select a valid model.","invalid_command":"❌ Invalid command.","send_channel_prompt":"Send channel username (e.g., @AI_Channel) or 'none':","channel_set":"✅ Force join channel(s) set to: `{}`","channel_none":"🔓 Force join disabled.","must_join":"⛔ You must join our channel(s) to use the bot:\n{channels}","btn_join_channel":"🔗 Join Channel","btn_check_join":"🔄 Check Membership","join_ok":"✅ Membership verified! You can now use the bot.","join_fail":"❌ You haven't joined all required channels yet!","send_del_model":"Send the exact name of the model to delete:","model_deleted":"✅ Model deleted successfully.","model_not_found":"❌ Model not found.","btn_user_mode":"👤 User Mode","btn_clear_cache":"🧹 Clear Cache (history only)","btn_clear_all":"🗑️ Full Database Wipe","clear_cache_confirm":"🧹 This will delete all chat history. ❓ Are you sure?","clear_cache_done":"✅ Chat history cleared.","clear_all_confirm":"🗑️ This will delete ALL data. ❓ Are you sure?","clear_all_done":"✅ All data has been wiped.","clear_cancelled":"❌ Operation cancelled.","btn_admin_panel":"⚙️ Admin Panel","stats_text":"📊 **Bot Statistics**\n👤 Users: `{users}`\n🤖 Models: `{models}`\n🗂️ Routers: `{routers}`\n🔐 Password: `{pwd_status}`","btn_view_data":"📋 View All Data","unknown_command":"❌ Unknown command","model_added_continue":"✅ Model added. Enter next model name, or press 'Finish'.","finish":"✅ Finish","add_router_done":"✅ Router and models registered successfully.","loading_data":"⏳ Loading data...","data_loaded":"✅ Data loaded successfully.","contact_intro":"Write your request to the admin:","contact_confirm":"✅ Your message was sent.","contact_button":"📞 Contact Admin"},
    "fa": {"name":"🇮🇷🇦🇫 فارسی","welcome_new":"لطفاً زبان خود را انتخاب کنید:","welcome_back":"خوش برگشتی، {name}!","welcome_first":"👋 خوش آمدی! برای دیدن راهنما از /help استفاده کن.","locked":"⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور را وارد کنید:","pwd_ok":"✅ رمز عبور تایید شد! به چت ادامه بده...","pwd_err":"⛔ رمز عبور صحیح را وارد کنید:","pwd_none":"🔓 قفل ربات برداشته شد.","pwd_set":"✅ رمز عبور جدید تنظیم شد: `{}`","admin_only":"❌ دسترسی فقط برای مدیریت.","type_here":"پیام خود را بنویسید...","select_model":"برای شروع یک چت جدید، مدل را انتخاب کنید:","no_models_admin":"⚠️ هنوز هیچ مدلی وجود ندارد.","no_models_user":"⚠️ هنوز هیچ مدلی وجود ندارد.","chat_started":"✅ شما به {} متصل شدید.\nپیام خود را بفرستید:","invalid_url":"❌ فرمت لینک اشتباه است.","admin_menu":"⚙️ پنل مدیریت پیشرفته ربات :","btn_routers":"🗂 APIها","btn_add_router":"➕ روتر جدید","btn_settings":"⚙️ تنظیمات","btn_database":"🗄️ دیتابیس","btn_stats":"📊 آمار و وضعیت","btn_set_pwd":"🔐 رمز عبور","btn_set_channel":"📢 کانال اجباری","btn_broadcast":"📢 پیام همگانی","btn_back":"🔙 بازگشت","btn_back_main":"🏠 منوی اصلی","send_pwd_prompt":"رمز جدید را بفرستید (یا none برای آزادسازی):","send_limit_prompt":"تعداد پیام‌های مجاز برای کاربران بدون رمز:","send_broadcast":"پیام همگانی خود را بفرستید:","broadcast_done":"✅ به {} کاربر ارسال شد.","send_url":"آدرس Base URL را بفرستید:","url_detected":"دامنه: {}\nحالا کلید API (توکن) را بفرستید:","send_model":"توکن ذخیره شد.\nحالا نام دقیق مدل را بفرستید:","send_model_for_router":"نام دقیق مدل را برای افزودن به این روتر بفرستید:","router_added":"✅ روتر و مدل با موفقیت اضافه شدند!","router_details":"📌 **روتر:** {}\n🌐 آدرس: `{}`\n🔑 توکن: `{}`\n📦 **مدل‌ها:**\n{}","btn_add_mod":"➕ مدل","btn_del_mod":"🗑 حذف مدل","btn_del_router":"🗑 حذف روتر","del_confirm_msg":"⚠️ آیا از حذف این روتر مطمئن هستید؟","btn_yes":"✅ بله","btn_no":"❌ خیر","del_success":"✅ حذف شد.","pls_select_model":"لطفاً یک مدل معتبر انتخاب کنید.","invalid_command":"❌ دستور نامعتبر.","send_channel_prompt":"آیدی کانال را با @ بفرستید (یا none برای غیرفعال‌سازی):","channel_set":"✅ کانال‌های اجباری تنظیم شدند: `{}`","channel_none":"🔓 کانال اجباری غیرفعال شد.","must_join":"⛔ برای استفاده از ربات، باید در کانال‌های زیر عضو باشید:\n{channels}","btn_join_channel":"🔗 عضویت در کانال","btn_check_join":"🔄 بررسی عضویت","join_ok":"✅ عضویت در همه کانال‌ها تایید شد!","join_fail":"❌ شما هنوز در همه کانال‌ها عضو نشده‌اید!","send_del_model":"نام دقیق مدلی که می‌خواهید حذف کنید را بفرستید:","model_deleted":"✅ مدل با موفقیت حذف شد.","model_not_found":"❌ مدلی با این نام یافت نشد.","btn_user_mode":"👤 حالت کاربری","btn_clear_cache":"🧹 پاک‌سازی کش (فقط تاریخچه)","btn_clear_all":"🗑️ پاک‌سازی کامل دیتابیس","clear_cache_confirm":"🧹 این کار تمام تاریخچه چت را حذف می‌کند. ❓ مطمئن هستید؟","clear_cache_done":"✅ تاریخچه چت پاک شد.","clear_all_confirm":"🗑️ این کار تمام داده‌ها را حذف می‌کند. ❓ مطمئن هستید؟","clear_all_done":"✅ تمام داده‌ها پاک شدند.","clear_cancelled":"❌ عملیات لغو شد.","btn_admin_panel":"⚙️ پنل مدیریت","stats_text":"📊 **آمار ربات**\n👤 کاربران: `{users}`\n🤖 مدل‌ها: `{models}`\n🗂️ روترها: `{routers}`\n🔐 رمز عبور: `{pwd_status}`","btn_view_data":"📋 مشاهده داده‌ها","unknown_command":"❌ دستور ناشناس","model_added_continue":"✅ مدل اضافه شد. نام مدل بعدی را وارد کنید، یا دکمهٔ «پایان» را بزنید.","finish":"✅ پایان","add_router_done":"✅ روتر و مدل‌ها با موفقیت ثبت شدند.","loading_data":"⏳ در حال بارگذاری داده‌ها...","data_loaded":"✅ داده‌ها با موفقیت بارگذاری شدند.","contact_intro":"درخواست خود را برای مدیر بنویسید:","contact_confirm":"✅ پیام شما ارسال شد.","contact_button":"📞 تماس با مدیر"}
}

async def init_db():
    await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT, is_auth INTEGER DEFAULT 0, current_model_id INTEGER, msg_count INTEGER DEFAULT 0)")
    await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS routers (id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT, base_url TEXT, api_key TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS models (id INTEGER PRIMARY KEY AUTOINCREMENT, router_id INTEGER, model_name TEXT)")
    await db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT)")

async def get_text(user_id, key):
    row = await db.fetchone("SELECT lang FROM users WHERE user_id = ?", (user_id,))
    lang = row[0] if row and row[0] in LANGS else "en"
    return LANGS[lang].get(key, LANGS["en"].get(key, key))

async def check_channel_join(user_id):
    if user_id == ADMIN_ID: return True, None
    row = await db.fetchone("SELECT value FROM settings WHERE key = 'force_channel'")
    if not row or not row[0] or row[0].lower() == 'none': return True, None
    channels = [ch.strip() for ch in row[0].split(',') if ch.strip()]
    failed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ['left', 'kicked']: failed.append(ch)
        except: failed.append(ch)
    return (False, failed) if failed else (True, None)

chat_mode = {}

class BotStates(StatesGroup):
    waiting_for_password = State()
    admin_add_router_url = State()
    admin_add_router_key = State()
    admin_add_router_model = State()
    admin_add_model_only = State()
    admin_set_password = State()
    admin_broadcast = State()

def lang_keyboard():
    b = InlineKeyboardBuilder()
    for k, v in LANGS.items(): b.button(text=v["name"], callback_data=f"setlang_{k}")
    return b.adjust(2).as_markup()

async def admin_panel_keyboard(user_id):
    b = InlineKeyboardBuilder()
    b.button(text=await get_text(user_id, "btn_routers"), callback_data="admin_routers")
    b.button(text=await get_text(user_id, "btn_add_router"), callback_data="admin_add_router")
    b.button(text=await get_text(user_id, "btn_settings"), callback_data="admin_settings_menu")
    b.button(text=await get_text(user_id, "btn_user_mode"), callback_data="admin_switch_user")
    return b.adjust(2, 1, 1).as_markup()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    chat_mode[message.from_user.id] = False
    await db.execute("INSERT OR IGNORE INTO users (user_id, lang, msg_count) VALUES (?, ?, 0)", (message.from_user.id, "fa"))
    if message.from_user.id == ADMIN_ID:
        await message.answer(await get_text(message.from_user.id, "admin_menu"), reply_markup=await admin_panel_keyboard(message.from_user.id))
    else:
        joined, channels = await check_channel_join(message.from_user.id)
        if not joined:
            txt = await get_text(message.from_user.id, "must_join")
            await message.answer(txt.format(channels=", ".join(channels)))
            return
        await message.answer(await get_text(message.from_user.id, "welcome_first"))

@router.callback_query(F.data == "admin_add_router")
async def admin_add_router(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BotStates.admin_add_router_url)
    await callback.message.edit_text(await get_text(callback.from_user.id, "send_url"))

@router.message(BotStates.admin_add_router_url)
async def process_router_url(message: Message, state: FSMContext):
    url = message.text.strip()
    await state.update_data(base_url=url)
    await state.set_state(BotStates.admin_add_router_key)
    await message.answer(await get_text(message.from_user.id, "url_detected").format(urlparse(url).netloc))

@router.message(BotStates.admin_add_router_key)
async def process_router_key(message: Message, state: FSMContext):
    await state.update_data(api_key=message.text.strip())
    await state.set_state(BotStates.admin_add_router_model)
    await message.answer(await get_text(message.from_user.id, "send_model"))

@router.message(BotStates.admin_add_router_model)
async def process_router_model(message: Message, state: FSMContext):
    data = await state.get_data()
    model_name = message.text.strip()
    
    if "router_id" not in data:
        domain = urlparse(data["base_url"]).netloc
        res = await db.execute("INSERT INTO routers (domain, base_url, api_key) VALUES (?, ?, ?)", 
                         (domain, data["base_url"], data["api_key"]))
        router_id = res["lastrowid"]
        await state.update_data(router_id=router_id)
    else:
        router_id = data["router_id"]
        
    await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (router_id, model_name))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=await get_text(message.from_user.id, "finish"), callback_data="finishmod_")
    ]])
    await message.answer(await get_text(message.from_user.id, "model_added_continue"), reply_markup=kb)

@router.callback_query(F.data == "finishmod_")
async def finish_adding_models_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    admin_kb = await admin_panel_keyboard(callback.from_user.id)
    await callback.message.edit_text(await get_text(callback.from_user.id, "add_router_done"), reply_markup=admin_kb)

@router.callback_query(F.data == "admin_settings_menu")
async def admin_settings(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text=await get_text(callback.from_user.id, "btn_back_main"), callback_data="admin_back")
    await callback.message.edit_text(await get_text(callback.from_user.id, "title_settings"), reply_markup=b.as_markup())

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(await get_text(callback.from_user.id, "admin_menu"), reply_markup=await admin_panel_keyboard(callback.from_user.id))

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
