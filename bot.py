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

# ================= دیکشنری زبان‌ها =================
# ۹ زبان: EN, RU, FA, AR, HI, TR, FR, DE, ZH
LANGS = {
    "en": {"name": "🇬🇧 English", "welcome": "Welcome! Please select a model to chat.", "locked": "⛔ You are unauthorized. Please enter the password to access the bot:", "pwd_ok": "✅ Password accepted! You can now chat.", "pwd_err": "❌ Incorrect password. Try again:", "exit": "🧹 Chat history cleared. You are back to the main menu.", "admin_only": "❌ Admin only.", "type_here": "Type your message...", "select_model": "Select an AI model from the list below to start:"},
    "ru": {"name": "🇷🇺 Русский", "welcome": "Добро пожаловать! Выберите модель.", "locked": "⛔ Нет доступа. Введите пароль:", "pwd_ok": "✅ Пароль принят!", "pwd_err": "❌ Неверный пароль.", "exit": "🧹 История очищена.", "admin_only": "❌ Только админ.", "type_here": "Введите сообщение...", "select_model": "Выберите модель ИИ ниже:"},
    "fa": {"name": "🇮🇷 فارسی", "welcome": "خوش آمدید! لطفاً یک مدل را انتخاب کنید.", "locked": "⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور را ارسال کنید:", "pwd_ok": "✅ رمز عبور تایید شد! حالا می‌توانید گفتگو کنید.", "pwd_err": "❌ رمز اشتباه است. دوباره تلاش کنید:", "exit": "🧹 تاریخچه مکالمه شما پاک شد. به منوی اصلی برگشتید.", "admin_only": "❌ دسترسی فقط برای مدیریت.", "type_here": "پیام خود را بنویسید...", "select_model": "برای شروع، یکی از مدل‌های هوش مصنوعی زیر را انتخاب کنید:"},
    "ar": {"name": "🇸🇦 العربية", "welcome": "أهلاً بك! يرجى اختيار نموذج.", "locked": "⛔ غير مصرح لك. أدخل كلمة المرور:", "pwd_ok": "✅ تم قبول كلمة المرور!", "pwd_err": "❌ كلمة المرور خاطئة.", "exit": "🧹 تم مسح السجل.", "admin_only": "❌ للمسؤولين فقط.", "type_here": "اكتب رسالتك...", "select_model": "اختر نموذج ذكاء اصطناعي للبدء:"},
    "hi": {"name": "🇮🇳 हिन्दी", "welcome": "स्वागत है! कृपया एक मॉडल चुनें।", "locked": "⛔ आप अनधिकृत हैं। पासवर्ड दर्ज करें:", "pwd_ok": "✅ पासवर्ड स्वीकार किया गया!", "pwd_err": "❌ गलत पासवर्ड।", "exit": "🧹 इतिहास साफ़ हो गया।", "admin_only": "❌ केवल व्यवस्थापक।", "type_here": "अपना संदेश लिखें...", "select_model": "शुरू करने के लिए एक एआई मॉडल चुनें:"},
    "tr": {"name": "🇹🇷 Türkçe", "welcome": "Hoş geldiniz! Lütfen bir model seçin.", "locked": "⛔ Yetkisizsiniz. Lütfen şifreyi girin:", "pwd_ok": "✅ Şifre kabul edildi!", "pwd_err": "❌ Yanlış şifre.", "exit": "🧹 Sohbet geçmişi temizlendi.", "admin_only": "❌ Sadece yönetici.", "type_here": "Mesajınızı yazın...", "select_model": "Başlamak için bir yapay zeka modeli seçin:"},
    "fr": {"name": "🇫🇷 Français", "welcome": "Bienvenue ! Veuillez sélectionner un modèle.", "locked": "⛔ Non autorisé. Entrez le mot de passe :", "pwd_ok": "✅ Mot de passe accepté !", "pwd_err": "❌ Mot de passe incorrect.", "exit": "🧹 Historique effacé.", "admin_only": "❌ Admin uniquement.", "type_here": "Tapez votre message...", "select_model": "Sélectionnez un modèle d'IA pour commencer :"},
    "de": {"name": "🇩🇪 Deutsch", "welcome": "Willkommen! Bitte wählen Sie ein Modell.", "locked": "⛔ Nicht autorisiert. Bitte Passwort eingeben:", "pwd_ok": "✅ Passwort akzeptiert!", "pwd_err": "❌ Falsches Passwort.", "exit": "🧹 Verlauf gelöscht.", "admin_only": "❌ Nur für Admins.", "type_here": "Schreibe deine Nachricht...", "select_model": "Wähle ein KI-Modell um zu beginnen:"},
    "zh": {"name": "🇨🇳 中文", "welcome": "欢迎！请选择一个模型。", "locked": "⛔ 未经授权。请输入密码：", "pwd_ok": "✅ 密码已接受！", "pwd_err": "❌ 密码错误。", "exit": "🧹 聊天记录已清除。", "admin_only": "❌ 仅限管理员。", "type_here": "输入您的消息...", "select_model": "选择一个 AI 模型开始："}
}

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
            if not pwd_row or not pwd_row[0]: return True # رمز تنظیم نشده است
        async with db.execute("SELECT is_auth FROM users WHERE user_id = ?", (user_id,)) as cursor:
            auth_row = await cursor.fetchone()
            return bool(auth_row and auth_row[0] == 1)

