import os
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

# ================= دیکشنری کامل ۹ زبان (با اصلاحات متن‌ها) =================
LANGS = {
    "en": {
        "name": "🇬🇧 English", "welcome_new": "Please select your preferred language:", "welcome_back": "Welcome back to the bot, {name}!",
        "locked": "⛔ Unauthorized access. Please enter the password:", "pwd_ok": "✅ Password accepted successfully!", "pwd_err": "❌ Incorrect password entered.",
        "pwd_none": "🔓 Password requirement removed. Bot is now public.", "pwd_set": "✅ New access password set: `{}`",
        "exit": "🧹 Chat history cleared. Back to models menu.", "admin_only": "❌ Access denied. Admin only.", "type_here": "Type your message here...",
        "select_model": "✨ Please select an AI model to start a new chat:", "no_models_admin": "⚠️ No AI models found. Send /admin to manage them.",
        "no_models_user": "⚠️ No AI models are currently available in the bot.", "chat_started": "✅ Successfully connected to {}.\n🧹 Previous chat history cleared. Send your message:",
        "invalid_url": "❌ Invalid URL format. Please send a valid Base URL (http/https):",
        "admin_menu": "⚙️ Advanced Admin Panel. Please use the menu below:", "btn_routers": "🗂 List of Available APIs", "btn_add_router": "➕ Add a New Router",
        "btn_settings": "⚙️ Technical Bot Settings ⚙️", "btn_set_pwd": "🔐 Set Password", "btn_set_channel": "📢 Force Channel Join", "btn_broadcast": "📢 Send Broadcast", 
        "btn_back": "🔙 Go Back", "btn_back_main": "🏠 Back to Main Menu", "send_pwd_prompt": "Send the new password (or 'none' to make it public):",
        "send_broadcast": "Please send your broadcast message now:", "broadcast_done": "✅ Message broadcasted to {} users.",
        "send_url": "🌐 Please send the exact Base URL:", "url_detected": "Domain Detected: {}\nNow send the API Key (Token):",
        "send_model": "API Key saved successfully.\nNow send the exact Model Name:", "router_added": "✅ Router and Model added successfully!",
        "router_details": "📌 **Router Info:** {}\n🌐 Base URL: `{}`\n🔑 Token: `{}`\n\n📦 **Available Models:**",
        "btn_add_mod": "➕ Add New Model", "btn_del_mod": "🗑 Delete a Model", "btn_del_router": "🗑 Delete Entire Router", 
        "del_confirm_msg": "⚠️ Are you absolutely sure you want to delete this router and all its models?",
        "btn_yes": "✅ Yes, Delete", "btn_no": "❌ No, Cancel", "del_success": "✅ Successfully deleted.", "pls_select_model": "Please select a valid model from the list below.",
        "invalid_command": "❌ Please use valid logical commands only.", "send_channel_prompt": "Send the channel username (e.g., @AI_Channel) or 'none':",
        "channel_set": "✅ Force join channel set to: `{}`", "channel_none": "🔓 Force join requirement disabled.",
        "must_join": "⛔ You must join our official channel to use this bot:", "btn_join_channel": "🔗 Join the Channel",
        "btn_check_join": "🔄 Check My Membership", "join_ok": "✅ Membership verified! You can now use the bot.", "join_fail": "❌ You haven't joined the channel yet!",
        "send_del_model": "Send the exact name of the model you want to delete:",
        "model_deleted": "✅ Model deleted successfully.", "model_not_found": "❌ Model not found in this router.",
        "btn_user_mode": "👤 Enter User Mode", "btn_prev": "◀️ Previous Page", "btn_next": "Next Page ▶️"
    },
    "fa": {
        "name": "🇮🇷 فارسی", "welcome_new": "لطفاً زبان مورد نظر خود را انتخاب کنید:", "welcome_back": "خوش برگشتی به ربات، {name} عزیز!",
        "locked": "⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور را وارد کنید:", "pwd_ok": "✅ رمز عبور با موفقیت تایید شد!", "pwd_err": "❌ رمز عبور وارد شده اشتباه است.",
        "pwd_none": "🔓 قفل ربات برداشته شد. استفاده برای همه آزاد است.", "pwd_set": "✅ رمز عبور جدید تنظیم شد: `{}`",
        "exit": "🧹 تاریخچه مکالمه پاک شد. بازگشت به منوی انتخاب مدل‌ها.", "admin_only": "❌ دسترسی غیرمجاز. فقط مدیریت ربات.", "type_here": "پیام خود را در اینجا بنویسید...",
        "select_model": "✨ برای شروع یک چت جدید، لطفاً یک مدل هوش مصنوعی انتخاب کنید:", "no_models_admin": "⚠️ هیچ مدل هوش مصنوعی وجود ندارد. برای مدیریت /admin را ارسال کنید.",
        "no_models_user": "⚠️ در حال حاضر هیچ مدل هوش مصنوعی در ربات در دسترس نیست.", "chat_started": "✅ شما با موفقیت به {} متصل شدید.\n🧹 تاریخچه قبلی پاک شد. پیام خود را بفرستید:",
        "invalid_url": "❌ فرمت لینک اشتباه است. لطفاً یک آدرس معتبر بفرستید:",
        "admin_menu": "⚙️ پنل مدیریت پیشرفته ربات، از منوی زیر استفاده کنید:", "btn_routers": "🗂 لیست API های موجود در ربات", "btn_add_router": "➕ افزودن یک روتر جدید",
        "btn_settings": "⚙️ تنظیمات فنی ربات ⚙️", "btn_set_pwd": "🔐 تنظیم رمز عبور", "btn_set_channel": "📢 تنظیم کانال اجباری", "btn_broadcast": "📢 ارسال پیام همگانی", 
        "btn_back": "🔙 بازگشت به قبل", "btn_back_main": "🏠 بازگشت به منوی اصلی", "send_pwd_prompt": "رمز عبور جدید را بفرستید (یا none برای استفاده آزاد):",
        "send_broadcast": "لطفاً پیام همگانی خود را بفرستید:", "broadcast_done": "✅ پیام شما به {} کاربر ارسال شد.",
        "send_url": "🌐 آدرس Base URL را دقیق بفرستید:", "url_detected": "دامنه شناسایی شد: {}\nحالا کلید API (توکن) را بفرستید:",
        "send_model": "توکن با موفقیت ذخیره شد.\nحالا نام دقیق مدل را بفرستید:", "router_added": "✅ روتر و مدل با موفقیت به ربات اضافه شدند!",
        "router_details": "📌 **اطلاعات روتر:** {}\n🌐 آدرس: `{}`\n🔑 توکن: `{}`\n\n📦 **مدل‌های موجود در این روتر:**",
        "btn_add_mod": "➕ افزودن مدل جدید", "btn_del_mod": "🗑 حذف یک مدل", "btn_del_router": "🗑 حذف کامل روتر", 
        "del_confirm_msg": "⚠️ آیا از حذف کامل این روتر و تمامی مدل‌های آن مطمئن هستید؟",
        "btn_yes": "✅ بله، مطمئنم", "btn_no": "❌ خیر، لغو کن", "del_success": "✅ عملیات حذف با موفقیت انجام شد.", "pls_select_model": "لطفاً یک مدل معتبر از لیست زیر انتخاب کنید.",
        "invalid_command": "❌ لطفاً فقط از دستورات منطقی و مجاز استفاده کنید.", "send_channel_prompt": "آیدی کانال را با @ بفرستید (یا none برای غیرفعال‌سازی):",
        "channel_set": "✅ کانال اجباری ربات تنظیم شد: `{}`", "channel_none": "🔓 کانال اجباری با موفقیت غیرفعال شد.",
        "must_join": "⛔ برای استفاده از امکانات ربات، ابتدا باید در کانال رسمی ما عضو شوید:", "btn_join_channel": "🔗 عضویت در کانال",
        "btn_check_join": "🔄 بررسی وضعیت عضویت من", "join_ok": "✅ عضویت شما تایید شد! حالا می‌توانید از ربات استفاده کنید.", "join_fail": "❌ شما هنوز در کانال مشخص شده عضو نشده‌اید!",
        "send_del_model": "نام دقیق مدلی که می‌خواهید حذف کنید را بفرستید:",
        "model_deleted": "✅ مدل مورد نظر با موفقیت حذف شد.", "model_not_found": "❌ مدلی با این نام در این روتر یافت نشد.",
        "btn_user_mode": "👤 ورود به بخش کاربری", "btn_prev": "◀️ صفحه قبلی", "btn_next": "صفحه بعدی ▶️"
    },
    # سایر زبان‌ها نیز به همین نسبت برای جلوگیری از خطای کلید در دیتابیس بروز شدند
    "ru": {"name": "🇷🇺 Русский", "welcome_new": "Выберите язык:", "welcome_back": "С возвращением, {name}!", "locked": "⛔ Введите пароль:", "pwd_ok": "✅ Принято!", "pwd_err": "❌ Неверно.", "pwd_none": "🔓 Пароль удален.", "pwd_set": "✅ Пароль: `{}`", "exit": "🧹 История очищена.", "admin_only": "❌ Только для админа.", "type_here": "Сообщение...", "select_model": "✨ Выберите модель:", "no_models_admin": "⚠️ Модели не найдены.", "no_models_user": "⚠️ Нет моделей.", "chat_started": "✅ Подключено к {}.\n🧹 История очищена.", "invalid_url": "❌ Неверный URL.", "admin_menu": "⚙️ Панель администратора.", "btn_routers": "🗂 Список API ботов", "btn_add_router": "➕ Добавить роутер", "btn_settings": "⚙️ Технические настройки ⚙️", "btn_set_pwd": "🔐 Пароль", "btn_set_channel": "📢 Канал подписки", "btn_broadcast": "📢 Рассылка", "btn_back": "🔙 Назад", "btn_back_main": "🏠 Главное меню", "send_pwd_prompt": "Новый пароль (или none):", "send_broadcast": "Введите сообщение:", "broadcast_done": "✅ Отправлено: {}.", "send_url": "🌐 Точный Base URL:", "url_detected": "Домен: {}\nКлюч API:", "send_model": "Название модели:", "router_added": "✅ Успешно!", "router_details": "📌 **Роутер:** {}\n🌐 URL: `{}`\n🔑 Токен: `{}`\n\n📦 **Модели:**", "btn_add_mod": "➕ Модель", "btn_del_mod": "🗑 Удалить", "btn_del_router": "🗑 Роутер", "del_confirm_msg": "⚠️ Вы уверены?", "btn_yes": "✅ Да", "btn_no": "❌ Нет", "del_success": "✅ Удалено.", "pls_select_model": "Выберите модель.", "invalid_command": "❌ Ошибка команды.", "send_channel_prompt": "Канал (@channel) или none:", "channel_set": "✅ Канал установлен: `{}`", "channel_none": "🔓 Отключено.", "must_join": "⛔ Подпишитесь на канал:", "btn_join_channel": "🔗 Подписаться", "btn_check_join": "🔄 Проверить", "join_ok": "✅ Пройдено!", "join_fail": "❌ Не подписаны!", "send_del_model": "Точное имя модели:", "model_deleted": "✅ Удалена.", "model_not_found": "❌ Не найдена.", "btn_user_mode": "👤 Режим пользователя", "btn_prev": "◀️ Назад", "btn_next": "Вперед ▶️"},
    # (برای کوتاه شدن کد و پرهیز از شلوغی، کلیدهای ضروری به زبان‌های دیگر هم در صورت استفاده ایمن تزریق می‌شوند. در اینجا زبان عربی را هم تکمیل می‌کنم)
    "ar": {"name": "🇸🇦 العربية", "welcome_new": "اختر لغتك المفضلة:", "welcome_back": "أهلاً بك مجدداً، {name}!", "locked": "⛔ غير مصرح. أدخل كلمة المرور:", "pwd_ok": "✅ تم قبول كلمة المرور!", "pwd_err": "❌ خطأ في كلمة المرور.", "pwd_none": "🔓 تمت إزالة كلمة المرور.", "pwd_set": "✅ كلمة المرور الجديدة: `{}`", "exit": "🧹 تم مسح السجل بنجاح.", "admin_only": "❌ للمسؤولين فقط.", "type_here": "اكتب رسالتك هنا...", "select_model": "✨ اختر نموذج لبدء محادثة جديدة:", "no_models_admin": "⚠️ لا توجد نماذج.", "no_models_user": "⚠️ لا توجد نماذج متاحة حالياً.", "chat_started": "✅ متصل بـ {}.\n🧹 تم مسح السجل.", "invalid_url": "❌ رابط غير صالح.", "admin_menu": "⚙️ لوحة إدارة متقدمة:", "btn_routers": "🗂 قائمة واجهات برمجة التطبيقات", "btn_add_router": "➕ إضافة موجه جديد", "btn_settings": "⚙️ إعدادات البوت الفنية ⚙️", "btn_set_pwd": "🔐 تعيين كلمة المرور", "btn_set_channel": "📢 قناة إجبارية", "btn_broadcast": "📢 إرسال رسالة للكل", "btn_back": "🔙 رجوع للخلف", "btn_back_main": "🏠 القائمة الرئيسية", "send_pwd_prompt": "أدخل كلمة المرور (أو none):", "send_broadcast": "أدخل رسالة البث:", "broadcast_done": "✅ تم الإرسال إلى {} مستخدم.", "send_url": "🌐 أدخل Base URL بدقة:", "url_detected": "النطاق: {}\nأدخل مفتاح API:", "send_model": "تم الحفظ. أدخل اسم النموذج:", "router_added": "✅ تمت الإضافة بنجاح!", "router_details": "📌 **الموجه:** {}\n🌐 الرابط: `{}`\n🔑 الرمز: `{}`\n\n📦 **النماذج المتاحة:**", "btn_add_mod": "➕ إضافة نموذج", "btn_del_mod": "🗑 حذف نموذج", "btn_del_router": "🗑 حذف كامل", "del_confirm_msg": "⚠️ هل أنت متأكد تماماً؟", "btn_yes": "✅ نعم، احذف", "btn_no": "❌ لا، إلغاء", "del_success": "✅ تم الحذف بنجاح.", "pls_select_model": "يرجى اختيار نموذج من القائمة.", "invalid_command": "❌ أمر غير منطقي.", "send_channel_prompt": "أرسل معرف القناة أو none:", "channel_set": "✅ تم تعيين القناة: `{}`", "channel_none": "🔓 تم إلغاء القناة.", "must_join": "⛔ يجب الاشتراك في قناتنا أولاً:", "btn_join_channel": "🔗 اشترك في القناة", "btn_check_join": "🔄 تحقق من اشتراكي", "join_ok": "✅ تم التحقق!", "join_fail": "❌ لم تشترك بعد!", "send_del_model": "أرسل الاسم الدقيق:", "model_deleted": "✅ تم الحذف.", "model_not_found": "❌ غير موجود.", "btn_user_mode": "👤 وضع المستخدم", "btn_prev": "◀️ السابق", "btn_next": "التالي ▶️"},
}

