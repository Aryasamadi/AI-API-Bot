import os
import json
import logging
import aiohttp
import aiosqlite
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# بارگذاری متغیرهای محیطی
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

DB_PATH = "bot_database.db"

# ================= دیتابیس =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS apis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                architecture TEXT, -- 'openai' یا 'gemini'
                base_url TEXT,
                api_key TEXT,
                models TEXT -- لیست مدل‌ها به صورت JSON
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                current_api_id INTEGER,
                current_model TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT
            )
        """)
        await db.commit()

# ================= ماشین وضعیت (FSM) =================
class AddAPIStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_arch = State()
    waiting_for_url = State()
    waiting_for_key = State()
    waiting_for_models = State()

# ================= کیبوردها =================
def main_keyboard(is_admin=False):
    buttons = [
        [InlineKeyboardButton(text="🤖 شروع چت با هوش مصنوعی", callback_data="user_mode")]
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ ورود به پنل مدیریت", callback_data="admin_mode")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن API جدید", callback_data="add_api")],
        [InlineKeyboardButton(text="📋 لیست APIها", callback_data="list_apis")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="main_menu")]
    ])

def user_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 انتخاب مدل / API", callback_data="select_api")],
        [InlineKeyboardButton(text="🧹 پاک کردن حافظه چت", callback_data="clear_history")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
    ])

def arch_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="معماری OpenAI (Groq, DeepSeek, و...)", callback_data="arch_openai")],
        [InlineKeyboardButton(text="معماری Gemini", callback_data="arch_gemini")]
    ])

# ================= هندلرهای اصلی =================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer(
        "👋 به ربات هوشمند خوش آمدید!\nلطفاً بخش مورد نظر خود را انتخاب کنید:",
        reply_markup=main_keyboard(is_admin)
    )

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id == ADMIN_ID
    await callback.message.edit_text("منوی اصلی:", reply_markup=main_keyboard(is_admin))

@router.callback_query(F.data == "admin_mode")
async def cb_admin_mode(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("شما ادمین نیستید!", show_alert=True)
    await callback.message.edit_text("⚙️ پنل مدیریت:", reply_markup=admin_keyboard())

@router.callback_query(F.data == "user_mode")
async def cb_user_mode(callback: CallbackQuery):
    await callback.message.edit_text("🤖 پنل کاربری:", reply_markup=user_panel_keyboard())

# ================= هندلرهای پنل مدیریت (افزودن API) =================
@router.callback_query(F.data == "add_api")
async def add_api_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("نام این اتصال را وارد کنید (مثلا: Groq API):")
    await state.set_state(AddAPIStates.waiting_for_name)

@router.message(AddAPIStates.waiting_for_name)
async def add_api_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("معماری این API را انتخاب کنید:", reply_markup=arch_keyboard())
    await state.set_state(AddAPIStates.waiting_for_arch)

@router.callback_query(AddAPIStates.waiting_for_arch)
async def add_api_arch(callback: CallbackQuery, state: FSMContext):
    arch = "openai" if callback.data == "arch_openai" else "gemini"
    await state.update_data(architecture=arch)
    await callback.message.answer("آدرس Base URL را وارد کنید:\n(برای جمینای می‌توانید عبارت `gemini` را بفرستید)")
    await state.set_state(AddAPIStates.waiting_for_url)

@router.message(AddAPIStates.waiting_for_url)
async def add_api_url(message: Message, state: FSMContext):
    await state.update_data(base_url=message.text)
    await message.answer("حالا کلید API (API Key) را بفرستید:")
    await state.set_state(AddAPIStates.waiting_for_key)

@router.message(AddAPIStates.waiting_for_key)
async def add_api_key(message: Message, state: FSMContext):
    await state.update_data(api_key=message.text)
    await message.answer("مدل‌های این API را با کاما جدا کرده و بفرستید:\nمثال: gpt-3.5-turbo, gpt-4")
    await state.set_state(AddAPIStates.waiting_for_models)

@router.message(AddAPIStates.waiting_for_models)
async def add_api_models(message: Message, state: FSMContext):
    models = [m.strip() for m in message.text.split(",")]
    data = await state.get_data()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO apis (name, architecture, base_url, api_key, models) VALUES (?, ?, ?, ?, ?)",
            (data['name'], data['architecture'], data['base_url'], data['api_key'], json.dumps(models))
        )
        await db.commit()
    
    await message.answer("✅ اتصال با موفقیت ذخیره شد!", reply_markup=admin_keyboard())
    await state.clear()

# ================= هندلرهای لیست و حذف API =================
@router.callback_query(F.data == "list_apis")
async def list_apis(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, architecture FROM apis") as cursor:
            apis = await cursor.fetchall()
            
    if not apis:
        return await callback.message.answer("هیچ API ثبت نشده است.", reply_markup=admin_keyboard())

    buttons = []
    for api_id, name, arch in apis:
        buttons.append([InlineKeyboardButton(text=f"🗑 حذف {name} ({arch})", callback_data=f"del_api_{api_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_mode")])
    
    await callback.message.edit_text("لیست API ها (برای حذف روی آن‌ها کلیک کنید):", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("del_api_"))
async def delete_api(callback: CallbackQuery):
    api_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM apis WHERE id = ?", (api_id,))
        await db.commit()
    await callback.answer("✅ حذف شد!", show_alert=True)
    await list_apis(callback)

# ================= هندلرهای کاربری =================
@router.callback_query(F.data == "clear_history")
async def clear_history(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM history WHERE user_id = ?", (callback.from_user.id,))
        await db.commit()
    await callback.answer("🧹 حافظه با موفقیت پاک شد!", show_alert=True)

@router.callback_query(F.data == "select_api")
async def select_api_user(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name FROM apis") as cursor:
            apis = await cursor.fetchall()
            
    if not apis:
        return await callback.answer("ادمین هنوز هیچ API ای تنظیم نکرده است.", show_alert=True)

    buttons = [[InlineKeyboardButton(text=name, callback_data=f"useapi_{api_id}")] for api_id, name in apis]
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="user_mode")])
    await callback.message.edit_text("یک سرویس را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("useapi_"))
async def select_model_user(callback: CallbackQuery):
    api_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT models FROM apis WHERE id = ?", (api_id,)) as cursor:
            row = await cursor.fetchone()
            
    models = json.loads(row[0])
    buttons = [[InlineKeyboardButton(text=m, callback_data=f"setmod_{api_id}_{m}")] for m in models]
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="select_api")])
    await callback.message.edit_text("مدل را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("setmod_"))
async def finalize_selection(callback: CallbackQuery):
    _, api_id, model = callback.data.split("_", 2)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_settings (user_id, current_api_id, current_model) VALUES (?, ?, ?)",
            (callback.from_user.id, int(api_id), model)
        )
        await db.commit()
    await callback.message.edit_text(f"✅ مدل {model} تنظیم شد. حالا می‌توانید چت کنید!", reply_markup=user_panel_keyboard())

# ================= منطق چت و اتصال به API =================
async def fetch_history(user_id, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

async def save_history(user_id, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
        await db.commit()

async def call_ai_api(api_data, model, messages):
    url = api_data['base_url']
    key = api_data['api_key']
    arch = api_data['architecture']
    
    async with aiohttp.ClientSession() as session:
        if arch == "openai":
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": messages}
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                return data['choices'][0]['message']['content']
                
        elif arch == "gemini":
            # تبدیل ساختار استاندارد به ساختار جمینای
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            contents = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})
            payload = {"contents": contents}
            headers = {"Content-Type": "application/json"}
            async with session.post(gemini_url, headers=headers, json=payload) as resp:
                data = await resp.json()
                return data['candidates'][0]['content']['parts'][0]['text']
    return "خطا در برقراری ارتباط با API."

@router.message(F.text & ~F.text.startswith("/"))
async def handle_user_message(message: Message):
    user_id = message.from_user.id
    
    # خواندن تنظیمات کاربر
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT current_api_id, current_model FROM user_settings WHERE user_id = ?", (user_id,)) as cursor:
            settings = await cursor.fetchone()
            
    if not settings:
        return await message.answer("لطفاً ابتدا از پنل کاربری یک مدل انتخاب کنید.")
        
    api_id, model = settings
    
    # خواندن اطلاعات API
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT architecture, base_url, api_key FROM apis WHERE id = ?", (api_id,)) as cursor:
            api_info = await cursor.fetchone()
            
    if not api_info:
        return await message.answer("اتصال API منقضی شده است.")
        
    api_data = {"architecture": api_info[0], "base_url": api_info[1], "api_key": api_info[2]}
    
    # ذخیره پیام کاربر
    await save_history(user_id, "user", message.text)
    
    # دریافت حافظه
    messages = await fetch_history(user_id, limit=10)
    
    wait_msg = await message.answer("درحال پردازش... ⏳")
    
    try:
        response = await call_ai_api(api_data, model, messages)
        await save_history(user_id, "assistant", response)
        await wait_msg.edit_text(response)
    except Exception as e:
        await wait_msg.edit_text(f"خطایی رخ داد: {str(e)}")

# ================= اجرای ربات =================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
