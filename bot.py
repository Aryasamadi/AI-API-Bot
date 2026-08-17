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

# ------------------------------
# Load environment
# ------------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)
DB_PATH = "bot_advanced.db"

# ------------------------------
# Generic External Database Manager (Cloudflare D1 by default)
# ------------------------------
class DatabaseManager:
    def __init__(self):
        self.db_path = DB_PATH
        # Use your custom variable names from the image
        self.cloud_account = os.getenv("CLOUD_ACCOUNT_ID")
        self.cloud_db_id = os.getenv("CLOUD_DB_ID")
        self.cloud_token = os.getenv("CLOUD_API_TOKEN")
        self.use_cloud = bool(self.cloud_account and self.cloud_db_id and self.cloud_token and self.cloud_token.strip())
        if self.use_cloud:
            logging.info("☁️ External cloud database mode ACTIVE (Cloudflare D1)")
        else:
            logging.info("💾 Local SQLite mode ACTIVE")

    async def _cloud_request(self, query, params=()):
        """
        Generic method for external cloud DB.
        Currently uses Cloudflare D1 API.
        For other services, replace the URL and headers here.
        """
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
                        return data["result"][0] if data["result"] else None
                    else:
                        logging.error(f"Cloud API error: {data.get('errors')}")
                        return None
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

    async def truncate_all_tables(self):
        tables = ["users", "settings", "routers", "models", "history"]
        for table in tables:
            await self.execute(f"DELETE FROM {table}")
        if not self.use_cloud:
            for table in tables:
                await self.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}'")
        logging.info("All tables truncated (cache cleared).")

db = DatabaseManager()

# ------------------------------
# Emoji pool for models
# ------------------------------
MODEL_EMOJIS = [
    "🧠", "🤖", "🚀", "💡", "⚡", "🔥", "🌟", "💎",
    "📡", "🛸", "🧩", "🎯", "🏆", "🎓", "🧬", "🔮",
    "🌀", "🌈", "💫", "🎨", "🦾", "🧿", "⚙️", "📊"
]

def get_model_emoji(model_id: int) -> str:
    return MODEL_EMOJIS[model_id % len(MODEL_EMOJIS)]