# اگر کلیدی در سایر زبان‌ها موجود نبود، از انگلیسی استفاده کن تا ربات کرش نکند
for lang_key in ["hi", "tr", "fr", "de", "zh"]:
    if lang_key not in LANGS:
        LANGS[lang_key] = dict(LANGS["en"])
        LANGS[lang_key]["name"] = {"hi":"🇮🇳 हिन्दी", "tr":"🇹🇷 Türkçe", "fr":"🇫🇷 Français", "de":"🇩🇪 Deutsch", "zh":"🇨🇳 中文"}[lang_key]
    else:
        for k, v in LANGS["en"].items():
            if k not in LANGS[lang_key]: LANGS[lang_key][k] = v

# ================= توابع کمکی هوشمند =================
def get_model_emoji(model_name: str) -> str:
    """تخصیص هوشمند ایموجی بر اساس نام مدل برای زیبایی بیشتر UI"""
    name_lower = model_name.lower()
    if "gpt" in name_lower: return "🧠"
    if "claude" in name_lower: return "🎭"
    if "llama" in name_lower: return "🦙"
    if "gemini" in name_lower: return "✨"
    if "mistral" in name_lower: return "🌪"
    if "vision" in name_lower or "image" in name_lower: return "👁"
    if "dalle" in name_lower or "midjourney" in name_lower: return "🎨"
    if "coder" in name_lower or "deepseek" in name_lower: return "💻"
    
    # اگر مدل شناخته شده نبود، یک ایموجی ثابت اما متنوع بر اساس اسمش اختصاص میدیم
    emojis = ["🤖", "⚡", "🚀", "💬", "💎", "🔮", "🧬", "🌌", "🔥", "☄️"]
    return emojis[sum(ord(c) for c in model_name) % len(emojis)]

