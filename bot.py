import os
import re
import json
import logging
import asyncio
import base64
import hashlib
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

# ================= Initial Setup =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)
DB_PATH = "bot_advanced.db"

# ================= Cloud/Local Database Manager =================
class DatabaseManager:
    def __init__(self):
        self.db_path = DB_PATH
        # Generic cloud environment variables
        self.cloud_account = os.getenv("CLOUD_ACCOUNT_ID")
        self.cloud_db_id = os.getenv("CLOUD_DB_ID")
        self.cloud_token = os.getenv("CLOUD_API_TOKEN")
        
        # Enable cloud mode if all variables are provided
        self.use_cloud = bool(self.cloud_account and self.cloud_db_id and self.cloud_token and self.cloud_token.strip())
        if self.use_cloud:
            logging.info("☁️ External Cloud Database Mode: ENABLED") 
        else:
            logging.info("💾 Local SQLite Mode: ENABLED")

    async def _cloud_request(self, query, params=()):
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.cloud_account}/d1/database/{self.cloud_db_id}/query"
        headers = {
            "Authorization": f"Bearer {self.cloud_token}",
            "Content-Type": "application/json"
        }
        payload = {"sql": query}
        if params:
            payload["params"] = list(params)
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=10) as resp:
                    data = await resp.json()
                    if data.get("success"):
                        return data["result"][0]
                    else:
                        logging.error(f"Cloud DB API Error: {data.get('errors')}")
                        return None
        except Exception as e:
            logging.error(f"Cloud Request Failed: {e}")
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

# Instantiate the database manager
db = DatabaseManager()

# ================= UI Elements & Emojis =================
AI_EMOJIS = ["🤖", "🧠", "⚡️", "🔮", "✨", "🚀", "💡", "📡", "🛠", "⚙️", "🔬", "💻", "💎", "🔥"]

def get_model_emoji(model_name: str) -> str:
    """Generates a consistent random emoji based on the model name hash."""
    idx = int(hashlib.md5(model_name.encode()).hexdigest(), 16) % len(AI_EMOJIS)
    return AI_EMOJIS[idx]