# ------------------------------
# Multi‑language dictionary (all changes applied)
# ------------------------------
LANGS = {
    "en": {
        "name": "🇬🇧 English",
        "welcome_new": "Please select your language:",
        "welcome_back": "Welcome back, {name}!",
        "locked": "⛔ Unauthorized. Please enter the password:",
        "pwd_ok": "✅ Password accepted!",
        "pwd_err": "❌ Incorrect password.",
        "pwd_none": "🔓 Password requirement removed. Bot is public.",
        "pwd_set": "✅ New password set: `{}`",
        "admin_only": "❌ Admin only.",
        "type_here": "Type your message...",
        "select_model": "Select an AI model to start a NEW chat:",
        "no_models_admin": "⚠️ No models found. Send /admin to manage.",
        "no_models_user": "⚠️ No AI models are currently available.",
        "chat_started": "✅ Connected to {}.\nSend your message:",
        "invalid_url": "❌ Invalid URL format. Please send a valid Base URL (http/https):",
        "admin_menu": "⚙️ Admin Panel, use the menu below.",
        "btn_routers": "🗂 API List",
        "btn_add_router": "➕ Add Router",
        "btn_settings": "⚙️ Settings",
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
        "router_added": "✅ Router and Model added successfully!",
        "router_details": "📌 **Router:** {}\n🌐 Base URL: `{}`\n🔑 Token: `{}`\n\n📦 **Models (copy any name):**\n```\n{}\n```",
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
        "btn_clear_remote": "🧹 Clear Cache",
        "clear_confirm": "⚠️ This will delete ALL data from the external database (users, settings, routers, models, history). Are you sure?",
        "clear_done": "✅ All remote data has been cleared.",
        "clear_cancelled": "❌ Operation cancelled.",
        "btn_admin_panel": "⚙️ Admin Panel"
    },
    "fa": {
        "name": "🇮🇷🇦🇫 فارسی",
        "welcome_new": "لطفاً زبان خود را انتخاب کنید:",
        "welcome_back": "خوش برگشتی، {name}!",
        "locked": "⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور را وارد کنید:",
        "pwd_ok": "✅ رمز عبور تایید شد!",
        "pwd_err": "❌ رمز اشتباه است.",
        "pwd_none": "🔓 قفل ربات برداشته شد. استفاده برای همه آزاد است.",
        "pwd_set": "✅ رمز عبور جدید تنظیم شد: `{}`",
        "admin_only": "❌ دسترسی فقط برای مدیریت.",
        "type_here": "پیام خود را بنویسید...",
        "select_model": "برای شروع یک چت جدید، مدل را انتخاب کنید:",
        "no_models_admin": "⚠️ هیچ مدلی وجود ندارد. برای مدیریت /admin را ارسال کنید.",
        "no_models_user": "⚠️ در حال حاضر هیچ مدلی در دسترس نیست.",
        "chat_started": "✅ شما به {} متصل شدید.\nپیام خود را بفرستید:",
        "invalid_url": "❌ فرمت لینک اشتباه است. لطفاً یک URL معتبر بفرستید:",
        "admin_menu": "⚙️ پنل مدیریت، از منو پایین استفاده کنید.",
        "btn_routers": "🗂 APIها",
        "btn_add_router": "➕ روتر جدید",
        "btn_settings": "⚙️ تنظیمات",
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
        "router_added": "✅ روتر و مدل با موفقیت اضافه شدند!",
        "router_details": "📌 **روتر:** {}\n🌐 آدرس: `{}`\n🔑 توکن: `{}`\n\n📦 **مدل‌ها (برای کپی کردن):**\n```\n{}\n```",
        "btn_add_mod": "➕ مدل",
        "btn_del_mod": "🗑 حذف مدل",
        "btn_del_router": "🗑 حذف روتر",
        "del_confirm_msg": "⚠️ آیا از حذف این روتر مطمئن هستید؟",
        "btn_yes": "✅ بله",
        "btn_no": "❌ خیر",
        "del_success": "✅ حذف شد.",
        "pls_select_model": "لطفاً یک مدل معتبر انتخاب کنید.",
        "invalid_command": "❌ لطفاً از دستورات منطقی استفاده کنید.",
        "send_channel_prompt": "آیدی کانال را با @ بفرستید (یا none برای غیرفعال‌سازی):",
        "channel_set": "✅ کانال اجباری تنظیم شد: `{}`",
        "channel_none": "🔓 کانال اجباری غیرفعال شد.",
        "must_join": "⛔ برای استفاده از ربات، باید در کانال ما عضو باشید:",
        "btn_join_channel": "🔗 عضویت در کانال",
        "btn_check_join": "🔄 بررسی عضویت",
        "join_ok": "✅ عضویت تایید شد! حالا می‌توانید استفاده کنید.",
        "join_fail": "❌ شما هنوز در کانال عضو نشده‌اید!",
        "send_del_model": "نام دقیق مدلی که می‌خواهید حذف کنید را بفرستید:",
        "model_deleted": "✅ مدل با موفقیت حذف شد.",
        "model_not_found": "❌ مدلی با این نام یافت نشد.",
        "btn_user_mode": "👤 حالت کاربری",
        "btn_clear_remote": "🧹 پاک‌سازی کش",
        "clear_confirm": "⚠️ این کار تمام داده‌های دیتابیس خارجی (کاربران، تنظیمات، روترها، مدل‌ها و تاریخچه) را حذف می‌کند. مطمئن هستید؟",
        "clear_done": "✅ تمام داده‌های خارجی پاک شدند.",
        "clear_cancelled": "❌ عملیات لغو شد.",
        "btn_admin_panel": "⚙️ پنل مدیریت"
    },
    "ru": {
        "name": "🇷🇺 Русский",
        "welcome_new": "Пожалуйста, выберите язык:",
        "welcome_back": "С возвращением, {name}!",
        "locked": "⛔ Доступ ограничен. Введите пароль:",
        "pwd_ok": "✅ Пароль принят!",
        "pwd_err": "❌ Неверный пароль.",
        "pwd_none": "🔓 Пароль удален. Бот общедоступен.",
        "pwd_set": "✅ Новый пароль: `{}`",
        "admin_only": "❌ Только для админа.",
        "type_here": "Введите сообщение...",
        "select_model": "Выберите модель для нового чата:",
        "no_models_admin": "⚠️ Модели не найдены. /admin",
        "no_models_user": "⚠️ Нет доступных моделей.",
        "chat_started": "✅ Подключено к {}.\nОтправьте сообщение:",
        "invalid_url": "❌ Неверный URL.",
        "admin_menu": "⚙️ Панель администратора.",
        "btn_routers": "🗂 Список API",
        "btn_add_router": "➕ Добавить роутер",
        "btn_settings": "⚙️ Настройки",
        "btn_set_pwd": "🔐 Пароль",
        "btn_set_channel": "📢 Канал",
        "btn_broadcast": "📢 Рассылка",
        "btn_back": "🔙 Назад",
        "btn_back_main": "🏠 Главное меню",
        "send_pwd_prompt": "Введите новый пароль (или none):",
        "send_broadcast": "Введите сообщение для рассылки:",
        "broadcast_done": "✅ Отправлено: {}.",
        "send_url": "Введите Base URL:",
        "url_detected": "Домен: {}\nВведите API ключ:",
        "send_model": "Введите название модели:",
        "router_added": "✅ Успешно!",
        "router_details": "📌 **Роутер:** {}\n🌐 URL: `{}`\n🔑 Токен: `{}`\n\n📦 **Модели (копируйте):**\n```\n{}\n```",
        "btn_add_mod": "➕ Модель",
        "btn_del_mod": "🗑 Удалить",
        "btn_del_router": "🗑 Роутер",
        "del_confirm_msg": "⚠️ Вы уверены?",
        "btn_yes": "✅ Да",
        "btn_no": "❌ Нет",
        "del_success": "✅ Удалено.",
        "pls_select_model": "Выберите модель.",
        "invalid_command": "❌ Неверная команда.",
        "send_channel_prompt": "Отправьте юзернейм канала (@channel) или none:",
        "channel_set": "✅ Канал установлен: `{}`",
        "channel_none": "🔓 Подписка отключена.",
        "must_join": "⛔ Подпишитесь на канал:",
        "btn_join_channel": "🔗 Подписаться",
        "btn_check_join": "🔄 Проверить",
        "join_ok": "✅ Проверка пройдена!",
        "join_fail": "❌ Вы еще не подписались!",
        "send_del_model": "Точное имя модели для удаления:",
        "model_deleted": "✅ Удалена.",
        "model_not_found": "❌ Не найдена.",
        "btn_user_mode": "👤 Режим пользователя",
        "btn_clear_remote": "🧹 Очистить кэш",
        "clear_confirm": "⚠️ Это удалит все данные из внешней БД. Уверены?",
        "clear_done": "✅ Готово.",
        "clear_cancelled": "❌ Отменено.",
        "btn_admin_panel": "⚙️ Панель администратора"
    },
    "ar": {
        "name": "🇸🇦 العربية",
        "welcome_new": "يرجى اختيار لغتك:",
        "welcome_back": "أهلاً بك مجدداً، {name}!",
        "locked": "⛔ غير مصرح. أدخل كلمة المرور:",
        "pwd_ok": "✅ تم القبول!",
        "pwd_err": "❌ خطأ.",
        "pwd_none": "🔓 تمت إزالة كلمة المرور.",
        "pwd_set": "✅ كلمة المرور الجديدة: `{}`",
        "admin_only": "❌ للمسؤولين فقط.",
        "type_here": "اكتب رسالتك...",
        "select_model": "اختر نموذج لبدء محادثة جديدة:",
        "no_models_admin": "⚠️ لا توجد نماذج. أرسل /admin",
        "no_models_user": "⚠️ لا توجد نماذج متاحة.",
        "chat_started": "✅ متصل بـ {}.\nأرسل رسالتك:",
        "invalid_url": "❌ رابط غير صالح.",
        "admin_menu": "⚙️ لوحة الإدارة.",
        "btn_routers": "🗂 قائمة API",
        "btn_add_router": "➕ إضافة موجه",
        "btn_settings": "⚙️ الإعدادات",
        "btn_set_pwd": "🔐 كلمة المرور",
        "btn_set_channel": "📢 قناة إجبارية",
        "btn_broadcast": "📢 إرسال للكل",
        "btn_back": "🔙 رجوع",
        "btn_back_main": "🏠 القائمة الرئيسية",
        "send_pwd_prompt": "أدخل كلمة المرور الجديدة (أو none):",
        "send_broadcast": "أدخل رسالة البث:",
        "broadcast_done": "✅ تم الإرسال إلى {}.",
        "send_url": "أدخل Base URL:",
        "url_detected": "النطاق: {}\nأدخل مفتاح API:",
        "send_model": "أدخل اسم النموذج:",
        "router_added": "✅ تمت الإضافة!",
        "router_details": "📌 **الموجه:** {}\n🌐 الرابط: `{}`\n🔑 الرمز: `{}`\n\n📦 **النماذج (انسخ):**\n```\n{}\n```",
        "btn_add_mod": "➕ إضافة نموذج",
        "btn_del_mod": "🗑 حذف نموذج",
        "btn_del_router": "🗑 حذف الموجه",
        "del_confirm_msg": "⚠️ هل أنت متأكد؟",
        "btn_yes": "✅ نعم",
        "btn_no": "❌ لا",
        "del_success": "✅ تم الحذف.",
        "pls_select_model": "يرجى اختيار نموذج.",
        "invalid_command": "❌ أمر غير صالح.",
        "send_channel_prompt": "أرسل معرف القناة (@channel) أو none:",
        "channel_set": "✅ تم تعيين القناة: `{}`",
        "channel_none": "🔓 تم إلغاء القناة الإجبارية.",
        "must_join": "⛔ يجب الاشتراك في القناة أولاً:",
        "btn_join_channel": "🔗 اشترك",
        "btn_check_join": "🔄 تحقق",
        "join_ok": "✅ تم التحقق!",
        "join_fail": "❌ لم تشترك بعد!",
        "send_del_model": "أرسل الاسم الدقيق للنموذج:",
        "model_deleted": "✅ تم الحذف.",
        "model_not_found": "❌ غير موجود.",
        "btn_user_mode": "👤 وضع المستخدم",
        "btn_clear_remote": "🧹 مسح الكاش",
        "clear_confirm": "⚠️ سيتم حذف جميع البيانات. متأكد؟",
        "clear_done": "✅ تم المسح.",
        "clear_cancelled": "❌ ألغي.",
        "btn_admin_panel": "⚙️ لوحة الإدارة"
    },
    "hi": {
        "name": "🇮🇳 हिन्दी",
        "welcome_new": "कृपया अपनी भाषा चुनें:",
        "welcome_back": "वापसी पर स्वागत है, {name}!",
        "locked": "🔑 पासवर्ड दर्ज करें:",
        "pwd_ok": "✅ स्वीकृत!",
        "pwd_err": "❌ गलत।",
        "pwd_none": "🔓 पासवर्ड हटाया गया।",
        "pwd_set": "✅ नया पासवर्ड: `{}`",
        "admin_only": "❌ केवल व्यवस्थापक।",
        "type_here": "संदेश लिखें...",
        "select_model": "नया चैट शुरू करने के लिए मॉडल चुनें:",
        "no_models_admin": "⚠️ कोई मॉडल नहीं। /admin भेजें।",
        "no_models_user": "⚠️ कोई मॉडल उपलब्ध नहीं।",
        "chat_started": "✅ {} से कनेक्टेड।\nसंदेश भेजें:",
        "invalid_url": "❌ अमान्य URL۔",
        "admin_menu": "⚙️ एडमिन पैनल।",
        "btn_routers": "🗂 API सूची",
        "btn_add_router": "➕ राउटर जोड़ें",
        "btn_settings": "⚙️ सेटिंग्स",
        "btn_set_pwd": "🔐 पासवर्ड",
        "btn_set_channel": "📢 चैनल",
        "btn_broadcast": "📢 प्रसारण",
        "btn_back": "🔙 पीछे",
        "btn_back_main": "🏠 मुख्य मेनू",
        "send_pwd_prompt": "नया पासवर्ड भेजें (या none):",
        "send_broadcast": "संदेश भेजें:",
        "broadcast_done": "✅ {} को भेजा गया।",
        "send_url": "Base URL भेजें:",
        "url_detected": "डोमेन: {}\nAPI कुंजी भेजें:",
        "send_model": "मॉडल का नाम भेजें:",
        "router_added": "✅ जोड़ा गया!",
        "router_details": "📌 **राउटर:** {}\n🌐 URL: `{}`\n🔑 टोकन: `{}`\n\n📦 **मॉडल (कॉपी करें):**\n```\n{}\n```",
        "btn_add_mod": "➕ मॉडल",
        "btn_del_mod": "🗑 मॉडल हटाएं",
        "btn_del_router": "🗑 राउटर हटाएं",
        "del_confirm_msg": "⚠️ क्या आप सुनिश्चित हैं?",
        "btn_yes": "✅ हाँ",
        "btn_no": "❌ नहीं",
        "del_success": "✅ हटा दिया गया।",
        "pls_select_model": "मॉडल चुनें।",
        "invalid_command": "❌ अमान्य कमांड।",
        "send_channel_prompt": "चैनल का नाम (@channel) या none भेजें:",
        "channel_set": "✅ चैनल सेट: `{}`",
        "channel_none": "🔓 चैनल बंद।",
        "must_join": "⛔ पहले चैनल से जुड़ें:",
        "btn_join_channel": "🔗 जुड़ें",
        "btn_check_join": "🔄 जांचें",
        "join_ok": "✅ सदस्यता सत्यापित!",
        "join_fail": "❌ आप अभी तक नहीं जुड़े हैं!",
        "send_del_model": "हटाने के लिए सटीक मॉडल नाम:",
        "model_deleted": "✅ हटाया गया।",
        "model_not_found": "❌ नहीं मिला।",
        "btn_user_mode": "👤 उपयोगकर्ता मोड",
        "btn_clear_remote": "🧹 कैश साफ़ करें",
        "clear_confirm": "⚠️ सारा डेटा डिलीट हो जाएगा। क्या आप निश्चित हैं?",
        "clear_done": "✅ साफ़ हो गया।",
        "clear_cancelled": "❌ रद्द।",
        "btn_admin_panel": "⚙️ व्यवस्थापक पैनल"
    },
    "tr": {
        "name": "🇹🇷 Türkçe",
        "welcome_new": "Lütfen dilinizi seçin:",
        "welcome_back": "Tekrar hoş geldiniz, {name}!",
        "locked": "⛔ Şifreyi girin:",
        "pwd_ok": "✅ Kabul edildi!",
        "pwd_err": "❌ Yanlış.",
        "pwd_none": "🔓 Şifre kaldırıldı.",
        "pwd_set": "✅ Yeni şifre: `{}`",
        "admin_only": "❌ Sadece yönetici.",
        "type_here": "Mesajınızı yazın...",
        "select_model": "Yeni bir sohbet için model seçin:",
        "no_models_admin": "⚠️ Model yok. /admin",
        "no_models_user": "⚠️ Model yok.",
        "chat_started": "✅ {} bağlanıldı.\nMesajınızı gönderin:",
        "invalid_url": "❌ Geçersiz URL.",
        "admin_menu": "⚙️ Yönetici Paneli.",
        "btn_routers": "🗂 API Listesi",
        "btn_add_router": "➕ Yönlendirici",
        "btn_settings": "⚙️ Ayarlar",
        "btn_set_pwd": "🔐 Şifre",
        "btn_set_channel": "📢 Kanal",
        "btn_broadcast": "📢 Duyuru",
        "btn_back": "🔙 Geri",
        "btn_back_main": "🏠 Ana Menü",
        "send_pwd_prompt": "Yeni şifre (veya none):",
        "send_broadcast": "Duyuru gönderin:",
        "broadcast_done": "✅ {} kişiye gönderildi.",
        "send_url": "Base URL:",
        "url_detected": "Alan adı: {}\nAPI Anahtarı:",
        "send_model": "Model adını gönderin:",
        "router_added": "✅ Eklendi!",
        "router_details": "📌 **Yönlendirici:** {}\n🌐 URL: `{}`\n🔑 Token: `{}`\n\n📦 **Modeller (kopyala):**\n```\n{}\n```",
        "btn_add_mod": "➕ Model",
        "btn_del_mod": "🗑 Model Sil",
        "btn_del_router": "🗑 Yönlendirici Sil",
        "del_confirm_msg": "⚠️ Emin misiniz?",
        "btn_yes": "✅ Evet",
        "btn_no": "❌ Hayır",
        "del_success": "✅ Silindi.",
        "pls_select_model": "Model seçin.",
        "invalid_command": "❌ Geçersiz komut.",
        "send_channel_prompt": "Kanal adını (@channel) veya none:",
        "channel_set": "✅ Kanal ayarlandı: `{}`",
        "channel_none": "🔓 Zorunlu kanal iptal edildi.",
        "must_join": "⛔ Önce kanala katılın:",
        "btn_join_channel": "🔗 Katıl",
        "btn_check_join": "🔄 Kontrol Et",
        "join_ok": "✅ Katılım onaylandı!",
        "join_fail": "❌ Henüz katılmadınız!",
        "send_del_model": "Tam model adını gönderin:",
        "model_deleted": "✅ Silindi.",
        "model_not_found": "❌ Bulunamadı.",
        "btn_user_mode": "👤 Kullanıcı Modu",
        "btn_clear_remote": "🧹 Önbelleği Temizle",
        "clear_confirm": "⚠️ Tüm veriler silinecek. Emin misiniz?",
        "clear_done": "✅ Temizlendi.",
        "clear_cancelled": "❌ İptal.",
        "btn_admin_panel": "⚙️ Yönetici Paneli"
    },
    "fr": {
        "name": "🇫🇷 Français",
        "welcome_new": "Choisissez votre langue :",
        "welcome_back": "Bon retour, {name} !",
        "locked": "⛔ Entrez le mot de passe :",
        "pwd_ok": "✅ Accepté !",
        "pwd_err": "❌ Erreur.",
        "pwd_none": "🔓 MDP supprimé.",
        "pwd_set": "✅ Nouveau MDP : `{}`",
        "admin_only": "❌ Admin uniquement.",
        "type_here": "Tapez votre message...",
        "select_model": "Sélectionnez un modèle pour commencer :",
        "no_models_admin": "⚠️ Aucun modèle. /admin",
        "no_models_user": "⚠️ Aucun modèle.",
        "chat_started": "✅ Connecté à {}.\nEnvoyez votre message :",
        "invalid_url": "❌ URL invalide.",
        "admin_menu": "⚙️ Panneau d'administration.",
        "btn_routers": "🗂 Liste API",
        "btn_add_router": "➕ Routeur",
        "btn_settings": "⚙️ Paramètres",
        "btn_set_pwd": "🔐 MDP",
        "btn_set_channel": "📢 Canal",
        "btn_broadcast": "📢 Diffusion",
        "btn_back": "🔙 Retour",
        "btn_back_main": "🏠 Menu",
        "send_pwd_prompt": "Nouveau mot de passe (ou none) :",
        "send_broadcast": "Envoyez le message :",
        "broadcast_done": "✅ Envoyé à {}.",
        "send_url": "URL de base :",
        "url_detected": "Domaine : {}\nClé API :",
        "send_model": "Nom du modèle :",
        "router_added": "✅ Ajouté !",
        "router_details": "📌 **Routeur :** {}\n🌐 URL : `{}`\n🔑 Jeton : `{}`\n\n📦 **Modèles (copier) :**\n```\n{}\n```",
        "btn_add_mod": "➕ Modèle",
        "btn_del_mod": "🗑 Supprimer",
        "btn_del_router": "🗑 Supprimer Routeur",
        "del_confirm_msg": "⚠️ Sûr ?",
        "btn_yes": "✅ Oui",
        "btn_no": "❌ Non",
        "del_success": "✅ Supprimé.",
        "pls_select_model": "Choisissez un modèle.",
        "invalid_command": "❌ Commande invalide.",
        "send_channel_prompt": "Envoyez le nom du canal (@canal) ou none :",
        "channel_set": "✅ Canal défini : `{}`",
        "channel_none": "🔓 Canal désactivé.",
        "must_join": "⛔ Rejoignez le canal d'abord :",
        "btn_join_channel": "🔗 Rejoindre",
        "btn_check_join": "🔄 Vérifier",
        "join_ok": "✅ Abonnement vérifié !",
        "join_fail": "❌ Vous n'avez pas rejoint !",
        "send_del_model": "Nom exact du modèle :",
        "model_deleted": "✅ Supprimé.",
        "model_not_found": "❌ Introuvable.",
        "btn_user_mode": "👤 Mode utilisateur",
        "btn_clear_remote": "🧹 Vider le cache",
        "clear_confirm": "⚠️ Supprimer toutes les données ?",
        "clear_done": "✅ Fait.",
        "clear_cancelled": "❌ Annulé.",
        "btn_admin_panel": "⚙️ Panneau d'administration"
    },
    "de": {
        "name": "🇩🇪 Deutsch",
        "welcome_new": "Sprache wählen:",
        "welcome_back": "Willkommen, {name}!",
        "locked": "⛔ Passwort eingeben:",
        "pwd_ok": "✅ Akzeptiert!",
        "pwd_err": "❌ Falsch.",
        "pwd_none": "🔓 Passwort entfernt.",
        "pwd_set": "✅ Neues Passwort: `{}`",
        "admin_only": "❌ Nur Admin.",
        "type_here": "Nachricht...",
        "select_model": "Modell für neuen Chat wählen:",
        "no_models_admin": "⚠️ Keine Modelle. /admin",
        "no_models_user": "⚠️ Keine Modelle.",
        "chat_started": "✅ Verbunden mit {}.\nNachricht senden:",
        "invalid_url": "❌ Ungültige URL.",
        "admin_menu": "⚙️ Admin-Panel.",
        "btn_routers": "🗂 API-Liste",
        "btn_add_router": "➕ Router",
        "btn_settings": "⚙️ Einstellungen",
        "btn_set_pwd": "🔐 Passwort",
        "btn_set_channel": "📢 Kanal",
        "btn_broadcast": "📢 Broadcast",
        "btn_back": "🔙 Zurück",
        "btn_back_main": "🏠 Hauptmenü",
        "send_pwd_prompt": "Neues Passwort (oder none):",
        "send_broadcast": "Nachricht senden:",
        "broadcast_done": "✅ An {} gesendet.",
        "send_url": "Base URL:",
        "url_detected": "Domain: {}\nAPI-Key:",
        "send_model": "Modellname:",
        "router_added": "✅ Hinzugefügt!",
        "router_details": "📌 **Router:** {}\n🌐 URL: `{}`\n🔑 Token: `{}`\n\n📦 **Modelle (kopieren):**\n```\n{}\n```",
        "btn_add_mod": "➕ Modell",
        "btn_del_mod": "🗑 Modell löschen",
        "btn_del_router": "🗑 Router löschen",
        "del_confirm_msg": "⚠️ Sicher?",
        "btn_yes": "✅ Ja",
        "btn_no": "❌ Nein",
        "del_success": "✅ Gelöscht.",
        "pls_select_model": "Modell wählen.",
        "invalid_command": "❌ Ungültig.",
        "send_channel_prompt": "Kanalname (@kanal) oder none:",
        "channel_set": "✅ Kanal gesetzt: `{}`",
        "channel_none": "🔓 Pflichtkanal deaktiviert.",
        "must_join": "⛔ Bitte dem Kanal beitreten:",
        "btn_join_channel": "🔗 Beitreten",
        "btn_check_join": "🔄 Prüfen",
        "join_ok": "✅ Mitgliedschaft geprüft!",
        "join_fail": "❌ Sie sind noch nicht beigetreten!",
        "send_del_model": "Exakten Modellnamen:",
        "model_deleted": "✅ Gelöscht.",
        "model_not_found": "❌ Nicht gefunden.",
        "btn_user_mode": "👤 Benutzermodus",
        "btn_clear_remote": "🧹 Cache leeren",
        "clear_confirm": "⚠️ Alle Daten löschen? Sicher?",
        "clear_done": "✅ Erledigt.",
        "clear_cancelled": "❌ Abgebrochen.",
        "btn_admin_panel": "⚙️ Admin-Panel"
    },
    "zh": {
        "name": "🇨🇳 中文",
        "welcome_new": "请选择语言：",
        "welcome_back": "欢迎，{name}！",
        "locked": "⛔ 请输入密码：",
        "pwd_ok": "✅ 密码正确！",
        "pwd_err": "❌ 密码错误。",
        "pwd_none": "🔓 密码已移除。",
        "pwd_set": "✅ 新密码：`{}`",
        "admin_only": "❌ 仅限管理员。",
        "type_here": "输入消息...",
        "select_model": "选择模型以开始新聊天：",
        "no_models_admin": "⚠️ 无模型。发送 /admin",
        "no_models_user": "⚠️ 无可用模型。",
        "chat_started": "✅ 连接到 {}。\n发送您的消息：",
        "invalid_url": "❌ 无效 URL。",
        "admin_menu": "⚙️ 管理面板。",
        "btn_routers": "🗂 API 列表",
        "btn_add_router": "➕ 添加路由",
        "btn_settings": "⚙️ 设置",
        "btn_set_pwd": "🔐 密码",
        "btn_set_channel": "📢 频道",
        "btn_broadcast": "📢 广播",
        "btn_back": "🔙 返回",
        "btn_back_main": "🏠 主菜单",
        "send_pwd_prompt": "发送新密码（或 none）：",
        "send_broadcast": "发送广播：",
        "broadcast_done": "✅ 已发送给 {}。",
        "send_url": "Base URL：",
        "url_detected": "域：{}\nAPI 密钥：",
        "send_model": "模型名称：",
        "router_added": "✅ 添加成功！",
        "router_details": "📌 **路由：** {}\n🌐 地址：`{}`\n🔑 密钥：`{}`\n\n📦 **模型（复制）：**\n```\n{}\n```",
        "btn_add_mod": "➕ 模型",
        "btn_del_mod": "🗑 删除模型",
        "btn_del_router": "🗑 删除路由",
        "del_confirm_msg": "⚠️ 确定吗？",
        "btn_yes": "✅ 是",
        "btn_no": "❌ 否",
        "del_success": "✅ 已删除。",
        "pls_select_model": "请选择模型。",
        "invalid_command": "❌ 无效命令。",
        "send_channel_prompt": "发送频道名 (@channel) 或 none：",
        "channel_set": "✅ 频道已设置：`{}`",
        "channel_none": "🔓 强制订阅已关闭。",
        "must_join": "⛔ 必须先加入频道：",
        "btn_join_channel": "🔗 加入频道",
        "btn_check_join": "🔄 检查",
        "join_ok": "✅ 验证通过！",
        "join_fail": "❌ 您尚未加入！",
        "send_del_model": "要删除的准确模型名称：",
        "model_deleted": "✅ 已删除。",
        "model_not_found": "❌ 找不到模型。",
        "btn_user_mode": "👤 用户模式",
        "btn_clear_remote": "🧹 清除缓存",
        "clear_confirm": "⚠️ 将删除所有数据。确定吗？",
        "clear_done": "✅ 已清除。",
        "clear_cancelled": "❌ 已取消。",
        "btn_admin_panel": "⚙️ 管理面板"
    }
}

