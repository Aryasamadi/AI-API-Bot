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

# ================= دیکشنری کامل ۹ زبان =================
LANGS = {
    "en": {
        "name": "🇬🇧 English", "welcome_new": "Please select your language:", "welcome_back": "Welcome back, {name}!",
        "locked": "⛔ Unauthorized. Please enter the password:", "pwd_ok": "✅ Password accepted!", "pwd_err": "❌ Incorrect password.",
        "pwd_none": "🔓 Password requirement removed. Bot is public.", "pwd_set": "✅ New password set: `{}`",
        "exit": "🧹 Chat history cleared. Back to models.", "admin_only": "❌ Admin only.", "type_here": "Type your message...",
        "select_model": "Select an AI model to start:", "no_models_admin": "⚠️ No models found. Send /admin to manage.",
        "no_models_user": "⚠️ No AI models are currently available.", "chat_started": "✅ Connected to {}. Send your message:",
        "invalid_url": "❌ Invalid URL format. Please send a valid Base URL (http/https):",
        "admin_menu": "⚙️ Admin Panel, use the menu below.", "btn_routers": "🗂 API List", "btn_add_router": "➕ Add Router",
        "btn_set_pwd": "🔐 Set Password", "btn_broadcast": "📢 Broadcast", "btn_back": "🔙 Back",
        "btn_back_main": "🏠 Main Menu", "send_pwd_prompt": "Send new password (or 'none' to make public):",
        "send_broadcast": "Send your broadcast message:", "broadcast_done": "✅ Sent to {} users.",
        "send_url": "Send the Base URL (e.g., https://api.openai.com/v1):", "url_detected": "Domain: {}\nNow send the API Key (Token):",
        "send_model": "API Key saved.\nNow send the exact Model Name:", "router_added": "✅ Router and Model added successfully!",
        "router_details": "📌 **Router:** {}\n🌐 Base URL: `{}`\n🔑 Token: `{}`\n\n📦 **Models:**",
        "btn_add_mod": "➕ Add Model", "btn_del_router": "🗑 Delete Router", "del_confirm_msg": "⚠️ Are you sure you want to delete this router and its models?",
        "btn_yes": "✅ Yes, Delete", "btn_no": "❌ No, Cancel", "del_success": "✅ Router deleted.",
        "pls_select_model": "Please select a model first.",
        "invalid_command": "❌ Please use valid logical commands."
    },
    "fa": {
        "name": "🇮🇷 فارسی", "welcome_new": "لطفاً زبان خود را انتخاب کنید:", "welcome_back": "خوش برگشتی، {name}!",
        "locked": "⛔ شما کاربر غیرمجاز هستید. لطفاً رمز عبور را وارد کنید:", "pwd_ok": "✅ رمز عبور تایید شد!", "pwd_err": "❌ رمز اشتباه است.",
        "pwd_none": "🔓 قفل ربات برداشته شد. استفاده برای همه آزاد است.", "pwd_set": "✅ رمز عبور جدید تنظیم شد: `{}`",
        "exit": "🧹 تاریخچه مکالمه پاک شد. بازگشت به لیست مدل‌ها.", "admin_only": "❌ دسترسی فقط برای مدیریت.", "type_here": "پیام خود را بنویسید...",
        "select_model": "مدل هوش مصنوعی را انتخاب کنید:", "no_models_admin": "⚠️ هیچ مدلی وجود ندارد. برای مدیریت /admin را ارسال کنید .",
        "no_models_user": "⚠️ در حال حاضر هیچ مدلی در دسترس نیست.", "chat_started": "✅ شما به {} متصل شدید:",
        "invalid_url": "❌ فرمت لینک اشتباه است. لطفاً یک URL معتبر بفرستید:",
        "admin_menu": "⚙️ پنل مدیریت ، از منو پایین استفاده کنید.", "btn_routers": "🗂 لیست APIها", "btn_add_router": "➕ افزودن روتر",
        "btn_set_pwd": "🔐 تنظیم رمز عبور", "btn_broadcast": "📢 پیام همگانی", "btn_back": "🔙 بازگشت",
        "btn_back_main": "🏠 منوی اصلی", "send_pwd_prompt": "رمز جدید را بفرستید (یا none برای آزادسازی):",
        "send_broadcast": "پیام همگانی خود را بفرستید:", "broadcast_done": "✅ به {} کاربر ارسال شد.",
        "send_url": "آدرس Base URL را بفرستید:", "url_detected": "دامنه: {}\nحالا کلید API (توکن) را بفرستید:",
        "send_model": "توکن ذخیره شد.\nحالا نام دقیق مدل را بفرستید:", "router_added": "✅ روتر و مدل با موفقیت اضافه شدند!",
        "router_details": "📌 **روتر:** {}\n🌐 آدرس: `{}`\n🔑 توکن: `{}`\n\n📦 **مدل‌ها:**",
        "btn_add_mod": "➕ افزودن مدل", "btn_del_router": "🗑 حذف روتر", "del_confirm_msg": "⚠️ آیا از حذف این روتر مطمئن هستید؟",
        "btn_yes": "✅ بله، حذف", "btn_no": "❌ خیر، لغو", "del_success": "✅ روتر حذف شد.",
        "pls_select_model": "لطفاً یک مدل را انتخاب بکنید.",
        "invalid_command": "❌ لطفاً از دستورات منطقی استفاده کنید."
    },
    "ru": {
        "name": "🇷🇺 Русский", "welcome_new": "Пожалуйста, выберите язык:", "welcome_back": "С возвращением, {name}!",
        "locked": "⛔ Доступ ограничен. Введите пароль:", "pwd_ok": "✅ Пароль принят!", "pwd_err": "❌ Неверный пароль.",
        "pwd_none": "🔓 Пароль удален. Бот общедоступен.", "pwd_set": "✅ Новый пароль установлен: `{}`",
        "exit": "🧹 История очищена.", "admin_only": "❌ Только для админа.", "type_here": "Введите сообщение...",
        "select_model": "Выберите модель ИИ:", "no_models_admin": "⚠️ Модели не найдены. Отправьте /admin для управления.",
        "no_models_user": "⚠️ Нет доступных моделей.", "chat_started": "✅ Подключено к {}.",
        "invalid_url": "❌ Неверный URL.", "admin_menu": "⚙️ Панель администратора, используйте меню ниже.", "btn_routers": "🗂 Список API", "btn_add_router": "➕ Добавить роутер",
        "btn_set_pwd": "🔐 Установить пароль", "btn_broadcast": "📢 Рассылка", "btn_back": "🔙 Назад",
        "btn_back_main": "🏠 Главное меню", "send_pwd_prompt": "Введите новый пароль:",
        "send_broadcast": "Введите сообщение для рассылки:", "broadcast_done": "✅ Отправлено пользователям: {}.",
        "send_url": "Введите Base URL:", "url_detected": "Домен: {}\nВведите API ключ:",
        "send_model": "Введите название модели:", "router_added": "✅ Роутер добавлен!",
        "router_details": "📌 **Роутер:** {}\n🌐 URL: `{}`\n🔑 Токен: `{}`\n\n📦 **Модели:**",
        "btn_add_mod": "➕ Добавить модель", "btn_del_router": "🗑 Удалить", "del_confirm_msg": "⚠️ Вы уверены?",
        "btn_yes": "✅ Да", "btn_no": "❌ Нет", "del_success": "✅ Удалено.",
        "pls_select_model": "Пожалуйста, сначала выберите модель.",
        "invalid_command": "❌ Пожалуйста, используйте правильные команды."
    },
    "ar": {
        "name": "🇸🇦 العربية", "welcome_new": "يرجى اختيار لغتك:", "welcome_back": "أهلاً بك مجدداً، {name}!",
        "locked": "⛔ غير مصرح. أدخل كلمة المرور:", "pwd_ok": "✅ تم قبول كلمة المرور!", "pwd_err": "❌ كلمة المرور خاطئة.",
        "pwd_none": "🔓 تمت إزالة كلمة المرور. البوت عام.", "pwd_set": "✅ كلمة المرور الجديدة: `{}`",
        "exit": "🧹 تم مسح السجل.", "admin_only": "❌ للمسؤولين فقط.", "type_here": "اكتب رسالتك...",
        "select_model": "اختر نموذج ذكاء اصطناعي:", "no_models_admin": "⚠️ لا توجد نماذج. أرسل /admin للإدارة.",
        "no_models_user": "⚠️ لا توجد نماذج متاحة.", "chat_started": "✅ متصل بـ {}.",
        "invalid_url": "❌ رابط غير صالح.", "admin_menu": "⚙️ لوحة الإدارة، استخدم القائمة أدناه.", "btn_routers": "🗂 قائمة API", "btn_add_router": "➕ إضافة موجه",
        "btn_set_pwd": "🔐 تعيين كلمة المرور", "btn_broadcast": "📢 إرسال للكل", "btn_back": "🔙 رجوع",
        "btn_back_main": "🏠 القائمة الرئيسية", "send_pwd_prompt": "أدخل كلمة المرور الجديدة:",
        "send_broadcast": "أدخل رسالة البث:", "broadcast_done": "✅ تم الإرسال إلى {} مستخدم.",
        "send_url": "أدخل Base URL:", "url_detected": "النطاق: {}\nأدخل مفتاح API:",
        "send_model": "أدخل اسم النموذج:", "router_added": "✅ تمت الإضافة!",
        "router_details": "📌 **الموجه:** {}\n🌐 الرابط: `{}`\n🔑 الرمز: `{}`\n\n📦 **النماذج:**",
        "btn_add_mod": "➕ إضافة نموذج", "btn_del_router": "🗑 حذف", "del_confirm_msg": "⚠️ هل أنت متأكد؟",
        "btn_yes": "✅ نعم", "btn_no": "❌ إلغاء", "del_success": "✅ تم الحذف.",
        "pls_select_model": "يرجى اختيار نموذج أولاً.",
        "invalid_command": "❌ يرجى استخدام أوامر صحيحة."
    },
    "hi": {
        "name": "🇮🇳 हिन्दी", "welcome_new": "कृपया अपनी भाषा चुनें:", "welcome_back": "वापसी पर स्वागत है, {name}!",
        "locked": "🔑 पासवर्ड दर्ज करें:", "pwd_ok": "✅ पासवर्ड स्वीकृत!", "pwd_err": "❌ गलत पासवर्ड।",
        "pwd_none": "🔓 पासवर्ड हटा दिया गया है।", "pwd_set": "✅ नया पासवर्ड: `{}`",
        "exit": "🧹 इतिहास साफ़ हो गया।", "admin_only": "❌ केवल व्यवस्थापक।", "type_here": "संदेश लिखें...",
        "select_model": "मॉडल चुनें:", "no_models_admin": "⚠️ कोई मॉडल नहीं मिला। प्रबंधित करने के लिए /admin भेजें।",
        "no_models_user": "⚠️ कोई मॉडल उपलब्ध नहीं है।", "chat_started": "✅ {} से कनेक्टेड।",
        "invalid_url": "❌ अमान्य URL۔", "admin_menu": "⚙️ एडमिन पैनल, नीचे दिए गए मेनू का उपयोग करें।", "btn_routers": "🗂 API सूची", "btn_add_router": "➕ روटर जोड़ें",
        "btn_set_pwd": "🔐 पासवर्ड सेट करें", "btn_broadcast": "📢 प्रसारण", "btn_back": "🔙 पीछे",
        "btn_back_main": "🏠 मुख्य मेनू", "send_pwd_prompt": "नया पासवर्ड भेजें:",
        "send_broadcast": "संदेश भेजें:", "broadcast_done": "✅ {} उपयोगकर्ताओं को भेजा गया।",
        "send_url": "Base URL भेजें:", "url_detected": "डोमेन: {}\nAPI कुंजी भेजें:",
        "send_model": "मॉडल का नाम भेजें:", "router_added": "✅ जोड़ा गया!",
        "router_details": "📌 **روटर:** {}\n🌐 URL: `{}`\n🔑 टोकन: `{}`\n\n📦 **मॉडल:**",
        "btn_add_mod": "➕ मॉडल जोड़ें", "btn_del_router": "🗑 हटाएं", "del_confirm_msg": "⚠️ क्या आप নিশ্চিত हैं؟",
        "btn_yes": "✅ हाँ", "btn_no": "❌ नहीं", "del_success": "✅ हटा दिया गया।",
        "pls_select_model": "कृपया पहले एक मॉडल चुनें।",
        "invalid_command": "❌ कृपया मान्य तार्किक कमांड का उपयोग करें।"
    },
    "tr": {
        "name": "🇹🇷 Türkçe", "welcome_new": "Lütfen dilinizi seçin:", "welcome_back": "Tekrar hoş geldiniz, {name}!",
        "locked": "⛔ Yetkisiz. Şifreyi girin:", "pwd_ok": "✅ Şifre kabul edildi!", "pwd_err": "❌ Yanlış şifre.",
        "pwd_none": "🔓 Şifre kaldırıldı.", "pwd_set": "✅ Yeni şifre: `{}`",
        "exit": "🧹 Geçmiş temizlendi.", "admin_only": "❌ Sadece yönetici.", "type_here": "Mesajınızı yazın...",
        "select_model": "Bir model seçin:", "no_models_admin": "⚠️ Model bulunamadı. Yönetmek için /admin gönderin.",
        "no_models_user": "⚠️ Kullanılabilir model yok.", "chat_started": "✅ {} bağlanıldı.",
        "invalid_url": "❌ Geçersiz URL.", "admin_menu": "⚙️ Yönetici Paneli, aşağıdaki menüyü kullanın.", "btn_routers": "🗂 API Listesi", "btn_add_router": "➕ Router Ekle",
        "btn_set_pwd": "🔐 Şifre Belirle", "btn_broadcast": "📢 Duyuru", "btn_back": "🔙 Geri",
        "btn_back_main": "🏠 Ana Menü", "send_pwd_prompt": "Yeni şifreyi gönderin:",
        "send_broadcast": "Duyuru mesajını gönderin:", "broadcast_done": "✅ {} kullanıcıya gönderildi.",
        "send_url": "Base URL'yi gönderin:", "url_detected": "Alan adı: {}\nAPI Anahtarını gönderin:",
        "send_model": "Model adını gönderin:", "router_added": "✅ Eklendi!",
        "router_details": "📌 **Router:** {}\n🌐 URL: `{}`\n🔑 Token: `{}`\n\n📦 **Modeller:**",
        "btn_add_mod": "➕ Model Ekle", "btn_del_router": "🗑 Sil", "del_confirm_msg": "⚠️ Emin misiniz?",
        "btn_yes": "✅ Evet", "btn_no": "❌ İptal", "del_success": "✅ Silindi.",
        "pls_select_model": "Lütfen önce bir model seçin.",
        "invalid_command": "❌ Lütfen geçerli mantıksal komutlar kullanın."
    },
    "fr": {
        "name": "🇫🇷 Français", "welcome_new": "Veuillez choisir votre langue :", "welcome_back": "Bon retour, {name} !",
        "locked": "⛔ Non autorisé. Entrez le mot de passe :", "pwd_ok": "✅ Mot de passe accepté !", "pwd_err": "❌ Erreur.",
        "pwd_none": "🔓 Mot de passe supprimé.", "pwd_set": "✅ Nouveau mot de passe : `{}`",
        "exit": "🧹 Historique effacé.", "admin_only": "❌ Admin uniquement.", "type_here": "Tapez votre message...",
        "select_model": "Sélectionnez un modèle :", "no_models_admin": "⚠️ Aucun modèle trouvé. Envoyez /admin pour gérer.",
        "no_models_user": "⚠️ Aucun modèle disponible.", "chat_started": "✅ Connecté à {}.",
        "invalid_url": "❌ URL invalide.", "admin_menu": "⚙️ Panneau d'administration, utilisez le menu ci-dessous.", "btn_routers": "🗂 Liste API", "btn_add_router": "➕ Ajouter Routeur",
        "btn_set_pwd": "🔐 Définir MDP", "btn_broadcast": "📢 Diffusion", "btn_back": "🔙 Retour",
        "btn_back_main": "🏠 Menu Principal", "send_pwd_prompt": "Envoyez le nouveau mot de passe :",
        "send_broadcast": "Envoyez votre message :", "broadcast_done": "✅ Envoyé à {} utilisateurs.",
        "send_url": "Envoyez l'URL de base :", "url_detected": "Domaine : {}\nEnvoyez la clé API :",
        "send_model": "Envoyez le nom du modèle :", "router_added": "✅ Ajouté avec succès !",
        "router_details": "📌 **Routeur :** {}\n🌐 URL : `{}`\n🔑 Jeton : `{}`\n\n📦 **Modèles :**",
        "btn_add_mod": "➕ Ajouter Modèle", "btn_del_router": "🗑 Supprimer", "del_confirm_msg": "⚠️ Êtes-vous sûr ?",
        "btn_yes": "✅ Oui", "btn_no": "❌ Non", "del_success": "✅ Supprimé.",
        "pls_select_model": "Veuillez d'abord sélectionner un modèle.",
        "invalid_command": "❌ Veuillez utiliser des commandes logiques valides."
    },
    "de": {
        "name": "🇩🇪 Deutsch", "welcome_new": "Bitte wählen Sie Ihre Sprache:", "welcome_back": "Willkommen zurück, {name}!",
        "locked": "⛔ Nicht autorisiert. Passwort eingeben:", "pwd_ok": "✅ Passwort akzeptiert!", "pwd_err": "❌ Falsch.",
        "pwd_none": "🔓 Passwort entfernt.", "pwd_set": "✅ Neues Passwort: `{}`",
        "exit": "🧹 Verlauf gelöscht.", "admin_only": "❌ Nur Admin.", "type_here": "Nachricht schreiben...",
        "select_model": "Wählen Sie ein Modell:", "no_models_admin": "⚠️ Keine Modelle gefunden. Senden Sie /admin zur Verwaltung.",
        "no_models_user": "⚠️ Keine Modelle verfügbar.", "chat_started": "✅ Verbunden mit {}.",
        "invalid_url": "❌ Ungültige URL.", "admin_menu": "⚙️ Admin-Panel, verwenden Sie das Menü unten.", "btn_routers": "🗂 API-Liste", "btn_add_router": "➕ Router hinzufügen",
        "btn_set_pwd": "🔐 Passwort festlegen", "btn_broadcast": "📢 Broadcast", "btn_back": "🔙 Zurück",
        "btn_back_main": "🏠 Hauptmenü", "send_pwd_prompt": "Neues Passwort senden:",
        "send_broadcast": "Broadcast-Nachricht senden:", "broadcast_done": "✅ An {} Benutzer gesendet.",
        "send_url": "Base URL senden:", "url_detected": "Domain: {}\nAPI-Key senden:",
        "send_model": "Modellname senden:", "router_added": "✅ Hinzugefügt!",
        "router_details": "📌 **Router:** {}\n🌐 URL: `{}`\n🔑 Token: `{}`\n\n📦 **Modelle:**",
        "btn_add_mod": "➕ Modell hinzufügen", "btn_del_router": "🗑 Löschen", "del_confirm_msg": "⚠️ Sind Sie sicher?",
        "btn_yes": "✅ Ja", "btn_no": "❌ Nein", "del_success": "✅ Gelöscht.",
        "pls_select_model": "Bitte wählen Sie zuerst ein Modell aus.",
        "invalid_command": "❌ Bitte verwenden Sie gültige logische Befehle."
    },
    "zh": {
        "name": "🇨🇳 中文", "welcome_new": "请选择您的语言：", "welcome_back": "欢迎回来，{name}！",
        "locked": "⛔ 未授权。请输入密码：", "pwd_ok": "✅ 密码接受！", "pwd_err": "❌ 密码错误。",
        "pwd_none": "🔓 密码已移除，机器人已公开。", "pwd_set": "✅ 新密码已设置：`{}`",
        "exit": "🧹 聊天记录已清除。", "admin_only": "❌ 仅限管理员。", "type_here": "输入您的消息...",
        "select_model": "请选择 AI 模型：", "no_models_admin": "⚠️ 未找到模型。发送 /admin 进行管理。",
        "no_models_user": "⚠️ 当前无可用模型。", "chat_started": "{} 已连接。",
        "invalid_url": "❌ 无效的 URL。", "admin_menu": "⚙️ 管理面板，请使用下方菜单。", "btn_routers": "🗂 API 列表", "btn_add_router": "➕ 添加路由",
        "btn_set_pwd": "🔐 设置密码", "btn_broadcast": "📢 广播消息", "btn_back": "🔙 返回",
        "btn_back_main": "🏠 主菜单", "send_pwd_prompt": "发送新密码：",
        "send_broadcast": "发送广播消息：", "broadcast_done": "✅ 已发送给 {} 位用户。",
        "send_url": "发送 Base URL：", "url_detected": "域：{}\n发送 API 密钥：",
        "send_model": "发送模型名称：", "router_added": "✅ 添加成功！",
        "router_details": "📌 **路由：** {}\n🌐 地址：`{}`\n🔑 密钥：`{}`\n\n📦 **模型：**",
        "btn_add_mod": "➕ 添加模型", "btn_del_router": "🗑 删除", "del_confirm_msg": "⚠️ 您确定吗？",
        "btn_yes": "✅ 是", "btn_no": "❌ 否", "del_success": "✅ 已删除。",
        "pls_select_model": "请先选择一个模型。",
        "invalid_command": "❌ 请使用有效的逻辑命令。"
    }
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
    builder.adjust(2)
    return builder.as_markup()

async def admin_panel_keyboard(user_id):
    builder = InlineKeyboardBuilder()
    builder.button(text=await get_text(user_id, "btn_routers"), callback_data="admin_routers")
    builder.button(text=await get_text(user_id, "btn_add_router"), callback_data="admin_add_router")
    builder.button(text=await get_text(user_id, "btn_set_pwd"), callback_data="admin_pwd")
    builder.button(text=await get_text(user_id, "btn_broadcast"), callback_data="admin_broadcast")
    builder.adjust(2) # دکمه‌ها به صورت 2-2 چیده می‌شوند
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
        await message.answer("Please select your language:", reply_markup=lang_keyboard())
    else:
        welcome_txt = await get_text(message.from_user.id, "welcome_back")
        await message.answer(welcome_txt.format(name=message.from_user.first_name))
        await show_user_panel(message, message.from_user.id)

@router.message(Command("lang"))
@router.message(F.text.in_({"lang", "/lang"}))
async def cmd_lang(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Please select your language:", reply_markup=lang_keyboard())

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
        await message.answer(txt)
        return

    for m_id, m_name in models:
        buttons.append([InlineKeyboardButton(text=m_name, callback_data=f"selectmodel_{m_id}_{m_name}")])
        
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    select_text = await get_text(user_id, "select_model")
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
    await callback.message.answer(chat_start_txt.format(model_name))
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

@router.message(Command("model"))
@router.message(F.text.in_({"model", "/model"}))
async def cmd_model_exit(message: Message, state: FSMContext):
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

# --- ارسال پیام همگانی ---
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    txt = await get_text(callback.from_user.id, "send_broadcast")
    btn_back = await get_text(callback.from_user.id, "btn_back_main")
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

# --- مدیریت روترها ---
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
@router.message(BotStates.chatting)
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

    # پشتیبانی از استخراج متن از پیام و کپشن و خواندن فایل‌ها
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

    # گرفتن تاریخچه پیام‌های قبلی کاربر از دیتابیس
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            messages = [{"role": r[0], "content": r[1]} for r in reversed(rows)]
            
    # اضافه کردن پیام فعلی (با پشتیبانی از مالتی‌مدال/عکس در صورت وجود)
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

    # ذخیره پیام فعلی در دیتابیس به صورت متنی (برای جلوگیری از سنگینی دیتابیس، عکس مستقیم ذخیره نمی‌شود)
    db_content = content_text[:1000] + (" [Image Attached]" if image_base64 else "")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "user", db_content))
        await db.commit()
            
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": m_name, "messages": messages}
    
    # استفاده از ابزار استاندارد برای نمایش مداوم Typing
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
            
    # پشتیبانی از ارسال فایل (اگر متن از سقف مجاز تلگرام بیشتر بود، آن را بصورت txt می‌فرستد)
    if len(reply_text) > 4000:
        text_file = BufferedInputFile(reply_text.encode('utf-8'), filename="response.txt")
        await message.answer_document(text_file, caption="📄 The response was too long, so it's sent as a file.")
    else:
        await message.answer(reply_text)
    
    # ذخیره در دیتابیس (حداکثر 2000 کاراکتر برای خروجی)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)", (user_id, "assistant", reply_text[:2000] if len(reply_text) > 2000 else reply_text))
        await db.commit()

# ================= هندلر پیام‌های ناشناس / خارج از وضعیت =================
@router.message()
async def fallback_unknown(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, model_name FROM models") as cursor:
            models = await cursor.fetchall()
            
    if not models:
        # اگر مدلی وجود نداشت فقط هشدار دستور اشتباه را بفرست
        txt = await get_text(user_id, "invalid_command")
        await message.answer(txt)
    else:
        # اگر مدل وجود داشت، هم هشدار بده و هم دکمه‌های مدل‌ها را ضمیمه کن
        buttons = []
        for m_id, m_name in models:
            buttons.append([InlineKeyboardButton(text=m_name, callback_data=f"selectmodel_{m_id}_{m_name}")])
            
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        invalid_txt = await get_text(user_id, "invalid_command")
        select_txt = await get_text(user_id, "pls_select_model")
        
        # ترکیب دو پیغام
        final_text = f"{invalid_txt}\n\n{select_txt}"
        
        await message.answer(final_text, reply_markup=kb)

# ================= اجرای ربات =================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
