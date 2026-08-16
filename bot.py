import os
import re
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

# ================= تنظیمات اولیه =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)
DB_PATH = "bot_advanced.db"

# ================= دیکشنری زبان‌ها (گسترده) =================
LANGS = {
    "en": {
        "name": "🇬🇧 English", "welcome_new": "Please select your language:", "welcome_back": "Welcome back! {name}",
        "locked": "⛔ Unauthorized. Enter password:", "pwd_ok": "✅ Password accepted!", "pwd_err": "❌ Wrong password.",
        "pwd_none": "🔓 Password requirement removed. Bot is public.", "pwd_set": "✅ New password set: `{}`",
        "exit": "🧹 Chat history cleared.", "admin_only": "❌ Admin only.", "type_here": "Type your message...",
        "select_model": "Select a model to start:", "no_models_admin": "⚠️ No models found. Send /admin to add one.",
        "no_models_user": "⚠️ No AI models are currently available.", "chat_started": "✅ Connected to {}. Send your message:\n(Send /exit to quit)",
        "invalid_url": "❌ Invalid URL format. Please send a valid Base URL (http/https):",
        "admin_menu": "⚙️ Advanced Admin Panel:", "btn_routers": "🗂 API List", "btn_add_router": "➕ Add Router",
        "btn_set_pwd": "🔐 Set Password", "btn_broadcast": "📢 Broadcast", "btn_back": "🔙 Back",
        "btn_back_main": "🏠 Main Menu", "send_pwd_prompt": "Send new password (send 'none' to make bot public):",
        "send_broadcast": "Send your broadcast message:", "broadcast_done": "✅ Sent to {} users.",
        "send_url": "Send the Base URL (e.g., https://api.openai.com/v1):", "url_detected": "Domain: {}\nNow send the API Key (Token):",
        "send_model": "API Key saved.\nNow send the exact Model Name (e.g., gpt-4o):", "router_added": "✅ Router and Model added successfully!",
        "router_details": "📌 **Router:** {}\n🌐 Base URL: `{}`\n🔑 Token: `{}`\n\n📦 **Models:**",
        "btn_add_mod": "➕ Add Model", "btn_del_router": "🗑 Delete Router", "del_confirm_msg": "⚠️ Are you sure you want to delete this router and its models?",
        "btn_yes": "✅ Yes, Delete", "btn_no": "❌ No, Cancel", "del_success": "✅ Router deleted."
    },
    "fa": {
        "name": "🇮🇷 فارسی", "welcome_new": "لطفاً زبان خود را انتخاب کنید:", "welcome_back": "خوش برگشتی! {name}",
        "locked": "⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور را بفرستید:", "pwd_ok": "✅ رمز عبور تایید شد!", "pwd_err": "❌ رمز اشتباه است.",
        "pwd_none": "🔓 قفل ربات برداشته شد. اکنون استفاده برای همه آزاد است.", "pwd_set": "✅ رمز عبور جدید تنظیم شد: `{}`\nدسترسی کاربران قفل شد.",
        "exit": "🧹 تاریخچه مکالمه شما پاک شد.", "admin_only": "❌ دسترسی فقط برای مدیریت.", "type_here": "پیام خود را بنویسید...",
        "select_model": "مدل هوش مصنوعی را انتخاب کنید:", "no_models_admin": "⚠️ هیچ مدلی وجود ندارد. با ارسال /admin مدل اضافه کنید.",
        "no_models_user": "⚠️ در حال حاضر هیچ مدلی در دسترس نیست.", "chat_started": "✅ شما به {} متصل شدید. مکالمه را شروع کنید:\n(برای خروج /exit را بفرستید)",
        "invalid_url": "❌ فرمت لینک اشتباه است. لطفاً یک URL معتبر (با http یا https) بفرستید:",
        "admin_menu": "⚙️ پنل مدیریت پیشرفته:", "btn_routers": "🗂 لیست APIها", "btn_add_router": "➕ افزودن روتر",
        "btn_set_pwd": "🔐 تنظیم رمز عبور", "btn_broadcast": "📢 پیام همگانی", "btn_back": "🔙 بازگشت",
        "btn_back_main": "🏠 منوی اصلی", "send_pwd_prompt": "رمز جدید را بفرستید (برای آزاد شدن ربات کلمه none را بفرستید):",
        "send_broadcast": "پیام خود را برای ارسال همگانی بفرستید:", "broadcast_done": "✅ به {} کاربر ارسال شد.",
        "send_url": "آدرس Base URL را بفرستید (مثال: https://api.openai.com/v1):", "url_detected": "سایت: {}\nحالا کلید API (توکن) را بفرستید:",
        "send_model": "توکن ذخیره شد.\nحالا نام دقیق مدل را بفرستید (مثال: gpt-4o):", "router_added": "✅ روتر و مدل با موفقیت اضافه شدند!",
        "router_details": "📌 **روتر:** {}\n🌐 آدرس: `{}`\n🔑 توکن: `{}`\n\n📦 **مدل‌ها:**",
        "btn_add_mod": "➕ افزودن مدل", "btn_del_router": "🗑 حذف روتر", "del_confirm_msg": "⚠️ آیا از حذف این روتر و مدل‌های آن کاملاً مطمئن هستید؟",
        "btn_yes": "✅ بله، حذف کن", "btn_no": "❌ خیر، لغو", "del_success": "✅ روتر حذف شد."
    }
}