# ------------------------------
# Database initialization
# ------------------------------
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
    pwd_row = await db.fetchone("SELECT value FROM settings WHERE key = 'global_password'")
    if not pwd_row or not pwd_row[0] or pwd_row[0].lower() == 'none':
        return True
    auth_row = await db.fetchone("SELECT is_auth FROM users WHERE user_id = ?", (user_id,))
    return bool(auth_row and auth_row[0] == 1)

async def check_channel_join(user_id):
    if user_id == ADMIN_ID:
        return True, None
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

# ------------------------------
# FSM States
# ------------------------------
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
    admin_clear_remote_confirm = State()

# ------------------------------
# Keyboard builders
# ------------------------------
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
    builder.button(text=await get_text(user_id, "btn_set_pwd"), callback_data="admin_pwd")
    builder.button(text=await get_text(user_id, "btn_set_channel"), callback_data="admin_channel")
    builder.button(text=await get_text(user_id, "btn_broadcast"), callback_data="admin_broadcast")
    builder.button(text=await get_text(user_id, "btn_clear_remote"), callback_data="admin_clear_remote")
    builder.button(text=await get_text(user_id, "btn_back_main"), callback_data="admin_back")
    builder.adjust(2, 2, 1)  # 2-2-1 layout
    return builder.as_markup()