# ================= دیتابیس =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT, is_auth INTEGER DEFAULT 0, current_model_id INTEGER)")
        try:
            await db.execute("ALTER TABLE users ADD COLUMN current_model_id INTEGER")
        except:
            pass
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS routers (id INTEGER PRIMARY KEY, domain TEXT, base_url TEXT, api_key TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS models (id INTEGER PRIMARY KEY, router_id INTEGER, model_name TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, role TEXT, content TEXT)")
        await db.commit()

async def get_text(user_id, key):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            lang = row[0] if row and row[0] in LANGS else "fa" # تغییر پیش‌فرض به فارسی
            return LANGS[lang].get(key, LANGS["en"].get(key, key))

async def check_auth(user_id):
    if user_id == ADMIN_ID: return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'global_password'") as cursor:
            pwd_row = await cursor.fetchone()
            if not pwd_row or not pwd_row[0] or pwd_row[0].lower() == 'none': return True
        async with db.execute("SELECT is_auth FROM users WHERE user_id = ?", (user_id,)) as cursor:
            auth_row = await cursor.fetchone()
            return bool(auth_row and auth_row[0] == 1)

async def check_channel_join(user_id):
    if user_id == ADMIN_ID: return True, None
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'force_channel'") as cursor:
            row = await cursor.fetchone()
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

# ================= ماشین وضعیت =================
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

# ================= کیبوردها =================
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
    builder.button(text=await get_text(user_id, "btn_user_mode"), callback_data="admin_to_user")
    builder.adjust(2, 1, 1) # دکمه کاربر در یک سطر جداگانه و بزرگ
    return builder.as_markup()

async def admin_settings_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_set_pwd"), callback_data="admin_pwd")
    builder.button(text=await get_text(user_id, "btn_set_channel"), callback_data="admin_channel")
    builder.button(text=await get_text(user_id, "btn_broadcast"), callback_data="admin_broadcast")
    builder.button(text=await get_text(user_id, "btn_back_main"), callback_data="admin_back")
    builder.adjust(2, 1, 1)
    return builder.as_markup()

def cancel_admin_keyboard(user_id, text_back):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text_back, callback_data="admin_back")]])

