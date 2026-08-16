🤖 Multi-Language AI Router Telegram Bot
An advanced, multi-language Telegram Bot built with Python (aiogram 3) and SQLite. It allows administrators to dynamically add multiple OpenAI-compatible AI API endpoints (Routers) and models, enabling users to switch between models seamlessly.

🌟 Features
Multi-Language Support: Fully localized for 9 languages: English, Persian , Russian, Arabic, Hindi, Turkish, French, German, and Chinese.

Dynamic API & Model Management: Add, list, or delete custom API endpoints and models on-the-fly via the Admin Panel.

Global Password Protection: Lock the bot with a master password or set it to none for public access.

Broadcast System: Send global announcements to all registered users.

Real-time Typing Status: Shows the typing... indicator while waiting for the AI response.

Context Memory: Maintains short-term conversation history per user for contextual responses.

📜 Bot Commands
Configure these commands via @BotFather:
👤 User Commands
/start - Select language, check status, or display the main menu.
/model - Exit current chat, clear conversation history, and return to model selection.
/lang - Switch the bot's interface language.

/user - Quick menu access to available AI models.

⚙️ Admin Commands
/admin - Open the administrator control panel (Authorized users only).

🛠️ Prerequisites & Setup
1. Requirements
Python 3.10+
Telegram Bot Token from @BotFather
Your Numeric Telegram ID from @userinfobot
2. Installation
Clone or download the project files, navigate to the folder, and install dependencies:
pip install aiogram aiohttp aiosqlite python-dotenv
3. Environment Configuration
Create a .env file in the root directory:
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_ID=your_numeric_telegram_id_here
4. Running the Bot
python bot.py
☁️ Deployment Options (VPS & Cloud Platforms)
Standard VPS (Ubuntu / Debian / Systemd): Recommended for 24/7 long-term uptime using systemd or pm2.

Railway.app / Render / Koyeb / Fly.io: Native Python support. Connect your GitHub repository directly, set Environment Variables (BOT_TOKEN & ADMIN_ID), and deploy.

PythonAnywhere: Works for lightweight usage. Note that Polling mode requires a paid tier; Webhook conversion is recommended for free tiers.

Cloudflare Workers: Requires converting the bot from Polling to Webhook architecture and adjusting SQLite storage to an external DB like Supabase/PostgreSQL.

This project is under active development, and the codebase is updated regularly.




🤖 ربات تلگرام هوش مصنوعی و مدیریت همه API های ارائه شده تاکنون 

یک ربات تلگرام پیشرفته و چندزبانه که با پایتون (aiogram 3) و SQLite توسعه یافته است.

این ربات به مدیران اجازه می‌دهد تا لینک‌های API و مدل‌های مختلف هوش مصنوعی سازگار با OpenAI و Gemini را به صورت دینامیک اضافه کنند و به کاربران امکان می‌دهد با مدل دلخواه خود گفتگو کنند.

🌟 ویژگی‌های کلیدی
پشتیبانی کامل از ۹ زبان: پشتیبانی از زبان‌های فارسی، انگلیسی، روسی، عربی، هندی، ترکی، فرانسوی، آلمانی و چینی.

مدیریت دینامیک API و مدل‌ها: امکان افزودن و حذف روترها و مدل‌های هوش مصنوعی از طریق پنل مدیریت.

سیستم قفل و رمز عبور: امکان محدود کردن استفاده از ربات با رمز عبور یا عمومی‌سازی آن.
ارسال پیام همگانی: قابلیت ارسال پیام متنی به تمام کاربران ربات.

نمایش وضعیت Typing: نمایش حالت typing... در پروفایل ربات هنگام دریافت پاسخ از AI.

حافظه مکالمه: حفظ تاریخچه آخرین پیام‌ها برای پاسخ‌دهی دقیق‌تر.

📜 لیست کامل دستورات ربات (Commands)
این دستورات در سورس ربات فعال هستند و می‌توانید آن‌ها را در @BotFather نیز تنظیم کنید:
👤 دستورات کاربران
/start - شروع به کار ربات، انتخاب زبان یا نمایش منوی خوش‌آمدگویی.
/model - خروج از چت فعلی، پاک‌سازی حافظه مکالمه و بازگشت به منوی انتخاب مدل.
/lang - تغییر زبان محیط ربات.
/user - دسترسی سریع به پنل و لیست مدل‌های هوش مصنوعی.
⚙️ دستورات مدیریت
/admin - باز کردن پنل اصلی مدیریت (تنها برای آیدی عددی ست‌شده در .env).
🛠️ پیش‌نیازها و راهنمای نصب
۱. پیش‌نیازها
پایتون نسخه ۳.۱۰ یا بالاتر
توکن ربات تلگرام از @BotFather
شناسه عددی تلگرام (Admin ID) از @userinfobot

۲. نصب پکیج‌ها
کد پروژه را دانلود کرده، ترمینال را در پوشه پروژه باز کنید و دستور زیر را اجرا کنید:
pip install aiogram aiohttp aiosqlite python-dotenv

۳. تنظیم فایل .env
یک فایل به نام .env در مسیر اصلی پروژه بسازید و اطلاعات خود را قرار دهید:
BOT_TOKEN=توکن_ربات_تلگرام_شما
ADMIN_ID=آیدی_عددی_تلگرام_شما

۴. اجرای ربات
python bot.py
☁️ روش‌های میزبانی و اجرای ربات (سرور و کلود)
سرور مجازی اختصاصی (VPS): بهترین گزینه برای اجرای دائمی با استفاده از سرویس‌دهنده‌های systemd یا pm2.

پلاتفرم‌های ابری (Railway.app / Render / Koyeb / Fly.io): می‌توانید پروژه را به گیتهاب متصل کرده و متغیرهای .env را در پنل این سرویس‌ها ست کنید تا ربات به صورت رایگان/آزمایشی ران شود.

PythonAnywhere: برای پلن رایگان بهتر است سورس ربات به حالت Webhook تغییر یابد، اما برای تست‌های اولیه مناسب است.

Cloudflare Workers: نیازمند تغییر ساختار کد از حالت Polling به Webhook و اتصال دیتابیس به یک DB ابری خارجی (مانند Supabase یا PostgreSQL) می‌باشد.

این پروژه در حال توسعه فعال است و کد آن به صورت منظم آپدیت می‌شود