def cancel_admin_keyboard(user_id, text_back):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text_back, callback_data="admin_back")]])

# ------------------------------
# User panel with pagination & admin button
# ------------------------------
async def show_user_panel(message, user_id, page=0, is_admin_view=False):
    joined, channel = await check_channel_join(user_id)
    if not joined:
        txt = await get_text(user_id, "must_join")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=await get_text(user_id, "btn_join_channel"), url=f"https://t.me/{channel.replace('@', '')}")],
            [InlineKeyboardButton(text=await get_text(user_id, "btn_check_join"), callback_data="check_join_channel")]
        ])
        await message.answer(f"{txt}\n{channel}", reply_markup=kb)
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
            emoji = get_model_emoji(m_id)
            row.append(InlineKeyboardButton(text=f"{emoji} {m_name}", callback_data=f"selmod_{m_id}"))
        buttons.append(row)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"userpage_{page-1}"))
    if page < max_page:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"userpage_{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    # If admin is viewing, add a back button
    if is_admin_view:
        back_text = await get_text(user_id, "btn_back_main")
        buttons.append([InlineKeyboardButton(text=back_text, callback_data="admin_back")])
    else:
        # If user is admin, add an admin panel button at the bottom
        if user_id == ADMIN_ID:
            admin_btn_text = await get_text(user_id, "btn_admin_panel")
            buttons.append([InlineKeyboardButton(text=admin_btn_text, callback_data="go_admin_panel")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    select_text = await get_text(user_id, "select_model")
    if total == 0:
        select_text = await get_text(user_id, "no_models_user") if not is_admin_view else await get_text(user_id, "no_models_admin")
    await message.answer(select_text, reply_markup=kb)

# ------------------------------
# Language & Start Handlers
# ------------------------------
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_exists = await db.fetchone("SELECT lang FROM users WHERE user_id = ?", (message.from_user.id,))
    if not user_exists:
        await db.execute("INSERT OR IGNORE INTO users (user_id, lang) VALUES (?, ?)", (message.from_user.id, "en"))
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

# ------------------------------
# User commands (case-insensitive)
# ------------------------------
@router.message(Command("user"))
@router.message(F.text.lower().in_({"user", "/user"}))
async def cmd_user(message: Message, state: FSMContext):
    await state.clear()
    await show_user_panel(message, message.from_user.id)

# ------------------------------
# Check join callback
# ------------------------------
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

# ------------------------------
# Go to admin panel from user view
# ------------------------------
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

# ------------------------------
# Model selection (silent clear)
# ------------------------------
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

    # Silently clear history and set new model
    await db.execute("UPDATE users SET current_model_id = ? WHERE user_id = ?", (model_id, user_id))
    await db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))

    # Only notify about connection, not about clearing
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