# ================= Language Dictionary =================
LANGS = {
    "en": {
        "name": "🇬🇧 English", "welcome_new": "Please select your preferred language:", "welcome_back": "Welcome back to the bot, {name}!",
        "locked": "⛔ Unauthorized access. Please enter the bot password:", "pwd_ok": "✅ Password accepted successfully!", "pwd_err": "❌ Incorrect password entered.",
        "pwd_none": "🔓 Password requirement removed. Bot is now public.", "pwd_set": "✅ New global password set to: `{}`",
        "exit": "🔙 Returning to the main model selection menu.", "admin_only": "❌ Access denied. Admins only.", "type_here": "Type your message here...",
        "select_model": "Please select an AI model to start chatting:", "no_models_admin": "⚠️ No AI models found. Send /admin to manage them.",
        "no_models_user": "⚠️ There are currently no AI models available.", "chat_started": "✅ Connected to {}. Send your message to begin:",
        "invalid_url": "❌ Invalid URL format detected. Please send a valid Base URL (http/https):",
        "admin_menu": "⚙️ Technical Admin Panel. Please use the menu below:", "btn_routers": "🗂 List of Available APIs", "btn_add_router": "➕ Add New Router",
        "btn_settings": "⚙️ Bot Technical Settings", "btn_set_pwd": "🔐 Set Global Password", "btn_set_channel": "📢 Set Force Join Channel", "btn_broadcast": "📢 Send Broadcast Message", 
        "btn_back": "🔙 Go Back to Previous", "btn_back_main": "🏠 Return to Main Menu", "send_pwd_prompt": "Please send the new password (or type 'none' to make it public):",
        "send_broadcast": "Please send your broadcast message text:", "broadcast_done": "✅ Broadcast message successfully sent to {} users.",
        "send_url": "🌐 Please send the exact Base URL (e.g., https://api.openai.com/v1):", "url_detected": "Detected Domain: {}\nPlease send the API Key (Token) now:",
        "send_model": "API Key saved successfully.\nNow, please send the exact Model Name:", "router_added": "✅ Router and Model have been added successfully!",
        "router_details": "📌 **Router Domain:** {}\n🌐 Base URL: `{}`\n🔑 Token: `{}`\n\n📦 **Assigned Models:**",
        "btn_add_mod": "➕ Add Another Model", "btn_del_mod": "🗑 Delete a Model", "btn_del_router": "🗑 Delete Entire Router", 
        "del_confirm_msg": "⚠️ Are you absolutely sure you want to delete this router and all its models?",
        "btn_yes": "✅ Yes, Delete it", "btn_no": "❌ No, Cancel action", "del_success": "✅ Successfully deleted from database.", "pls_select_model": "Please select a valid AI model from the list below.",
        "invalid_command": "❌ Unrecognized command. Please use the available logic.", "send_channel_prompt": "Send the channel username (e.g., @MyChannel) or type 'none' to disable:",
        "channel_set": "✅ Force join channel has been set to: `{}`", "channel_none": "🔓 Force join requirement has been disabled.",
        "must_join": "⛔ You must join our official channel to use this bot:", "btn_join_channel": "🔗 Join Official Channel",
        "btn_check_join": "🔄 Check My Membership", "join_ok": "✅ Membership verified! You can now use the services.", "join_fail": "❌ You haven't joined the channel yet!",
        "send_del_model": "Please send the exact name of the model you wish to delete:",
        "model_deleted": "✅ The model was deleted successfully.", "model_not_found": "❌ Model not found in the database.",
        "btn_user_mode": "👤 Switch to User Mode", "btn_clear_cloud": "☁️ Clear Cloud Database Cache", 
        "clear_cloud_confirm": "⚠️ Are you sure you want to clear the entire chat history cache from the external cloud database?",
        "btn_yes_clear": "✅ Yes, Clear Cache", "btn_no_cancel": "❌ No, Cancel", "cloud_cleared": "✅ Cloud database cache cleared successfully."
    },
    "fa": {
        "name": "🇮🇷 فارسی", "welcome_new": "لطفاً زبان مورد نظر خود را انتخاب کنید:", "welcome_back": "خوش برگشتی کاربر عزیز، {name}!",
        "locked": "⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور ربات را وارد کنید:", "pwd_ok": "✅ رمز عبور با موفقیت تایید شد!", "pwd_err": "❌ رمز عبور وارد شده اشتباه است.",
        "pwd_none": "🔓 قفل ربات برداشته شد. استفاده برای تمامی کاربران آزاد است.", "pwd_set": "✅ رمز عبور جدید ربات تنظیم شد: `{}`",
        "exit": "🔙 در حال بازگشت به منوی انتخاب مدل‌ها.", "admin_only": "❌ دسترسی غیرمجاز. این بخش فقط برای مدیریت است.", "type_here": "پیام خود را اینجا بنویسید...",
        "select_model": "جهت شروع گفتگو، لطفاً یک مدل هوش مصنوعی را انتخاب کنید:", "no_models_admin": "⚠️ هیچ مدل هوش مصنوعی یافت نشد. برای مدیریت /admin را ارسال کنید.",
        "no_models_user": "⚠️ در حال حاضر هیچ مدل هوش مصنوعی در دسترس نمی‌باشد.", "chat_started": "✅ با موفقیت به مدل {} متصل شدید. پیام خود را جهت شروع گفتگو بفرستید:",
        "invalid_url": "❌ فرمت لینک ارسال شده اشتباه است. لطفاً یک آدرس اینترنتی (URL) معتبر بفرستید:",
        "admin_menu": "⚙️ پنل تنظیمات فنی ربات، لطفاً از منوی زیر انتخاب کنید:", "btn_routers": "🗂 لیست API های موجود در ربات :", "btn_add_router": "➕ افزودن روتر جدید",
        "btn_settings": "⚙️ تنظیمات فنی ربات", "btn_set_pwd": "🔐 تنظیم رمز عبور ربات", "btn_set_channel": "📢 تنظیم کانال اجباری", "btn_broadcast": "📢 ارسال پیام همگانی", 
        "btn_back": "🔙 بازگشت به منوی قبل", "btn_back_main": "🏠 بازگشت به منوی اصلی", "send_pwd_prompt": "رمز عبور جدید را ارسال کنید (یا عبارت none را برای آزادسازی بفرستید):",
        "send_broadcast": "متن پیام همگانی خود را جهت ارسال بنویسید:", "broadcast_done": "✅ پیام شما با موفقیت به {} کاربر ارسال گردید.",
        "send_url": "🌐 آدرس Base URL را دقیق بفرستید:", "url_detected": "دامنه شناسایی شده: {}\nحالا لطفاً کلید API (توکن) را بفرستید:",
        "send_model": "توکن با موفقیت ذخیره شد.\nحالا نام دقیق مدل هوش مصنوعی را بفرستید:", "router_added": "✅ روتر و مدل جدید با موفقیت به ربات اضافه شدند!",
        "router_details": "📌 **دامنه روتر:** {}\n🌐 آدرس متصل: `{}`\n🔑 توکن اختصاصی: `{}`\n\n📦 **مدل‌های متصل شده:**",
        "btn_add_mod": "➕ افزودن مدل جدید", "btn_del_mod": "🗑 حذف کردن مدل", "btn_del_router": "🗑 حذف کامل این روتر", 
        "del_confirm_msg": "⚠️ آیا از حذف کامل این روتر و تمام مدل‌های آن اطمینان کامل دارید؟",
        "btn_yes": "✅ بله، کاملا مطمئنم", "btn_no": "❌ خیر، انصراف می‌دهم", "del_success": "✅ اطلاعات با موفقیت از سیستم حذف گردید.", "pls_select_model": "لطفاً یک مدل معتبر از لیست زیر انتخاب کنید.",
        "invalid_command": "❌ دستور وارد شده نامعتبر است. لطفاً از گزینه‌های موجود استفاده کنید.", "send_channel_prompt": "آیدی کانال را همراه با @ بفرستید (یا عبارت none را برای غیرفعال‌سازی بفرستید):",
        "channel_set": "✅ قفل کانال اجباری با موفقیت تنظیم شد: `{}`", "channel_none": "🔓 سیستم قفل کانال اجباری غیرفعال گردید.",
        "must_join": "⛔ کاربر گرامی، برای استفاده از ربات حتماً باید در کانال ما عضو باشید:", "btn_join_channel": "🔗 عضویت در کانال رسمی",
        "btn_check_join": "🔄 بررسی وضعیت عضویت من", "join_ok": "✅ عضویت شما تایید شد! حالا می‌توانید از ربات استفاده کنید.", "join_fail": "❌ شما هنوز در کانال اسپانسر عضو نشده‌اید!",
        "send_del_model": "لطفاً نام دقیق مدلی که قصد حذف آن را دارید بفرستید:",
        "model_deleted": "✅ مدل مورد نظر با موفقیت حذف گردید.", "model_not_found": "❌ مدلی با این نام در دیتابیس یافت نشد.",
        "btn_user_mode": "👤 ورود به حالت کاربری", "btn_clear_cloud": "☁️ پاکسازی کش دیتابیس ابری", 
        "clear_cloud_confirm": "⚠️ آیا از پاکسازی کامل حافظه کش (تاریخچه چت‌ها) در دیتابیس ابری اطمینان کامل دارید؟",
        "btn_yes_clear": "✅ بله، حافظه پاک شود", "btn_no_cancel": "❌ خیر، انصراف می‌دهم", "cloud_cleared": "✅ حافظه کش دیتابیس خارجی با موفقیت خالی شد."
    }
}