# ================= ماشین وضعیت =================
class BotStates(StatesGroup):
    waiting_for_password = State()
    chatting = State()
    admin_add_router_url = State()
    admin_add_router_key = State()
    admin_add_model = State()
    admin_set_password = State()
    admin_broadcast = State()

# ================= پنل‌ها و کیبوردها =================
def lang_keyboard():
    buttons = [[InlineKeyboardButton(text=v["name"], callback_data=f"setlang_{k}")] for k, v in LANGS.items()]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def user_models_keyboard():
    buttons = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, model_name FROM models") as cursor:
            models = await cursor.fetchall()
            for m_id, m_name in models:
                # استفاده از ۵ کلمه برای بزرگتر شدن دکمه‌ها
                buttons.append([InlineKeyboardButton(text=f"🚀 شروع کار با مدل {m_name}", callback_data=f"selectmodel_{m_id}_{m_name}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗂 لیست APIها (روترها)", callback_data="admin_routers")],
        [InlineKeyboardButton(text="➕ افزودن روتر جدید", callback_data="admin_add_router")],
        [InlineKeyboardButton(text="🔐 تنظیم/تغییر رمز عبور", callback_data="admin_pwd")],
        [InlineKeyboardButton(text="📢 ارسال پیام همگانی", callback_data="admin_broadcast")]
    ])

# ================= هندلرهای شروع و زبان =================
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, lang) VALUES (?, ?)", (message.from_user.id, "en"))
        await db.commit()
    await message.answer("Please select your language / لطفاً زبان خود را انتخاب کنید:", reply_markup=lang_keyboard())

@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, callback.from_user.id))
        await db.commit()
    
    welcome_text = await get_text(callback.from_user.id, "welcome")
    await callback.message.edit_text(welcome_text)
    await show_user_panel(callback.message, callback.from_user.id)

# ================= هندلرهای کاربری =================
@router.message(Command("user"))
@router.message(F.text.in_({"کاربر", "user"}))
async def cmd_user(message: Message, state: FSMContext):
    await state.clear()
    await show_user_panel(message, message.from_user.id)

async def show_user_panel(message, user_id):
    select_text = await get_text(user_id, "select_model")
    kb = await user_models_keyboard()
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
    await callback.message.answer(f"✅ شما به {model_name} متصل شدید. مکالمه را شروع کنید:\n(برای خروج عبارت /exit را بفرستید)")