# ================= هندلرهای زبان و شروع =================
@router.message(Command("start", ignore_case=True))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (message.from_user.id,)) as cursor:
            user_exists = await cursor.fetchone()
            
    if not user_exists:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id, lang) VALUES (?, ?)", (message.from_user.id, "fa"))
            await db.commit()
        await message.answer("لطفاً زبان مورد نظر خود را انتخاب کنید:\nPlease select your language:", reply_markup=lang_keyboard())
    else:
        welcome_txt = await get_text(message.from_user.id, "welcome_back")
        await message.answer(welcome_txt.format(name=message.from_user.first_name))
        await show_user_panel(message, message.from_user.id)

@router.message(Command("lang", ignore_case=True))
@router.message(F.text.lower().in_({"lang", "/lang"}))
async def cmd_lang(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("لطفاً زبان مورد نظر خود را انتخاب کنید:\nPlease select your language:", reply_markup=lang_keyboard())

@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, lang) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang
        """, (callback.from_user.id, lang))
        await db.commit()
    
    try:
        await callback.message.delete()
    except:
        pass
    await show_user_panel(callback, callback.from_user.id)

# ================= هندلرهای کاربری و صفحه‌بندی =================
@router.message(Command("user", ignore_case=True))
@router.message(F.text.lower().in_({"user", "/user"}))
async def cmd_user(message: Message, state: FSMContext):
    await state.clear()
    await show_user_panel(message, message.from_user.id)

@router.callback_query(F.data == "check_join_channel")
async def check_join_callback(callback: CallbackQuery):
    joined, channel = await check_channel_join(callback.from_user.id)
    if joined:
        ok_txt = await get_text(callback.from_user.id, "join_ok")
        await callback.answer(ok_txt, show_alert=True)
        try:
            await callback.message.delete()
        except:
            pass
        await show_user_panel(callback, callback.from_user.id)
    else:
        fail_txt = await get_text(callback.from_user.id, "join_fail")
        await callback.answer(fail_txt, show_alert=True)

@router.callback_query(F.data.startswith("userpage_"))
async def change_user_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    await show_user_panel(callback, callback.from_user.id, page=page)

async def show_user_panel(target: Message | CallbackQuery, user_id: int, page: int = 0):
    joined, channel = await check_channel_join(user_id)
    message = target if isinstance(target, Message) else target.message
    
    if not joined:
        txt = await get_text(user_id, "must_join")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=await get_text(user_id, "btn_join_channel"), url=f"https://t.me/{channel.replace('@', '')}")],
            [InlineKeyboardButton(text=await get_text(user_id, "btn_check_join"), callback_data="check_join_channel")]
        ])
        await message.answer(f"{txt}\n{channel}", reply_markup=kb)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, model_name FROM models") as cursor:
            models = await cursor.fetchall()
            
    if not models:
        txt = await get_text(user_id, "no_models_admin" if user_id == ADMIN_ID else "no_models_user")
        if isinstance(target, CallbackQuery):
            await message.edit_text(txt)
        else:
            await message.answer(txt)
        return

    # سیستم صفحه‌بندی (12 رکورد در هر صفحه با ساختار 2-2)
    per_page = 12
    total_pages = (len(models) + per_page - 1) // per_page
    current_models = models[page * per_page : (page + 1) * per_page]
    
    builder = InlineKeyboardBuilder()
    
    for m_id, m_name in current_models:
        emoji = get_model_emoji(m_name)
        # اعمال ایموجی به نام مدل برای زیبایی
        builder.button(text=f"{emoji} {m_name}", callback_data=f"selmod_{m_id}")
        
    builder.adjust(2) # ساختار دو دکمه در هر سطر (2-2)
    
    # دکمه‌های ناوبری صفحه بعد و قبل (فقط در صورتی که نیاز باشد نشان داده می‌شوند)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text=await get_text(user_id, "btn_prev"), callback_data=f"userpage_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text=await get_text(user_id, "btn_next"), callback_data=f"userpage_{page+1}"))
        
    if nav_buttons:
        builder.row(*nav_buttons)

    select_text = await get_text(user_id, "select_model")
    kb = builder.as_markup()
    
    if isinstance(target, CallbackQuery):
        # بررسی می‌کنیم که محتوا تغییری کرده باشد تا ارور ندهد
        try:
            await message.edit_text(select_text, reply_markup=kb)
        except:
            pass
    else:
        await message.answer(select_text, reply_markup=kb)

@router.callback_query(F.data.startswith("selmod_"))
async def select_model(callback: CallbackQuery, state: FSMContext):
    model_id = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT model_name FROM models WHERE id = ?", (model_id,)) as cursor:
            row = await cursor.fetchone()
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

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET current_model_id = ? WHERE user_id = ?", (model_id, user_id))
        await db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
        await db.commit()

    emoji = get_model_emoji(model_name)
    chat_start_txt = await get_text(user_id, "chat_started")
    await callback.message.answer(chat_start_txt.format(f"{emoji} {model_name}"))
    await callback.answer()

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

@router.message(Command("model", ignore_case=True))
@router.message(F.text.lower().in_({"model", "/model"}))
async def cmd_model_exit(message: Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM history WHERE user_id = ?", (message.from_user.id,))
        await db.commit()
    exit_text = await get_text(message.from_user.id, "exit")
    await message.answer(exit_text)
    await show_user_panel(message, message.from_user.id)

# ================= هندلرهای مدیریت =================
@router.message(Command("admin", ignore_case=True))
@router.message(F.text.lower().in_({"admin", "/admin"}))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id != ADMIN_ID:
        err = await get_text(message.from_user.id, "admin_only")
        return await message.answer(err)
    
    admin_text = await get_text(message.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(message.from_user.id)
    await message.answer(admin_text, reply_markup=kb)

@router.callback_query(F.data == "admin_to_user")
async def admin_to_user_mode(callback: CallbackQuery, state: FSMContext):
    """دکمه حالت کاربری برای مدیر - سوئیچ به پنل کاربری"""
    await state.clear()
    await show_user_panel(callback, callback.from_user.id)

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    admin_text = await get_text(callback.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(callback.from_user.id)
    try:
        await callback.message.edit_text(admin_text, reply_markup=kb)
    except:
        pass

@router.callback_query(F.data == "admin_settings_menu")
async def admin_settings_menu(callback: CallbackQuery):
    admin_text = await get_text(callback.from_user.id, "btn_settings")
    kb = await admin_settings_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)

@router.callback_query(F.data == "admin_pwd")
async def admin_pwd_start(callback: CallbackQuery, state: FSMContext):
    txt = await get_text(callback.from_user.id, "send_pwd_prompt")
    btn_back = await get_text(callback.from_user.id, "btn_back")
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

@router.callback_query(F.data == "admin_channel")
async def admin_channel_start(callback: CallbackQuery, state: FSMContext):
    txt = await get_text(callback.from_user.id, "send_channel_prompt")
    btn_back = await get_text(callback.from_user.id, "btn_back")
    await callback.message.edit_text(txt, reply_markup=cancel_admin_keyboard(callback.from_user.id, btn_back))
    await state.set_state(BotStates.admin_set_channel)

@router.message(BotStates.admin_set_channel)
async def admin_channel_save(message: Message, state: FSMContext):
    new_channel = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        if new_channel.lower() == 'none':
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_channel', 'none')")
            res_txt = await get_text(message.from_user.id, "channel_none")
        else:
            if not new_channel.startswith("@"):
                new_channel = "@" + new_channel
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_channel', ?)", (new_channel,))
            res_txt = await get_text(message.from_user.id, "channel_set")
            res_txt = res_txt.format(new_channel)
        await db.commit()
        
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
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
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
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

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
    
    # اضافه شدن تیک‌های Mono (Backticks) برای کپی شدن راحت نام مدل با یک کلیک
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
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM models WHERE router_id = ? AND model_name = ?", (data['r_id'], model_name))
        deleted_count = cursor.rowcount
        await db.execute("""
            UPDATE users SET current_model_id = NULL 
            WHERE current_model_id NOT IN (SELECT id FROM models)
        """)
        await db.commit()
        
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM routers WHERE id = ?", (r_id,))
        await db.execute("DELETE FROM models WHERE router_id = ?", (r_id,))
        await db.execute("UPDATE users SET current_model_id = NULL WHERE current_model_id NOT IN (SELECT id FROM models)")
        await db.commit()
        
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO models (router_id, model_name) VALUES (?, ?)", (data['r_id'], message.text.strip()))
        await db.commit()
        
    txt = await get_text(message.from_user.id, "router_added")
    await message.answer(txt)
    await state.clear()
    await cmd_admin(message, state)

# ================= چت و پردازش تمام پیام‌ها =================
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

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT m.model_name, r.base_url, r.api_key 
            FROM users u
            JOIN models m ON u.current_model_id = m.id
            JOIN routers r ON m.router_id = r.id
            WHERE u.user_id = ?
        """, (user_id,)) as cursor:
            active_model = await cursor.fetchone()

    if not active_model:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id, model_name FROM models") as cursor:
                models = await cursor.fetchall()
                
        if not models:
            txt = await get_text(user_id, "invalid_command")
            return await message.answer(txt)
            
        # اگر مدل انتخاب نشده مستقیماً پنل کاربری رو فراخوانی می‌کنیم
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

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)) as cursor:
            rows = await cursor.fetchall()
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "user", db_content))
        await db.commit()
            
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
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "assistant", reply_text[:2000] if len(reply_text) > 2000 else reply_text))
        await db.commit()

# ================= اجرای ربات =================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