# ------------------------------
# Model exit – no message, just clear and show panel
# ------------------------------
@router.message(Command("model"))
@router.message(F.text.lower().in_({"model", "/model"}))
async def cmd_model_exit(message: Message, state: FSMContext):
    await state.clear()
    await db.execute("DELETE FROM history WHERE user_id = ?", (message.from_user.id,))
    # Do NOT send any "cleared" message; just show the model list
    await show_user_panel(message, message.from_user.id)

# ------------------------------
# Admin commands (case-insensitive)
# ------------------------------
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

# ------------------------------
# Admin navigation
# ------------------------------
@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    admin_text = await get_text(callback.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)

@router.callback_query(F.data == "admin_settings_menu")
async def admin_settings_menu(callback: CallbackQuery):
    admin_text = await get_text(callback.from_user.id, "btn_settings") + " ⚙️:"
    kb = await admin_settings_keyboard(callback.from_user.id)
    await callback.message.edit_text(admin_text, reply_markup=kb)

@router.callback_query(F.data == "admin_switch_user")
async def admin_switch_user(callback: CallbackQuery):
    await callback.message.delete()
    await show_user_panel(callback.message, callback.from_user.id, is_admin_view=True)
    await callback.answer()

@router.callback_query(F.data.startswith("userpage_"))
async def user_page_callback(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    await callback.message.delete()
    await show_user_panel(callback.message, callback.from_user.id, page=page, is_admin_view=True)
    await callback.answer()

# ------------------------------
# Admin: Password
# ------------------------------
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

# ------------------------------
# Admin: Force Channel
# ------------------------------
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

# ------------------------------
# Admin: Broadcast
# ------------------------------
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

# ------------------------------
# Admin: Clear Remote Cache (external DB)
# ------------------------------
@router.callback_query(F.data == "admin_clear_remote")
async def admin_clear_remote_start(callback: CallbackQuery, state: FSMContext):
    if not db.use_cloud:
        await callback.answer("⚠️ No external cloud DB configured.", show_alert=True)
        return
    confirm_txt = await get_text(callback.from_user.id, "clear_confirm")
    btn_yes = await get_text(callback.from_user.id, "btn_yes")
    btn_no = await get_text(callback.from_user.id, "btn_no")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn_yes, callback_data="clear_remote_yes")],
        [InlineKeyboardButton(text=btn_no, callback_data="clear_remote_no")]
    ])
    await callback.message.edit_text(confirm_txt, reply_markup=kb)
    await state.set_state(BotStates.admin_clear_remote_confirm)