# Add fallback languages simply mapping to English for missing keys in other langs (if any)
for lang_code in ["ru", "ar", "hi", "tr", "fr", "de", "zh"]:
    if lang_code not in LANGS:
        LANGS[lang_code] = LANGS["en"]

# ================= Database Initialization =================
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
    lang = row[0] if row and row[0] in LANGS else "fa" # Default to FA based on user's preference
    return LANGS[lang].get(key, LANGS["en"].get(key, key))

async def check_auth(user_id):
    if user_id == ADMIN_ID: return True
    pwd_row = await db.fetchone("SELECT value FROM settings WHERE key = 'global_password'")
    if not pwd_row or not pwd_row[0] or pwd_row[0].lower() == 'none': return True
    auth_row = await db.fetchone("SELECT is_auth FROM users WHERE user_id = ?", (user_id,))
    return bool(auth_row and auth_row[0] == 1)

async def check_channel_join(user_id):
    if user_id == ADMIN_ID: return True, None
    row = await db.fetchone("SELECT value FROM settings WHERE key = 'force_channel'")
    if not row or not row[0] or row[0].lower() == 'none':
        return True, None
    channel = row[0]
            
    try:
        member = await bot.get_chat_member(channel, user_id)
        if member.status in ['left', 'kicked']:
            return False, channel
        return True, None
    except Exception:
        return False, channel