@router.message(BotStates.waiting_for_password)
async def check_password_input(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'global_password'") as cursor:
            pwd_row = await cursor.fetchone()
            global_pwd = pwd_row[0] if pwd_row else ""
            
    if message.text == global_pwd:
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
@router.message(F.text.in_({"خروج", "exit"}))
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
@router.message(F.text.in_({"مدیریت", "admin"}))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id != ADMIN_ID:
        err = await get_text(message.from_user.id, "admin_only")
        return await message.answer(err)
    await message.answer("⚙️ به پنل مدیریت پیشرفته خوش آمدید:", reply_markup=admin_panel_keyboard())

# --- مدیریت رمز عبور ---
@router.callback_query(F.data == "admin_pwd")
async def admin_pwd_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("رمز عبور جدید را بفرستید:\n(با تنظیم رمز جدید، دسترسی تمام کاربران فعلی قطع می‌شود تا زمانی که رمز جدید را وارد کنند)")
    await state.set_state(BotStates.admin_set_password)

@router.message(BotStates.admin_set_password)
async def admin_pwd_save(message: Message, state: FSMContext):
    new_pwd = message.text
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('global_password', ?)", (new_pwd,))
        await db.execute("UPDATE users SET is_auth = 0") # سلب دسترسی همه
        await db.commit()
    await message.answer(f"✅ رمز عبور جدید تنظیم شد: `{new_pwd}`\nهمه کاربران مجدداً قفل شدند.")
    await state.clear()

# --- ارسال پیام همگانی ---
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("پیام خود را بفرستید تا برای همه کاربران ربات ارسال شود:")
    await state.set_state(BotStates.admin_broadcast)

@router.message(BotStates.admin_broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
    count = 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
            for u in users:
                try:
                    await bot.send_message(u[0], f"📢 پیام از مدیریت:\n\n{message.text}")
                    count += 1
                except:
                    pass
    await message.answer(f"✅ پیام به {count} کاربر ارسال شد.")
    await state.clear()

# --- مدیریت روترها و مدل‌ها ---
@router.callback_query(F.data == "admin_add_router")
async def add_router_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("آدرس Base URL سایت را بفرستید:\n(ربات به صورت خودکار اسم سایت را استخراج می‌کند)")
    await state.set_state(BotStates.admin_add_router_url)

@router.message(BotStates.admin_add_router_url)
async def add_router_url(message: Message, state: FSMContext):
    url = message.text
    domain = urlparse(url).netloc or url
    await state.update_data(base_url=url, domain=domain)
    await message.answer(f"سایت تشخیص داده شده: {domain}\nحالا کلید API (Token) را بفرستید:")
    await state.set_state(BotStates.admin_add_router_key)

@router.message(BotStates.admin_add_router_key)
async def add_router_key(message: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO routers (domain, base_url, api_key) VALUES (?, ?, ?)", (data['domain'], data['base_url'], message.text))
        await db.commit()
    await message.answer("✅ دسته بندی روتر جدید ایجاد شد!", reply_markup=admin_panel_keyboard())
    await state.clear()

@router.callback_query(F.data == "admin_routers")
async def admin_routers_list(callback: CallbackQuery):
    buttons = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, domain FROM routers") as cursor:
            for r_id, domain in await cursor.fetchall():
                buttons.append([InlineKeyboardButton(text=f"روتر: {domain}", callback_data=f"router_{r_id}")])
    await callback.message.edit_text("لیست روترها (برای مشاهده مشخصه‌ها کلیک کنید):", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("router_"))
async def admin_router_details(callback: CallbackQuery):
    r_id = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT domain, base_url, api_key FROM routers WHERE id = ?", (r_id,)) as cursor:
            r = await cursor.fetchone()
        async with db.execute("SELECT id, model_name FROM models WHERE router_id = ?", (r_id,)) as cursor:
            models = await cursor.fetchall()

    if not r: return
    
    msg = f"📌 **مشخصات روتر:** {r[0]}\n"
    msg += f"🌐 Base URL: `{r[1]}`\n"
    msg += f"🔑 API Key: `{r[2]}`\n\n"
    msg += "📦 **مدل‌های متصل شده:**\n"
    for _, m_name in models:
        msg += f"- {m_name}\n"
        
    buttons = [
        [InlineKeyboardButton(text="➕ افزودن مدل به این روتر", callback_data=f"addmod_{r_id}")],
        [InlineKeyboardButton(text="🗑 حذف کل این روتر", callback_data=f"delrouter_{r_id}")],
        [InlineKeyboardButton(text="بازگشت", callback_data="admin_routers")]
    ]
    await callback.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("addmod_"))
async def admin_add_model(callback: CallbackQuery, state: FSMContext):
    r_id = callback.data.split("_")[1]
    await state.update_data(r_id=r_id)
    await callback.message.answer("نام دقیق مدل را ارسال کنید (مثلاً gpt-4o):")
    await state.set_state(BotStates.admin_add_model)

@router.message(BotStates.admin_add_model)
async def admin_save_model(message: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (data['r_id'], message.text.strip()))
        await db.commit()
    await message.answer(f"✅ مدل روی دکمه‌ها ذخیره شد!")
    await state.clear()

@router.callback_query(F.data.startswith("delrouter_"))
async def admin_delete_router(callback: CallbackQuery):
    r_id = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM routers WHERE id = ?", (r_id,))
        await db.execute("DELETE FROM models WHERE router_id = ?", (r_id,))
        await db.commit()
    await callback.answer("✅ روتر و مدل‌های آن حذف شدند.", show_alert=True)
    await admin_routers_list(callback)

# ================= چت و ارتباط با API =================
async def typing_action_task(chat_id):
    # این تابع در پس‌زمینه اجرا می‌شود و اکشن تایپ را زنده نگه می‌دارد
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
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

    # مدیریت تاریخچه
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "user", message.text))
        await db.commit()
        async with db.execute("SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            messages = [{"role": r[0], "content": r[1]} for r in reversed(rows)]
            
    # روشن کردن تایپینگ در پس‌زمینه
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
        typing_task.cancel() # متوقف کردن تایپینگ
        
    await message.answer(reply_text)
    
    # ذخیره پاسخ
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "assistant", reply_text))
        await db.commit()

# ================= اجرای ربات =================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
