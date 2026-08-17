import os
import re
import json
import math
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

# ================= تشخیص خودکار ایموجی مدل‌ها =================
def get_model_emoji(model_name: str) -> str:
    name = model_name.lower()
    if "gpt" in name or "openai" in name:
        return "🤖"
    elif "claude" in name or "anthropic" in name:
        return "🎭"
    elif "gemini" in name or "google" in name:
        return "💎"
    elif "llama" in name or "meta" in name:
        return "🦙"
    elif "deepseek" in name:
        return "🐳"
    elif "mistral" in name or "mixtral" in name:
        return "🌪"
    elif "qwen" in name:
        return "🐉"
    elif "vision" in name or "image" in name or "4o" in name:
        return "👁"
    elif "flux" in name or "dall" in name or "midjourney" in name:
        return "🎨"
    else:
        return "⚡"

# ================= فیلتر هوشمند دستورات =================
def text_cmd_filter(cmd_name: str):
    cmd = cmd_name.lower()
    return F.text.func(lambda t: t is not None and t.strip().lower().lstrip('/') == cmd)

# ================= دیکشنری کامل ۹ زبان =================
LANGS = {
    "en": {
        "name": "🇬🇧 English", "welcome_new": "Please select your preferred language:", "welcome_back": "Welcome back to system, {name}!",
        "locked": "⛔ Unauthorized access detected. Please enter the valid password:", "pwd_ok": "✅ Password verified successfully!", "pwd_err": "❌ Incorrect password provided.",
        "pwd_none": "🔓 Password protection removed. Bot is now open.", "pwd_set": "✅ New access password set: `{}`",
        "exit": "🧹 Conversation history cleared. Returning to models list.", "admin_only": "❌ Access denied. Admin only area.", "type_here": "Type your message below...",
        "select_model": "✨ Select an AI model below to start a new conversation:", "no_models_admin": "⚠️ No AI models found. Send /admin to manage models.",
        "no_models_user": "⚠️ No AI models are currently available in the system.", "chat_started": "✅ Successfully connected to {}.\n🧹 Previous chat history cleared. Send your message:",
        "invalid_url": "❌ Invalid URL format. Please send a valid Base URL address:",
        "admin_menu": "⚙️ Welcome to Admin Control Panel, select an option below:", "btn_routers": "🗂 Available APIs List in Bot:", "btn_add_router": "➕ Add New Router",
        "btn_settings": "⚙️ System Settings Menu", "btn_set_pwd": "🔐 Access Password", "btn_set_channel": "📢 Force Channel Join", "btn_broadcast": "📢 Broadcast Message", 
        "btn_user_mode": "👤 Switch to User Mode", "btn_back": "🔙 Return Previous Menu", "btn_back_main": "🏠 Return Main Panel", "send_pwd_prompt": "🔐 Please send the new access password (or 'none'):",
        "send_broadcast": "📢 Please enter the message you want to broadcast:", "broadcast_done": "✅ Broadcast successfully sent to {} active users.",
        "send_url": "🌐 Please send the precise Base URL address:", "url_detected": "Domain detected: {}\nNow send the API Key Token:",
        "send_model": "API Key saved.\nNow send the exact AI Model Name:", "router_added": "✅ Router and Model successfully registered!",
        "router_details": "📌 **Router Domain:** {}\n🌐 Base URL: `{}`\n🔑 API Token: `{}`\n\n📦 **Configured Models:**",
        "btn_add_mod": "➕ Add Model", "btn_del_mod": "🗑 Delete Model", "btn_del_router": "🗑 Delete Router", 
        "del_confirm_msg": "⚠️ Are you sure you want to delete this router?",
        "btn_yes": "✅ Yes Confirm", "btn_no": "❌ No Cancel", "del_success": "✅ Router deleted successfully.", "pls_select_model": "Please select a valid AI model from list.",
        "invalid_command": "❌ Invalid action. Please choose a valid command.", "send_channel_prompt": "📢 Please send the channel username (e.g. @Channel) or 'none':",
        "channel_set": "✅ Mandatory join channel set to: `{}`", "channel_none": "🔓 Mandatory channel join disabled.",
        "must_join": "⛔ Mandatory membership required. Join our channel to continue:", "btn_join_channel": "🔗 Join Channel Now",
        "btn_check_join": "🔄 Verify My Membership", "join_ok": "✅ Membership confirmed! You can use bot now.", "join_fail": "❌ You have not joined our channel yet!",
        "send_del_model": "🗑 Send the exact name of the model you want to delete:",
        "model_deleted": "✅ Model deleted successfully.", "model_not_found": "❌ Specified model name not found."
    },
    "fa": {
        "name": "🇮🇷 فارسی", "welcome_new": "لطفاً زبان مورد نظر خود را انتخاب کنید:", "welcome_back": "خوش آمدید، کاربر گرامی {name}!",
        "locked": "⛔ دسترسی غیرمجاز. لطفاً رمز عبور صحیح را وارد کنید:", "pwd_ok": "✅ رمز عبور با موفقیت تایید شد!", "pwd_err": "❌ رمز عبور وارد شده اشتباه است.",
        "pwd_none": "🔓 قفل دسترسی ربات برداشته شد. استفاده برای عموم آزاد است.", "pwd_set": "✅ رمز عبور جدید تنظیم گردید: `{}`",
        "exit": "🧹 تاریخچه مکالمه پاکسازی شد. بازگشت به لیست مدل‌ها.", "admin_only": "❌ دسترسی محدود به مدیریت سیستم می‌باشد.", "type_here": "پیام خود را بنویسید...",
        "select_model": "✨ جهت شروع گفتگو جدید، یک مدل هوش مصنوعی انتخاب کنید:", "no_models_admin": "⚠️ هیچ مدلی یافت نشد. جهت مدیریت /admin را ارسال فرمایید.",
        "no_models_user": "⚠️ در حال حاضر هیچ مدلی در سیستم فعال نمی‌باشد.", "chat_started": "✅ شما به مدل {} متصل شدید.\n🧹 تاریخچه قبلی پاک شد. پیام خود را ارسال کنید:",
        "invalid_url": "❌ فرمت لینک معتبر نیست. لطفاً یک آدرس وب معتبر ارسال کنید:",
        "admin_menu": "⚙️ به پنل مدیریت خوش آمدید، از منوی زیر انتخاب کنید:", "btn_routers": "🗂 لیست API های موجود در ربات :", "btn_add_router": "➕ افزودن روتر جدید",
        "btn_settings": "⚙️ تنظیمات فنی سیستم", "btn_set_pwd": "🔐 رمز عبور", "btn_set_channel": "📢 کانال اجباری", "btn_broadcast": "📢 پیام همگانی", 
        "btn_user_mode": "👤 حالت کاربری", "btn_back": "🔙 بازگشت به قبل", "btn_back_main": "🏠 منوی اصلی مدیریت", "send_pwd_prompt": "🔐 لطفاً رمز عبور جدید ربات را ارسال کنید (یا none):",
        "send_broadcast": "📢 لطفاً پیام همگانی خود را جهت ارسال عمومی وارد کنید:", "broadcast_done": "✅ پیام همگانی با موفقیت به {} کاربر ارسال گردید.",
        "send_url": "🌐 لطفاً آدرس دقیق Base URL را ارسال نمایید:", "url_detected": "دامنه شناسایی شد: {}\nحالا کلید API (توکن) را بفرستید:",
        "send_model": "توکن با موفقیت ثبت شد.\nحالا نام دقیق مدل هوش مصنوعی را بفرستید:", "router_added": "✅ روتر و مدل جدید با موفقیت اضافه شدند!",
        "router_details": "📌 **دامنه روتر:** {}\n🌐 آدرس بیس: `{}`\n🔑 توکن ارتباطی: `{}`\n\n📦 **مدل‌های فعال:**",
        "btn_add_mod": "➕ افزودن مدل", "btn_del_mod": "🗑 حذف مدل", "btn_del_router": "🗑 حذف روتر", 
        "del_confirm_msg": "⚠️ آیا از حذف کامل این روتر و مدل‌های آن اطمینان دارید؟",
        "btn_yes": "✅ بله تایید می‌کنم", "btn_no": "❌ خیر انصراف", "del_success": "✅ روتر مورد نظر حذف گردید.", "pls_select_model": "لطفاً یک مدل معتبر از لیست انتخاب کنید.",
        "invalid_command": "❌ دستور وارد شده معتبر نمی‌باشد.", "send_channel_prompt": "📢 لطفاً آیدی کانال اجباری را بفرستید (یا none):",
        "channel_set": "✅ کانال عضویت اجباری تنظیم شد: `{}`", "channel_none": "🔓 قفل عضویت اجباری کانال غیرفعال شد.",
        "must_join": "⛔ جهت استفاده از ربات، ابتدا باید در کانال ما عضو شوید:", "btn_join_channel": "🔗 عضویت در کانال رسمی",
        "btn_check_join": "🔄 بررسی وضعیت عضویت", "join_ok": "✅ عضویت شما تایید شد! هم‌اکنون می‌توانید استفاده کنید.", "join_fail": "❌ شما هنوز در کانال رسمی عضو نشده‌اید!",
        "send_del_model": "🗑 نام دقیق مدلی که می‌خواهید حذف کنید را بفرستید:",
        "model_deleted": "✅ مدل مورد نظر با موفقیت حذف شد.", "model_not_found": "❌ مدلی با این نام یافت نشد."
    },
    "ru": {
        "name": "🇷🇺 Русский", "welcome_new": "Пожалуйста, выберите ваш язык:", "welcome_back": "С возвращением в систему, {name}!",
        "locked": "⛔ Доступ ограничен. Введите правильный пароль:", "pwd_ok": "✅ Пароль успешно подтвержден!", "pwd_err": "❌ Введен неверный пароль.",
        "pwd_none": "🔓 Ограничение по паролю снято.", "pwd_set": "✅ Установлен новый пароль: `{}`",
        "exit": "🧹 История диалога очищена. Возврат к списку моделей.", "admin_only": "❌ Доступ разрешен только администраторам.", "type_here": "Введите ваше сообщение...",
        "select_model": "✨ Выберите модель ИИ для начала разговора:", "no_models_admin": "⚠️ Модели не найдены. Отправьте /admin для управления.",
        "no_models_user": "⚠️ В системе нет доступных моделей.", "chat_started": "✅ Вы успешно подключены к {}.\n🧹 История очищена.",
        "invalid_url": "❌ Неверный формат URL. Введите корректный адрес:",
        "admin_menu": "⚙️ Добро пожаловать в панель управления:", "btn_routers": "🗂 Список API в боте:", "btn_add_router": "➕ Добавить роутер",
        "btn_settings": "⚙️ Системные настройки", "btn_set_pwd": "🔐 Пароль доступа", "btn_set_channel": "📢 Подписка на канал", "btn_broadcast": "📢 Массовая рассылка", 
        "btn_user_mode": "👤 Режим пользователя", "btn_back": "🔙 Назад", "btn_back_main": "🏠 Главное меню", "send_pwd_prompt": "🔐 Введите новый пароль (или none):",
        "send_broadcast": "📢 Введите текст сообщения для рассылки:", "broadcast_done": "✅ Рассылка успешно отправлена {} пользователям.",
        "send_url": "🌐 Введите точный Base URL адрес:", "url_detected": "Домен: {}\nТеперь отправьте API токен:",
        "send_model": "Токен сохранен.\nТеперь введите точное имя модели:", "router_added": "✅ Роутер и модель успешно добавлены!",
        "router_details": "📌 **Роутер:** {}\n🌐 Base URL: `{}`\n🔑 API Токен: `{}`\n\n📦 **Активные модели:**",
        "btn_add_mod": "➕ Добавить модель", "btn_del_mod": "🗑 Удалить модель", "btn_del_router": "🗑 Удалить роутер", 
        "del_confirm_msg": "⚠️ Вы уверены, что хотите удалить этот роутер?",
        "btn_yes": "✅ Да, удалить", "btn_no": "❌ Отмена", "del_success": "✅ Успешно удалено.", "pls_select_model": "Выберите корректную модель.",
        "invalid_command": "❌ Неверная команда.", "send_channel_prompt": "📢 Отправьте юзернейм канала (@channel) или none:",
        "channel_set": "✅ Обязательный канал установлен: `{}`", "channel_none": "🔓 Подписка на канал отключена.",
        "must_join": "⛔ Для продолжения подпишитесь на канал:", "btn_join_channel": "🔗 Подписаться на канал",
        "btn_check_join": "🔄 Проверить подписку", "join_ok": "✅ Подписка подтверждена!", "join_fail": "❌ Вы еще не подписались на канал!",
        "send_del_model": "🗑 Введите точное имя модели для удаления:",
        "model_deleted": "✅ Модель успешно удалена.", "model_not_found": "❌ Модель с таким именем не найдена."
    },
    "ar": {
        "name": "🇸🇦 العربية", "welcome_new": "يرجى اختيار لغتك المفضلة:", "welcome_back": "أهلاً بك مجدداً في النظام، {name}!",
        "locked": "⛔ تم رصد دخول غير مصرح. أدخل كلمة المرور:", "pwd_ok": "✅ تم التحقق من كلمة المرور!", "pwd_err": "❌ كلمة المرور غير صحيحة.",
        "pwd_none": "🔓 تم إلغاء قفل كلمة المرور.", "pwd_set": "✅ تم تعيين كلمة المرور: `{}`",
        "exit": "🧹 تم مسح سجل المحادثة. العودة لقائمة النماذج.", "admin_only": "❌ الوصول محصور بمسؤول النظام فقط.", "type_here": "اكتب رسالتك هنا...",
        "select_model": "✨ اختر نموذج الذكاء الاصطناعي لبدء المحادثة:", "no_models_admin": "⚠️ لا توجد نماذج. أرسل /admin لإدارتها.",
        "no_models_user": "⚠️ لا توجد نماذج متاحة حالياً.", "chat_started": "✅ تم الاتصال بنجاح بـ {}.\n🧹 تم مسح السجل السابق.",
        "invalid_url": "❌ صيغة الرابط غير صحيحة. أدخل رابطاً معتبراً:",
        "admin_menu": "⚙️ مرحباً بك في لوحة التحكم، اختر من القائمة:", "btn_routers": "🗂 قائمة API المتاحة بالبوت:", "btn_add_router": "➕ إضافة موجه جديد",
        "btn_settings": "⚙️ إعدادات النظام الفنية", "btn_set_pwd": "🔐 كلمة مرور النظام", "btn_set_channel": "📢 القناة الإجبارية", "btn_broadcast": "📢 إرسال جماعي", 
        "btn_user_mode": "👤 وضع المستخدم", "btn_back": "🔙 الرجوع للسابق", "btn_back_main": "🏠 القائمة الرئيسية", "send_pwd_prompt": "🔐 أرسل كلمة المرور الجديدة (أو none):",
        "send_broadcast": "📢 أدخل نص الرسالة المراد بثها للجميع:", "broadcast_done": "✅ تم البث بنجاح إلى {} مستخدم.",
        "send_url": "🌐 أدخل عنوان Base URL 정확히:", "url_detected": "النطاق: {}\nأدخل مفتاح API:",
        "send_model": "تم حفظ المفتاح.\nأدخل اسم النموذج بدقة:", "router_added": "✅ تم إضافة الموجه والنموذج بنجاح!",
        "router_details": "📌 **الموجه:** {}\n🌐 الرابط: `{}`\n🔑 المفتاح: `{}`\n\n📦 **النماذج:**",
        "btn_add_mod": "➕ إضافة نموذج", "btn_del_mod": "🗑 حذف نموذج", "btn_del_router": "🗑 حذف الموجه", 
        "del_confirm_msg": "⚠️ هل أنت تأكد من حذف هذا الموجه؟",
        "btn_yes": "✅ نعم تأكيد", "btn_no": "❌ إلغاء", "del_success": "✅ تم الحذف بنجاح.", "pls_select_model": "اختر نموذجاً صحيحاً.",
        "invalid_command": "❌ أمر غير صالح.", "send_channel_prompt": "📢 أرسل معرف القناة (@channel) أو none:",
        "channel_set": "✅ تم تعيين القناة: `{}`", "channel_none": "🔓 تم إلغاء القناة الإجبارية.",
        "must_join": "⛔ يجب الاشتراك بالقناة المعتمدة أولاً:", "btn_join_channel": "🔗 الاشتراك بالقناة الآن",
        "btn_check_join": "🔄 التحقق من الاشتراك", "join_ok": "✅ تم التحقق من اشتراكك بنجاح!", "join_fail": "❌ لم تشترك بالقناة بعد!",
        "send_del_model": "🗑 أرسل الاسم الدقيق للنموذج المراد حذفه:",
        "model_deleted": "✅ تم حذف النموذج بنجاح.", "model_not_found": "❌ لم يتم العثور على النموذج."
    },
    "hi": {
        "name": "🇮🇳 हिन्दी", "welcome_new": "कृपया अपनी भाषा चुनें:", "welcome_back": "सिस्टम में स्वागत है, {name}!",
        "locked": "⛔ अनधिकृत पहुंच। पासवर्ड दर्ज करें:", "pwd_ok": "✅ पासवर्ड स्वीकृत!", "pwd_err": "❌ गलत पासवर्ड।",
        "pwd_none": "🔓 पासवर्ड सुरक्षा हटा दी गई।", "pwd_set": "✅ नया पासवर्ड: `{}`",
        "exit": "🧹 चैट इतिहास साफ़। मॉडल सूची पर वापस।", "admin_only": "❌ केवल एडमिन का उपयोग।", "type_here": "अपना संदेश लिखें...",
        "select_model": "✨ बातचीत शुरू करने के लिए AI मॉडल चुनें:", "no_models_admin": "⚠️ कोई मॉडल नहीं। /admin भेजें।",
        "no_models_user": "⚠️ कोई मॉडल उपलब्ध नहीं।", "chat_started": "✅ {} से सफलतापूर्वक कनेक्टेड।\n🧹 पुराना चैट साफ़।",
        "invalid_url": "❌ अमान्य URL।", "admin_menu": "⚙️ एडमिन कंट्रोल पैनल में आपका स्वागत है:", "btn_routers": "🗂 बॉट में उपलब्ध API सूची:", "btn_add_router": "➕ नया राउटर जोड़ें",
        "btn_settings": "⚙️ सिस्टम सेटिंग्स", "btn_set_pwd": "🔐 पासवर्ड", "btn_set_channel": "📢 अनिवार्य चैनल", "btn_broadcast": "📢 व्यापक प्रसारण", 
        "btn_user_mode": "👤 उपयोगकर्ता मोड", "btn_back": "🔙 पीछे जाएँ", "btn_back_main": "🏠 मुख्य मेनू", "send_pwd_prompt": "🔐 नया पासवर्ड भेजें (या none):",
        "send_broadcast": "📢 प्रसारण संदेश दर्ज करें:", "broadcast_done": "✅ {} उपयोगकर्ताओं को संदेश भेजा गया।",
        "send_url": "🌐 सटीक Base URL भेजें:", "url_detected": "डोमेन: {}\nAPI कुंजी भेजें:",
        "send_model": "API टोकन सहेजा गया। सटीक मॉडल नाम भेजें:", "router_added": "✅ राउटर और मॉडल जोड़ा गया!",
        "router_details": "📌 **राउटर:** {}\n🌐 URL: `{}`\n🔑 टोकन: `{}`\n\n📦 **मॉडल:**",
        "btn_add_mod": "➕ मॉडल जोड़ें", "btn_del_mod": "🗑 मॉडल हटाएं", "btn_del_router": "🗑 राउटर हटाएं", 
        "del_confirm_msg": "⚠️ क्या आप वाकई इसे हटाना चाहते हैं?",
        "btn_yes": "✅ हाँ हटाएं", "btn_no": "❌ रद्द करें", "del_success": "✅ सफलतापूर्वक हटा दिया गया।", "pls_select_model": "वैध मॉडल चुनें।",
        "invalid_command": "❌ अमान्य कमांड।", "send_channel_prompt": "📢 चैनल यूजरनेम (@channel) या none भेजें:",
        "channel_set": "✅ अनिवार्य चैनल सेट: `{}`", "channel_none": "🔓 चैनल सदस्यता बंद।",
        "must_join": "⛔ उपयोग जारी रखने के लिए चैनल से जुड़ें:", "btn_join_channel": "🔗 चैनल से जुड़ें",
        "btn_check_join": "🔄 सदस्यता जांचें", "join_ok": "✅ सदस्यता सत्यापित!", "join_fail": "❌ आप अभी तक चैनल से नहीं जुड़े हैं!",
        "send_del_model": "🗑 हटाने के लिए सटीक मॉडल नाम दर्ज करें:",
        "model_deleted": "✅ मॉडल हटा दिया गया।", "model_not_found": "❌ मॉडल नहीं मिला।"
    },
    "tr": {
        "name": "🇹🇷 Türkçe", "welcome_new": "Lütfen tercih ettiğiniz dili seçin:", "welcome_back": "Sisteme tekrar hoş geldiniz, {name}!",
        "locked": "⛔ Yetkisiz erişيم. Lütfen geçerli şifreyi girin:", "pwd_ok": "✅ Şifre başarıyla doğrulandı!", "pwd_err": "❌ Yanlış şifre girildi.",
        "pwd_none": "🔓 Şifre koruması kaldırıldı.", "pwd_set": "✅ Yeni erişim şifresi: `{}`",
        "exit": "🧹 Sohbet geçmişi temizlendi. Modellere dönülüyor.", "admin_only": "❌ Sadece yönetici erişimi.", "type_here": "Mesajınızı yazın...",
        "select_model": "✨ Sohbet başlatmak için AI modeli seçin:", "no_models_admin": "⚠️ Model bulunamadı. Yönetim için /admin gönderin.",
        "no_models_user": "⚠️ Kullanılabilir AI modeli bulunmuyor.", "chat_started": "✅ {} bağlandı.\n🧹 Geçmiş temizlendi.",
        "invalid_url": "❌ Geçersiz URL formatı.", "admin_menu": "⚙️ Yönetim Paneline Hoş Geldiniz:", "btn_routers": "🗂 Botta Mevcut API Listesi:", "btn_add_router": "➕ Yeni Router Ekle",
        "btn_settings": "⚙️ Sistem Ayarları Menüsü", "btn_set_pwd": "🔐 Erişim Şifresi", "btn_set_channel": "📢 Zorunlu Kanal", "btn_broadcast": "📢 Toplu Duyuru", 
        "btn_user_mode": "👤 Kullanıcı Modu", "btn_back": "🔙 Geri Dön", "btn_back_main": "🏠 Ana Menü", "send_pwd_prompt": "🔐 Yeni şifreyi girin (veya none):",
        "send_broadcast": "📢 Duyuru mesajınızı girin:", "broadcast_done": "✅ Duyuru {} kullanıcıya gönderildi.",
        "send_url": "🌐 Tam Base URL adresini gönderin:", "url_detected": "Alan adı: {}\nAPI Anahtarını gönderin:",
        "send_model": "API Anahtarı kaydedildi.\nTam model adını gönderin:", "router_added": "✅ Router ve Model başarıyla eklendi!",
        "router_details": "📌 **Router:** {}\n🌐 URL: `{}`\n🔑 Token: `{}`\n\n📦 **Modeller:**",
        "btn_add_mod": "➕ Model Ekle", "btn_del_mod": "🗑 Model Sil", "btn_del_router": "🗑 Router Sil", 
        "del_confirm_msg": "⚠️ Bu router'ı silmek istediğinize emin misiniz?",
        "btn_yes": "✅ Evet Onayla", "btn_no": "❌ İptal Et", "del_success": "✅ Başarıyla silindi.", "pls_select_model": "Geçerli bir model seçin.",
        "invalid_command": "❌ Geçersiz komut.", "send_channel_prompt": "📢 Kanal kullanıcı adını (@kanal) veya none gönderin:",
        "channel_set": "✅ Zorunlu kanal ayarlandı: `{}`", "channel_none": "🔓 Zorunlu kanal iptal edildi.",
        "must_join": "⛔ Devam etmek için kanala katılın:", "btn_join_channel": "🔗 Kanala Şimdi Katıl",
        "btn_check_join": "🔄 Üyeliğimi Kontrol Et", "join_ok": "✅ Katılımınız doğrulandı!", "join_fail": "❌ Henüz kanala katılmadınız!",
        "send_del_model": "🗑 Silinecek modelin tam adını gönderin:",
        "model_deleted": "✅ Model başarıyla silindi.", "model_not_found": "❌ Belirtilen model bulunamadı."
    },
    "fr": {
        "name": "🇫🇷 Français", "welcome_new": "Veuillez choisir votre langue :", "welcome_back": "Bon retour sur le système, {name} !",
        "locked": "⛔ Accès non autorisé. Veuillez entrer le mot de passe :", "pwd_ok": "✅ Mot de passe vérifié !", "pwd_err": "❌ Mot de passe incorrect.",
        "pwd_none": "🔓 Protection par mot de passe désactivée.", "pwd_set": "✅ Nouveau mot de passe : `{}`",
        "exit": "🧹 Historique effacé. Retour aux modèles.", "admin_only": "❌ Accès réservé aux administrateurs.", "type_here": "Tapez votre message...",
        "select_model": "✨ Sélectionnez un modèle IA pour converser :", "no_models_admin": "⚠️ Aucun modèle. Envoyez /admin pour gérer.",
        "no_models_user": "⚠️ Aucun modèle IA disponible.", "chat_started": "✅ Connecté à {}.\n🧹 Historique effacé.",
        "invalid_url": "❌ Format URL invalide.", "admin_menu": "⚙️ Bienvenue sur le panneau d'administration :", "btn_routers": "🗂 Liste des API disponibles dans le bot :", "btn_add_router": "➕ Ajouter Routeur",
        "btn_settings": "⚙️ Paramètres du système", "btn_set_pwd": "🔐 Mot de passe", "btn_set_channel": "📢 Canal obligatoire", "btn_broadcast": "📢 Diffusion globale", 
        "btn_user_mode": "👤 Mode Utilisateur", "btn_back": "🔙 Retour", "btn_back_main": "🏠 Menu principal", "send_pwd_prompt": "🔐 Entrez le nouveau mot de passe (ou none) :",
        "send_broadcast": "📢 Entrez le message à diffuser :", "broadcast_done": "✅ Message envoyé à {} utilisateurs.",
        "send_url": "🌐 Envoyez l'URL de base exacte :", "url_detected": "Domaine : {}\nEnvoyez la clé API :",
        "send_model": "Clé API enregistrée.\nEnvoyez le nom exact du modèle :", "router_added": "✅ Routeur et modèle ajoutés !",
        "router_details": "📌 **Routeur :** {}\n🌐 URL : `{}`\n🔑 Jeton : `{}`\n\n📦 **Modèles :**",
        "btn_add_mod": "➕ Ajouter modèle", "btn_del_mod": "🗑 Supprimer modèle", "btn_del_router": "🗑 Supprimer routeur", 
        "del_confirm_msg": "⚠️ Êtes-vous sûr de vouloir supprimer ce routeur ?",
        "btn_yes": "✅ Oui confirmer", "btn_no": "❌ Annuler", "del_success": "✅ Supprimé avec succès.", "pls_select_model": "Choisissez un modèle valide.",
        "invalid_command": "❌ Commande non valide.", "send_channel_prompt": "📢 Envoyez le nom du canal (@canal) ou none :",
        "channel_set": "✅ Canal obligatoire défini : `{}`", "channel_none": "🔓 Canal obligatoire désactivé.",
        "must_join": "⛔ Rejoignez notre canal pour continuer :", "btn_join_channel": "🔗 Rejoindre le canal",
        "btn_check_join": "🔄 Vérifier mon adhésion", "join_ok": "✅ Adhésion confirmée !", "join_fail": "❌ Vous n'avez pas encore rejoint le canal !",
        "send_del_model": "🗑 Envoyez le nom exact du modèle à supprimer :",
        "model_deleted": "✅ Modèle supprimé avec succès.", "model_not_found": "❌ Modèle introuvable."
    },
    "de": {
        "name": "🇩🇪 Deutsch", "welcome_new": "Bitte wählen Sie Ihre Sprache:", "welcome_back": "Willkommen zurück im System, {name}!",
        "locked": "⛔ Unbefugter Zugriff. Bitte Passwort eingeben:", "pwd_ok": "✅ Passwort erfolgreich bestätigt!", "pwd_err": "❌ Falsches Passwort eingegeben.",
        "pwd_none": "🔓 Passwortschutz wurde aufgehoben.", "pwd_set": "✅ Neues Passwort gesetzt: `{}`",
        "exit": "🧹 Verlauf gelöscht. Zurück zur Modellliste.", "admin_only": "❌ Zugriff nur für Administratoren.", "type_here": "Schreiben Sie Ihre Nachricht...",
        "select_model": "✨ Wählen Sie ein KI-Modell für den Chat:", "no_models_admin": "⚠️ Keine Modelle. Senden Sie /admin.",
        "no_models_user": "⚠️ Derzeit keine Modelle verfügbar.", "chat_started": "✅ Erfogreich mit {} verbunden.\n🧹 Verlauf gelöscht.",
        "invalid_url": "❌ Ungültiges URL-Format.", "admin_menu": "⚙️ Willkommen im Admin-Bedienfeld:", "btn_routers": "🗂 Liste der verfügbaren APIs im Bot:", "btn_add_router": "➕ Neuen Router hinzufügen",
        "btn_settings": "⚙️ Systemeinstellungen", "btn_set_pwd": "🔐 Passwort", "btn_set_channel": "📢 Pflichtkanal", "btn_broadcast": "📢 Nachricht senden", 
        "btn_user_mode": "👤 Benutzermodus", "btn_back": "🔙 Zurück", "btn_back_main": "🏠 Hauptmenü", "send_pwd_prompt": "🔐 Neues Passwort eingeben (oder none):",
        "send_broadcast": "📢 Nachricht für Rundschreiben eingeben:", "broadcast_done": "✅ Nachricht an {} Benutzer gesendet.",
        "send_url": "🌐 Exakte Base URL senden:", "url_detected": "Domain: {}\nJetzt API-Schlüssel senden:",
        "send_model": "API-Schlüssel gespeichert.\nExakten Modellnamen senden:", "router_added": "✅ Router und Modell hinzugefügt!",
        "router_details": "📌 **Router:** {}\n🌐 URL: `{}`\n🔑 Token: `{}`\n\n📦 **Modelle:**",
        "btn_add_mod": "➕ Modell hinzufügen", "btn_del_mod": "🗑 Modell löschen", "btn_del_router": "🗑 Router löschen", 
        "del_confirm_msg": "⚠️ Möchten Sie diesen Router wirklich löschen?",
        "btn_yes": "✅ Ja Bestätigen", "btn_no": "❌ Abbrechen", "del_success": "✅ Erfolgreich gelöscht.", "pls_select_model": "Gültiges Modell wählen.",
        "invalid_command": "❌ Ungültiger Befehl.", "send_channel_prompt": "📢 Kanalnamen (@kanal) oder none senden:",
        "channel_set": "✅ Pflichtkanal gesetzt: `{}`", "channel_none": "🔓 Pflichtkanal deaktiviert.",
        "must_join": "⛔ Bitte treten Sie dem Kanal bei:", "btn_join_channel": "🔗 Jetzt Kanal Beitreten",
        "btn_check_join": "🔄 Mitgliedschaft Prüfen", "join_ok": "✅ Mitgliedschaft bestätigt!", "join_fail": "❌ Sie sind dem Kanal noch nicht beigetreten!",
        "send_del_model": "🗑 Exakten Namen des zu löschenden Modells senden:",
        "model_deleted": "✅ Modell erfolgreich gelöscht.", "model_not_found": "❌ Modell nicht gefunden."
    },
    "zh": {
        "name": "🇨🇳 中文", "welcome_new": "请选择您的首选语言：", "welcome_back": "欢迎回到系统，{name}！",
        "locked": "⛔ 未授权访问。请输入正确密码：", "pwd_ok": "✅ 密码验证成功！", "pwd_err": "❌ 输入的密码不正确。",
        "pwd_none": "🔓 密码保护已移除。", "pwd_set": "✅ 已设置新密码：`{}`",
        "exit": "🧹 对话历史已清除。返回模型列表。", "admin_only": "❌ 仅限管理员访问。", "type_here": "请输入您的消息...",
        "select_model": "✨ 请选择 AI 模型以开始对话：", "no_models_admin": "⚠️ 未找到模型。发送 /admin 进行管理。",
        "no_models_user": "⚠️ 当前没有可用的 AI 模型。", "chat_started": "✅ 已成功连接至 {}。\n🧹 历史记录已清除。",
        "invalid_url": "❌ URL 格式无效。", "admin_menu": "⚙️ 欢迎来到管理员控制面板：", "btn_routers": "🗂 机器人中可用的 API 列表：", "btn_add_router": "➕ 添加新路由",
        "btn_settings": "⚙️ 系统设置菜单", "btn_set_pwd": "🔐 访问密码", "btn_set_channel": "📢 强制关注频道", "btn_broadcast": "📢 广播消息", 
        "btn_user_mode": "👤 用户模式", "btn_back": "🔙 返回上一级", "btn_back_main": "🏠 主控制面板", "send_pwd_prompt": "🔐 请发送新密码（或 none）：",
        "send_broadcast": "📢 请输入要广播的消息内容：", "broadcast_done": "✅ 广播成功发送给 {} 名用户。",
        "send_url": "🌐 请发送准确的 Base URL 地址：", "url_detected": "识别域名：{}\n现在发送 API 密钥：",
        "send_model": "密钥已保存。\n现在发送准确的模型名称：", "router_added": "✅ 路由和模型添加成功！",
        "router_details": "📌 **路由域名：** {}\n🌐 Address: `{}`\n🔑 Token: `{}`\n\n📦 **配置的模型：**",
        "btn_add_mod": "➕ 添加模型", "btn_del_mod": "🗑 删除模型", "btn_del_router": "🗑 删除路由", 
        "del_confirm_msg": "⚠️ 确定要删除此路由及其模型吗？",
        "btn_yes": "✅ 是的确认", "btn_no": "❌ 取消操作", "del_success": "✅ 成功删除。", "pls_select_model": "请选择有效模型。",
        "invalid_command": "❌ 无效指令。", "send_channel_prompt": "📢 请发送频道用户名 (@channel) 或 none：",
        "channel_set": "✅ 强制频道已设置：`{}`", "channel_none": "🔓 强制关注已关闭。",
        "must_join": "⛔ 必须先加入频道才能继续：", "btn_join_channel": "🔗 立即加入频道",
        "btn_check_join": "🔄 验证我的会员资格", "join_ok": "✅ 验证通过！您现在可以使用机器人了。", "join_fail": "❌ 您尚未加入我们的频道！",
        "send_del_model": "🗑 发送要删除的模型的准确名称：",
        "model_deleted": "✅ 模型删除成功。", "model_not_found": "❌ 未找到指定的模型名称。"
    }
}

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
            lang = row[0] if row and row[0] in LANGS else "en"
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
    builder.button(text=await get_text(user_id, "btn_user_mode"), callback_data="admin_switch_user")
    builder.adjust(2, 1, 1)
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
        await message.answer("Please select your language / لطفاً زبان خود را انتخاب کنید:", reply_markup=lang_keyboard())
    else:
        welcome_txt = await get_text(message.from_user.id, "welcome_back")
        await message.answer(welcome_txt.format(name=message.from_user.first_name))
        await show_user_panel(message, message.from_user.id)