# ================= State Machine =================
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

# ================= Keyboards =================
def lang_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🇮🇷 فارسی", callback_data="setlang_fa")
    builder.button(text="🇬🇧 English", callback_data="setlang_en")
    builder.adjust(2)
    return builder.as_markup()

async def admin_panel_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_routers"), callback_data="admin_routers")
    builder.button(text=await get_text(user_id, "btn_add_router"), callback_data="admin_add_router")
    builder.button(text=await get_text(user_id, "btn_settings"), callback_data="admin_settings_menu")
    builder.button(text=await get_text(user_id, "btn_user_mode"), callback_data="admin_to_user")
    builder.adjust(2, 1, 1)
    return builder.as_markup()

async def admin_settings_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_set_pwd"), callback_data="admin_pwd")
    builder.button(text=await get_text(user_id, "btn_set_channel"), callback_data="admin_channel")
    builder.button(text=await get_text(user_id, "btn_broadcast"), callback_data="admin_broadcast")
    builder.button(text=await get_text(user_id, "btn_clear_cloud"), callback_data="admin_clear_cloud")
    builder.button(text=await get_text(user_id, "btn_back_main"), callback_data="admin_back")
    builder.adjust(2, 1, 1, 1)
    return builder.as_markup()

def cancel_admin_keyboard(user_id, text_back):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text_back, callback_data="admin_back")]])

# ================= Handlers: Start and Language =================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_exists = await db.fetchone("SELECT lang FROM users WHERE user_id = ?", (message.from_user.id,))
            
    if not user_exists:
        await db.execute("INSERT OR IGNORE INTO users (user_id, lang) VALUES (?, ?)", (message.from_user.id, "fa"))
        await message.answer("لطفاً زبان مورد نظر خود را انتخاب کنید:\n\nPlease select your preferred language:", reply_markup=lang_keyboard())
    else:
        welcome_txt = await get_text(message.from_user.id, "welcome_back")
        await message.answer(welcome_txt.format(name=message.from_user.first_name))
        await show_user_panel(message, message.from_user.id)