# (زبان‌های دیگر را برای جلوگیری از طولانی شدن کد به صورت پیش‌فرض کپی انگلیسی می‌کنیم تا ساختار حفظ شود)
for lang_code in ["ru", "ar", "hi", "tr", "fr", "de", "zh"]:
    LANGS[lang_code] = dict(LANGS["en"])
    LANGS[lang_code]["name"] = {"ru": "🇷🇺 Русский", "ar": "🇸🇦 العربية", "hi": "🇮🇳 हिन्दी", "tr": "🇹🇷 Türkçe", "fr": "🇫🇷 Français", "de": "🇩🇪 Deutsch", "zh": "🇨🇳 中文"}[lang_code]

# ================= دیتابیس =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT, is_auth INTEGER DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS routers (id INTEGER PRIMARY KEY, domain TEXT, base_url TEXT, api_key TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS models (id INTEGER PRIMARY KEY, router_id INTEGER, model_name TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT)")
        await db.commit()

async def get_text(user_id, key):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            lang = row[0] if row else "en"
            return LANGS.get(lang, LANGS["en"]).get(key, key)

async def check_auth(user_id):
    if user_id == ADMIN_ID: return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'global_password'") as cursor:
            pwd_row = await cursor.fetchone()
            if not pwd_row or not pwd_row[0] or pwd_row[0].lower() == 'none': return True
        async with db.execute("SELECT is_auth FROM users WHERE user_id = ?", (user_id,)) as cursor:
            auth_row = await cursor.fetchone()
            return bool(auth_row and auth_row[0] == 1)

# ================= ماشین وضعیت =================
class BotStates(StatesGroup):
    waiting_for_password = State()
    chatting = State()
    admin_add_router_url = State()
    admin_add_router_key = State()
    admin_add_router_model = State()
    admin_add_model_only = State()
    admin_set_password = State()
    admin_broadcast = State()

# ================= کیبوردها =================
def lang_keyboard():
    builder = InlineKeyboardBuilder()
    for k, v in LANGS.items():
        builder.button(text=v["name"], callback_data=f"setlang_{k}")
    builder.adjust(2) # چیدمان 2 در 2
    return builder.as_markup()

async def admin_panel_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_routers"), callback_data="admin_routers")
    builder.button(text=await get_text(user_id, "btn_add_router"), callback_data="admin_add_router")
    builder.button(text=await get_text(user_id, "btn_set_pwd"), callback_data="admin_pwd")
    builder.button(text=await get_text(user_id, "btn_broadcast"), callback_data="admin_broadcast")
    builder.adjust(1)
    return builder.as_markup()

def cancel_admin_keyboard(user_id, text_back):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text_back, callback_data="admin_back")]])

# ================= هندلرهای زبان و شروع =================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (message.from_user.id,)) as cursor:
            user_exists = await cursor.fetchone()
            
    if not user_exists:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id, lang) VALUES (?, ?)", (message.from_user.id, "en"))
            await db.commit()
        await message.answer("Please select your language / لطفاً زبان خود را انتخاب کنید:", reply_markup=lang_keyboard())
    else:
        welcome_txt = await get_text(message.from_user.id, "welcome_back")
        await message.answer(welcome_txt.format(name=message.from_user.first_name))
        await show_user_panel(message, message.from_user.id)