@router.message(Command("lang", ignore_case=True))
@router.message(text_cmd_filter("lang"))
async def cmd_lang(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Please select your language / لطفاً زبان خود را انتخاب کنید:", reply_markup=lang_keyboard())

@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, lang) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang
        """, (callback.from_user.id, lang))
        await db.commit()
    
    await callback.message.delete()
    await show_user_panel(callback, callback.from_user.id)

# ================= هندلرهای کاربری و صفحه‌بندی =================
@router.message(Command("user", ignore_case=True))
@router.message(text_cmd_filter("user"))
async def cmd_user(message: Message, state: FSMContext):
    await state.clear()
    await show_user_panel(message, message.from_user.id)

@router.callback_query(F.data == "check_join_channel")
async def check_join_callback(callback: CallbackQuery):
    joined, channel = await check_channel_join(callback.from_user.id)
    if joined:
        ok_txt = await get_text(callback.from_user.id, "join_ok")
        await callback.answer(ok_txt, show_alert=True)
        await callback.message.delete()
        await show_user_panel(callback, callback.from_user.id)
    else:
        fail_txt = await get_text(callback.from_user.id, "join_fail")
        await callback.answer(fail_txt, show_alert=True)

async def show_user_panel(event, user_id: int, page: int = 1):
    is_cb = isinstance(event, CallbackQuery)
    target_msg = event.message if is_cb else event

    joined, channel = await check_channel_join(user_id)
    if not joined:
        txt = await get_text(user_id, "must_join")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=await get_text(user_id, "btn_join_channel"), url=f"https://t.me/{channel.replace('@', '')}")],
            [InlineKeyboardButton(text=await get_text(user_id, "btn_check_join"), callback_data="check_join_channel")]
        ])
        if is_cb:
            await target_msg.edit_text(f"{txt}\n{channel}", reply_markup=kb)
        else:
            await target_msg.answer(f"{txt}\n{channel}", reply_markup=kb)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, model_name FROM models ORDER BY id ASC") as cursor:
            models = await cursor.fetchall()
            
    if not models:
        txt = await get_text(user_id, "no_models_admin" if user_id == ADMIN_ID else "no_models_user")
        if is_cb:
            await target_msg.edit_text(txt)
        else:
            await target_msg.answer(txt)
        return

    # صفحه‌بندی مدل‌ها: ۱۲ رکورد در هر صفحه و چیدمان ۲-۲
    PAGE_SIZE = 12
    total_models = len(models)
    total_pages = math.ceil(total_models / PAGE_SIZE)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    current_models = models[start_idx:end_idx]

    builder = InlineKeyboardBuilder()
    for m_id, m_name in current_models:
        emoji = get_model_emoji(m_name)
        builder.button(text=f"{emoji} {m_name}", callback_data=f"selmod_{m_id}_{page}")
        
    builder.adjust(2) # چیدمان ۲ تایی (2-2)

    # افزودن دکمه‌های صفحه‌بندی در صورتی که بیش از ۱۲ مدل وجود داشته باشد
    if total_models > PAGE_SIZE:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"modpage_{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop_page"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"modpage_{page + 1}"))
        builder.row(*nav_buttons)

    select_text = await get_text(user_id, "select_model")
    
    if is_cb:
        try:
            await target_msg.edit_text(select_text, reply_markup=builder.as_markup())
        except Exception:
            await target_msg.answer(select_text, reply_markup=builder.as_markup())
    else:
        await target_msg.answer(select_text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("modpage_"))
async def process_model_pagination(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    await show_user_panel(callback, callback.from_user.id, page=page)
    await callback.answer()

@router.callback_query(F.data == "noop_page")
async def process_noop_page(callback: CallbackQuery):
    await callback.answer()

@router.callback_query(F.data.startswith("selmod_"))
async def select_model(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    model_id = parts[1]
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
@router.message(text_cmd_filter("model"))
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
@router.message(text_cmd_filter("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if message.from_user.id != ADMIN_ID:
        err = await get_text(message.from_user.id, "admin_only")
        return await message.answer(err)
    
    admin_text = await get_text(message.from_user.id, "admin_menu")
    kb = await admin_panel_keyboard(message.from_user.id)
    await message.answer(admin_text, reply_markup=kb)

@router.callback_query(F.data == "admin_switch_user")
async def admin_switch_to_user_mode(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_user_panel(callback, callback.from_user.id)
    await callback.answer()

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
                buttons.append([InlineKeyboardButton(text=f"🌐 {domain}", callback_data=f"router_{r_id}")])
                
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
    for _, m_name in models:
        emoji = get_model_emoji(m_name)
        # فرمت کپی‌آسان در حالت monospace
        msg += f"• `{m_name}` {emoji}\n"
        
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