@router.message(Command("lang"))
@router.message(F.text.lower().in_({"lang", "/lang"}))
async def cmd_lang(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("لطفاً زبان خود را انتخاب کنید:\n\nPlease select your language:", reply_markup=lang_keyboard())

@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    await db.execute("""
        INSERT INTO users (user_id, lang) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang
    """, (callback.from_user.id, lang))
    
    await callback.message.delete()
    await show_user_panel(callback.message, callback.from_user.id)

# ================= Handlers: User Panel & Pagination =================
@router.message(Command("user"))
@router.message(F.text.lower().in_({"user", "/user"}))
async def cmd_user(message: Message, state: FSMContext):
    await state.clear()
    await show_user_panel(message, message.from_user.id)

@router.callback_query(F.data == "admin_to_user")
async def switch_admin_to_user(callback: CallbackQuery):
    await callback.message.delete()
    await show_user_panel(callback.message, callback.from_user.id)

@router.callback_query(F.data == "check_join_channel")
async def check_join_callback(callback: CallbackQuery):
    joined, channel = await check_channel_join(callback.from_user.id)
    if joined:
        ok_txt = await get_text(callback.from_user.id, "join_ok")
        await callback.answer(ok_txt, show_alert=True)
        await callback.message.delete()
        await show_user_panel(callback.message, callback.from_user.id)
    else:
        fail_txt = await get_text(callback.from_user.id, "join_fail")
        await callback.answer(fail_txt, show_alert=True)

@router.callback_query(F.data.startswith("userpage_"))
async def handle_user_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    await show_user_panel(callback.message, callback.from_user.id, page=page, edit=True)

async def show_user_panel(message, user_id, page=0, edit=False):
    joined, channel = await check_channel_join(user_id)
    if not joined:
        txt = await get_text(user_id, "must_join")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=await get_text(user_id, "btn_join_channel"), url=f"https://t.me/{channel.replace('@', '')}")],
            [InlineKeyboardButton(text=await get_text(user_id, "btn_check_join"), callback_data="check_join_channel")]
        ])
        if edit and isinstance(message, Message):
            await message.edit_text(f"{txt}\n{channel}", reply_markup=kb)
        else:
            await message.answer(f"{txt}\n{channel}", reply_markup=kb)
        return

    models = await db.fetchall("SELECT id, model_name FROM models")
            
    if not models:
        txt = await get_text(user_id, "no_models_admin" if user_id == ADMIN_ID else "no_models_user")
        if edit:
            await message.edit_text(txt)
        else:
            await message.answer(txt)
        return

    # Pagination logic (12 per page, 2 per row)
    ITEMS_PER_PAGE = 12
    total_pages = (len(models) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    current_models = models[page * ITEMS_PER_PAGE : (page + 1) * ITEMS_PER_PAGE]

    builder = InlineKeyboardBuilder()
    for m_id, m_name in current_models:
        emoji = get_model_emoji(m_name)
        builder.button(text=f"{emoji} {m_name}", callback_data=f"selmod_{m_id}")
    
    builder.adjust(2) # 2 columns

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"userpage_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"userpage_{page+1}"))
    
    if nav_buttons:
        builder.row(*nav_buttons)

    kb = builder.as_markup()
    select_text = await get_text(user_id, "select_model")
    
    if edit:
        await message.edit_text(select_text, reply_markup=kb)
    else:
        await message.answer(select_text, reply_markup=kb)

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

    # Update state and silently clear history
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
    exit_text = await get_text(message.from_user.id, "exit")
    await message.answer(exit_text)
    await show_user_panel(message, message.from_user.id)

# ================= Handlers: Admin =================
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

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    admin_text = await get_text(callback.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)

@router.callback_query(F.data == "admin_settings_menu")
async def admin_settings_menu(callback: CallbackQuery):
    admin_text = await get_text(callback.from_user.id, "btn_settings")
    kb = await admin_settings_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)

# Admin: Clear Cloud Cache
@router.callback_query(F.data == "admin_clear_cloud")
async def admin_clear_cloud_prompt(callback: CallbackQuery):
    msg = await get_text(callback.from_user.id, "clear_cloud_confirm")
    btn_yes = await get_text(callback.from_user.id, "btn_yes_clear")
    btn_no = await get_text(callback.from_user.id, "btn_no_cancel")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_yes, callback_data="confirm_clear_cloud")],
        [InlineKeyboardButton(text=btn_no, callback_data="admin_settings_menu")]
    ])
    await callback.message.edit_text(msg, reply_markup=kb)

@router.callback_query(F.data == "confirm_clear_cloud")
async def admin_clear_cloud_confirm(callback: CallbackQuery):
    await db.execute("DELETE FROM history") # Clear cache entirely
    msg = await get_text(callback.from_user.id, "cloud_cleared")
    await callback.answer(msg, show_alert=True)
    await admin_settings_menu(callback) # Return to settings

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
        if not new_channel.startswith("@"):
            new_channel = "@" + new_channel
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_channel', ?)", (new_channel,))
        res_txt = await get_text(message.from_user.id, "channel_set")
        res_txt = res_txt.format(new_channel)
        
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
    res = await db.execute("INSERT INTO routers (domain, base_url, api_key) VALUES (?, ?, ?)", (data['domain'], data['base_url'], data['api_key']))
    r_id = res['lastrowid']
    await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (r_id, message.text.strip()))
        
    txt = await get_text(message.from_user.id, "router_added")
    await message.answer(txt)
    await state.clear()
    await cmd_admin(message, state)