@router.message(Command("lang"))
@router.message(F.text.in_({"lang", "/lang"}))
async def cmd_lang(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Please select your language / لطفاً زبان خود را انتخاب کنید:", reply_markup=lang_keyboard())

@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, callback.from_user.id))
        await db.commit()
    
    await callback.message.delete()
    await show_user_panel(callback.message, callback.from_user.id)

# ================= هندلرهای کاربری =================
@router.message(Command("user"))
@router.message(F.text.in_({"user", "/user"}))
async def cmd_user(message: Message, state: FSMContext):
    await state.clear()
    await show_user_panel(message, message.from_user.id)

async def show_user_panel(message, user_id):
    buttons = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, model_name FROM models") as cursor:
            models = await cursor.fetchall()
            
    if not models:
        txt = await get_text(user_id, "no_models_admin" if user_id == ADMIN_ID else "no_models_user")
        if isinstance(message, Message):
            await message.answer(txt)
        return

    for m_id, m_name in models:
        buttons.append([InlineKeyboardButton(text=m_name, callback_data=f"selectmodel_{m_id}_{m_name}")])
        
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    select_text = await get_text(user_id, "select_model")
    
    if isinstance(message, Message):
        await message.answer(select_text, reply_markup=kb)
    else: # If called from callback query
        await message.answer(select_text, reply_markup=kb)

@router.callback_query(F.data.startswith("selectmodel_"))
async def select_model(callback: CallbackQuery, state: FSMContext):
    model_id = callback.data.split("_")[1]
    model_name = callback.data.split("_")[2]
    
    is_authorized = await check_auth(callback.from_user.id)
    if not is_authorized:
        locked_text = await get_text(callback.from_user.id, "locked")
        await callback.answer(locked_text, show_alert=True)
        await callback.message.answer(locked_text)
        await state.set_state(BotStates.waiting_for_password)
        return

    await state.update_data(current_model_id=model_id, current_model_name=model_name)
    await state.set_state(BotStates.chatting)
    chat_start_txt = await get_text(callback.from_user.id, "chat_started")
    await callback.message.edit_text(chat_start_txt.format(model_name))

@router.message(BotStates.waiting_for_password)
async def check_password_input(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'global_password'") as cursor:
            pwd_row = await cursor.fetchone()
            global_pwd = pwd_row[0] if pwd_row else ""
            
    if message.text == global_pwd or global_pwd.lower() == 'none':
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_auth = 1 WHERE user_id = ?", (message.from_user.id,))
            await db.commit()
        success_text = await get_text(message.from_user.id, "pwd_ok")
        await message.answer(success_text)
        await state.clear()
        await show_user_panel(message, message.from_user.id)
    else:
        err_text = await get_text(message.from_user.id, "pwd_err")
        await message.answer(err_text)

@router.message(Command("exit"))
@router.message(F.text.in_({"exit", "/exit"}))
async def cmd_exit(message: Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM history WHERE user_id = ?", (message.from_user.id,))
        await db.commit()
    exit_text = await get_text(message.from_user.id, "exit")
    await message.answer(exit_text)
    await show_user_panel(message, message.from_user.id)

# ================= هندلرهای مدیریت =================
@router.message(Command("admin"))
@router.message(F.text.in_({"admin", "/admin"}))
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

# --- مدیریت رمز عبور ---
@router.callback_query(F.data == "admin_pwd")
async def admin_pwd_start(callback: CallbackQuery, state: FSMContext):
    txt = await get_text(callback.from_user.id, "send_pwd_prompt")
    btn_back = await get_text(callback.from_user.id, "btn_back_main")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_set_password)

@router.message(BotStates.admin_set_password)
async def admin_pwd_save(message: Message, state: FSMContext):
    new_pwd = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        if new_pwd.lower() == 'none':
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_password', 'none')")
            await db.execute("UPDATE users SET is_auth = 1")
            res_txt = await get_text(message.from_user.id, "pwd_none")
        else:
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_password', ?)", (new_pwd,))
            await db.execute("UPDATE users SET is_auth = 0")
            res_txt = await get_text(message.from_user.id, "pwd_set")
            res_txt = res_txt.format(new_pwd)
        await db.commit()
        
    await message.answer(res_txt)
    await state.clear()
    await cmd_admin(message, state)

# --- مدیریت روترها (طراحی جدید) ---
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
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO routers (domain, base_url, api_key) VALUES (?, ?, ?)", (data['domain'], data['base_url'], data['api_key']))
        r_id = cursor.lastrowid
        await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (r_id, message.text.strip()))
        await db.commit()
        
    txt = await get_text(message.from_user.id, "router_added")
    await message.answer(txt)
    await state.clear()
    await cmd_admin(message, state)

