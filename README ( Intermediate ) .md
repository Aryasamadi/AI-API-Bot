🚀 AI-API-Bot – README (Intermediate)

🤖 This bot is a Telegram interface for multiple AI models (like GPT, DeepSeek, Claude, Gemini, etc.) through a configurable API router system. It supports both local SQLite and external cloud databases, and it can be deployed on Railway, any VPS, or any Python‑hosting service.

✨ Key Features:

🗂️ Manage multiple API routers (each with its own Base URL and API key)
➕ Add/delete models per router
👤 Users can select a model and chat with it
💾 Chat history per user (last 10 messages) is kept locally or in cloud DB
⚙️ Admin panel with password protection, force‑join channel, broadcast, and database management (clear cache or full wipe)
🌍 Fully localized in 9 languages (🇬🇧 EN, 🇮🇷 FA, 🇷🇺 RU, 🇸🇦 AR, 🇮🇳 HI, 🇹🇷 TR, 🇫🇷 FR, 🇩🇪 DE, 🇨🇳 ZH)
📋 Model names appear with inline code formatting – tap to copy
🎨 Emojis are assigned per model based on keywords (e.g., 🐟 for DeepSeek, 🧠 for GPT)

📦 What you need to run it:

🔑 A Telegram Bot Token (obtain from @BotFather)
🆔 Your Telegram user ID (to set as ADMIN_ID)
☁️ (Optional) A Cloudflare account with a D1 database, or any external database that provides a REST API (you can adapt the generic provider)

🌱 Environment Variables:

The bot reads the following variables from a .env file or from the hosting platform's environment:

🔹 BOT_TOKEN – your bot token
🔹 ADMIN_ID – your Telegram user ID (as an integer)

For cloud database, you have two options:

1️⃣ Using Cloudflare D1 (default):
   DB_PROVIDER=cloudflare
   CLOUDFLARE_ACCOUNT_ID = your Cloudflare account ID
   CLOUDFLARE_D1_DATABASE_ID = your D1 database ID
   CLOUDFLARE_API_TOKEN = your API token with D1:Edit permission

2️⃣ Using any other external database (generic):
   DB_PROVIDER=generic
   CLOUD_API_URL = the API endpoint of your external DB (e.g., https://api.supabase.co/...)
   CLOUD_API_TOKEN = your authentication token
   CLOUD_QUERY_BODY = a JSON template like {"sql": "query", "params": []} (you can adapt it)

💡 If cloud variables are missing or incomplete, the bot automatically falls back to local SQLite (bot_advanced.db) – perfect for testing or low‑usage setups.

🛠️ Deployment Options:

A) ☁️ Railway (easiest):
   1. Fork this repository on GitHub.
   2. Create a new project on Railway and connect it to your forked repo.
   3. In Railway's "Variables" tab, add all required environment variables (BOT_TOKEN, ADMIN_ID, and cloud ones if needed).
   4. Railway will automatically install dependencies (from requirements.txt) and run the bot.
   5. No extra commands needed – the bot runs continuously.

B) 🖥️ VPS (Ubuntu/Debian):
   1. Install Python 3.9+, git, and pip.
   2. Clone your forked repository.
   3. Create a .env file in the project root with all required variables.
   4. Install dependencies: pip install aiogram aiohttp aiosqlite python-dotenv
   5. Run: python bot.py
   6. Use screen or tmux to keep it running in the background.

C) 🧪 Local testing (without cloud DB):
   Just set BOT_TOKEN and ADMIN_ID in a .env file, run the script, and it will work with SQLite.

🧠 What the bot does internally:

- When a user sends /start, they see a welcome message and then a language selection (first time only) or directly the model list.
- The model list is paginated (12 models per page, 2 per row).
- Selecting a model clears the user's chat history (silently) and connects them to that model.
- All subsequent messages are sent to the model's API endpoint (with chat history context).
- Admin panel (/admin) provides full control: adding/removing routers and models, broadcasting, setting a global password, forcing users to join a channel, and managing the database (clear chat history or full wipe).

📌 Important Notes:

- The bot uses polling, not webhooks, so it works on Railway without extra configuration.
- If you use the generic DB provider, you may need to adjust the _cloud_request method in the code to match your API's response format – but the default works for most JSON‑based APIs that return a "results" or "data" array.
- All texts are stored in the LANGS dictionary inside the code – you can add or modify languages easily.

✅ That's it. The bot is ready to serve multiple AI models through a single Telegram interface with full admin control and multi‑language support. telegram :@ariasamadi