@router.callback_query(F.data == "admin_routers")
async def admin_routers_list(callback: CallbackQuery):
    buttons = []
    routers = await db.fetchall("SELECT id, domain FROM routers")
    for r_id, domain in routers:
        buttons.append([InlineKeyboardButton(text=domain, callback_data=f"router_{r_id}")])
                
    btn_back = await get_text(callback.from_user.id, "btn_back_main")
    buttons.append([InlineKeyboardButton(text=btn_back, callback_data="admin_back")])
    
    txt = await get_text(callback.from_user.id, "btn_routers")
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("router_"))
async def admin_router_details(callback: CallbackQuery):
    r_id = callback.data.split("_")[1]
    r = await db.fetchone("SELECT domain, base_url, api_key FROM routers WHERE id = ?", (r_id,))
    models = await db.fetchall("SELECT id, model_name FROM models WHERE router_id = ?", (r_id,))

    if not r: return
    
    txt_template = await get_text(callback.from_user.id, "router_details")
    msg = txt_template.format(r[0], r[1], r[2]) + "\n"
    
    # Show models in monospace with emoji for easy copying
    for _, m_name in models:
        emoji = get_model_emoji(m_name)
        msg += f"- {emoji} `{m_name}`\n"
        
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
    txt = await get_text(callback.from_user.id, "send_model")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    
    buttons = [[InlineKeyboardButton(text=btn_back, callback_data=f"router_{r_id}")]]
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(BotStates.admin_add_model_only)

@router.message(BotStates.admin_add_model_only)
async def admin_save_model_only(message: Message, state: FSMContext):
    data = await state.get_data()
    await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (data['r_id'], message.text.strip()))
        
    txt = await get_text(message.from_user.id, "router_added")
    await message.answer(txt)
    await state.clear()
    await cmd_admin(message, state)

# ================= Chat Flow & Message Processor =================
@router.message()
async def process_user_chat(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    joined, channel = await check_channel_join(user_id)
    if not joined:
        txt = await get_text(user_id, "must_join")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=await get_text(user_id, "btn_join_channel"), url=f"https://t.me/{channel.replace('@', '')}")],
            [InlineKeyboardButton(text=await get_text(user_id, "btn_check_join"), callback_data="check_join_channel")]
        ])
        await message.answer(f"{txt}\n{channel}", reply_markup=kb)
        return

    active_model = await db.fetchone("""
        SELECT m.model_name, r.base_url, r.api_key 
        FROM users u
        JOIN models m ON u.current_model_id = m.id
        JOIN routers r ON m.router_id = r.id
        WHERE u.user_id = ?
    """, (user_id,))

    if not active_model:
        models = await db.fetchall("SELECT id, model_name FROM models")
                
        if not models:
            txt = await get_text(user_id, "invalid_command")
            return await message.answer(txt)
            
        invalid_txt = await get_text(user_id, "invalid_command")
        select_txt = await get_text(user_id, "pls_select_model")
        
        # Present user panel again if they send text without active model
        await message.answer(f"{invalid_txt}\n\n{select_txt}")
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
                        reply_text = f"❌ API Error: {resp_data.get('error', {}).get('message', 'Unknown Error')}"
        except Exception as e:
            reply_text = f"❌ Server connection failed. Detail: {e}"
            
    if len(reply_text) > 4000:
        text_file = BufferedInputFile(reply_text.encode('utf-8'), filename="response.txt")
        await message.answer_document(text_file, caption="📄 The response was too long, so it's sent as a file.")
    else:
        await message.answer(reply_text)
    
    await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "assistant", reply_text[:2000] if len(reply_text) > 2000 else reply_text))

# ================= Bot Execution =================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