@router.callback_query(F.data == "admin_routers")
async def admin_routers_list(callback: CallbackQuery):
    buttons = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, domain FROM routers") as cursor:
            for r_id, domain in await cursor.fetchall():
                buttons.append([InlineKeyboardButton(text=domain, callback_data=f"router_{r_id}")])
                
    btn_back = await get_text(callback.from_user.id, "btn_back_main")
    buttons.append([InlineKeyboardButton(text=btn_back, callback_data="admin_back")])
    
    txt = await get_text(callback.from_user.id, "btn_routers")
    await callback.message.edit_text(txt + ":", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("router_"))
async def admin_router_details(callback: CallbackQuery):
    r_id = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT domain, base_url, api_key FROM routers WHERE id = ?", (r_id,)) as cursor:
            r = await cursor.fetchone()
        async with db.execute("SELECT id, model_name FROM models WHERE router_id = ?", (r_id,)) as cursor:
            models = await cursor.fetchall()

    if not r: return
    
    txt_template = await get_text(callback.from_user.id, "router_details")
    msg = txt_template.format(r[0], r[1], r[2]) + "\n"
    for _, m_name in models:
        msg += f"- {m_name}\n"
        
    btn_add = await get_text(callback.from_user.id, "btn_add_mod")
    btn_del = await get_text(callback.from_user.id, "btn_del_router")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    
    buttons = [
        [InlineKeyboardButton(text=btn_add, callback_data=f"addmod_{r_id}")],
        [InlineKeyboardButton(text=btn_del, callback_data=f"askdel_{r_id}")],
        [InlineKeyboardButton(text=btn_back, callback_data="admin_routers")]
    ]
    await callback.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

# --- تاییدیه حذف روتر ---
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM routers WHERE id = ?", (r_id,))
        await db.execute("DELETE FROM models WHERE router_id = ?", (r_id,))
        await db.commit()
        
    msg = await get_text(callback.from_user.id, "del_success")
    await callback.answer(msg, show_alert=True)
    await admin_routers_list(callback)

# --- افزودن مدل تکی به روتر موجود ---
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (data['r_id'], message.text.strip()))
        await db.commit()
        
    txt = await get_text(message.from_user.id, "router_added")
    await message.answer(txt)
    await state.clear()
    await cmd_admin(message, state)

# ================= چت و ارتباط با API =================
async def typing_action_task(chat_id):
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass

@router.message(BotStates.chatting & F.text)
async def handle_chat(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    m_id = data.get("current_model_id")
    m_name = data.get("current_model_name")
    
    if not m_id: return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT router_id FROM models WHERE id = ?", (m_id,)) as cursor:
            r_row = await cursor.fetchone()
            if not r_row: return
        async with db.execute("SELECT base_url, api_key FROM routers WHERE id = ?", (r_row[0],)) as cursor:
            r_info = await cursor.fetchone()
            
    url = r_info[0].strip().rstrip('/')
    key = r_info[1].strip()
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "user", message.text))
        await db.commit()
        async with db.execute("SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            messages = [{"role": r[0], "content": r[1]} for r in reversed(rows)]
            
    # روشن کردن تایپینگ در حین پردازش
    typing_task = asyncio.create_task(typing_action_task(message.chat.id))

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": m_name, "messages": messages}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
                resp_data = await resp.json(content_type=None)
                if resp.status == 200 and 'choices' in resp_data:
                    reply_text = resp_data['choices'][0]['message']['content']
                else:
                    reply_text = f"❌ Error API: {resp_data.get('error', {}).get('message', 'Unknown')}"
    except Exception as e:
        reply_text = f"❌ Server connection failed."
    finally:
        typing_task.cancel()
        
    await message.answer(reply_text)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "assistant", reply_text))
        await db.commit()

# ================= اجرای ربات =================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