@router.callback_query(F.data == "clear_remote_yes")
async def clear_remote_yes(callback: CallbackQuery, state: FSMContext):
    await db.truncate_all_tables()
    done_txt = await get_text(callback.from_user.id, "clear_done")
    await callback.answer(done_txt, show_alert=True)
    await state.clear()
    await admin_settings_menu(callback)

@router.callback_query(F.data == "clear_remote_no")
async def clear_remote_no(callback: CallbackQuery, state: FSMContext):
    cancel_txt = await get_text(callback.from_user.id, "clear_cancelled")
    await callback.answer(cancel_txt, show_alert=True)
    await state.clear()
    await admin_settings_menu(callback)

# ------------------------------
# Admin: Routers and Models (monospace)
# ------------------------------
@router.callback_query(F.data == "admin_routers")
async def admin_routers_list(callback: CallbackQuery):
    buttons = []
    routers = await db.fetchall("SELECT id, domain FROM routers")
    for r_id, domain in routers:
        buttons.append([InlineKeyboardButton(text=domain, callback_data=f"router_{r_id}")])
    btn_back = await get_text(callback.from_user.id, "btn_back_main")
    buttons.append([InlineKeyboardButton(text=btn_back, callback_data="admin_back")])
    txt = await get_text(callback.from_user.id, "btn_routers")
    await callback.message.edit_text(txt + ":", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("router_"))
async def admin_router_details(callback: CallbackQuery):
    r_id = callback.data.split("_")[1]
    r = await db.fetchone("SELECT domain, base_url, api_key FROM routers WHERE id = ?", (r_id,))
    models = await db.fetchall("SELECT id, model_name FROM models WHERE router_id = ?", (r_id,))
    if not r:
        return
    model_names = "\n".join([m[1] for m in models]) if models else "(no models)"
    txt_template = await get_text(callback.from_user.id, "router_details")
    msg = txt_template.format(r[0], r[1], r[2], model_names)

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

# ------------------------------
# Admin: Add Router
# ------------------------------
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

# ------------------------------
# Main chat handler
# ------------------------------
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
        buttons = [[InlineKeyboardButton(text=m_name, callback_data=f"selmod_{m_id}")] for m_id, m_name in models]
        invalid_txt = await get_text(user_id, "invalid_command")
        select_txt = await get_text(user_id, "pls_select_model")
        await message.answer(f"{invalid_txt}\n\n{select_txt}", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
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

# ------------------------------
# Main runner
# ------------------------------
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
