AI-API-Bot – README (Beginner)

This is a Telegram bot that lets you chat with many different AI models (like ChatGPT, DeepSeek, Claude, etc.) all in one place. You can add your own API keys for different models and manage everything through an admin panel.

What you need to get started:

1. A Telegram account.
2. A bot token from Telegram (talk to @BotFather and create a new bot, then copy the token).
3. Your own Telegram user ID (you can get it from @userinfobot or similar).
4. A hosting service like Railway (free tier works) – or you can run it on your own computer (VPS) if you know how.

If you don't have a cloud database, don't worry – the bot uses a local file (SQLite) automatically. That's fine for small use.

Step‑by‑step to deploy on Railway (easiest way):

1. Create a GitHub account (if you don't have one) and fork this repository (click the "Fork" button on the top right of this GitHub page).
2. Go to Railway.app and sign in with your GitHub account.
3. Click "New Project" and choose "Deploy from GitHub repo".
4. Select the repository you just forked.
5. Railway will automatically start deploying your bot. Wait for it to finish (it takes about 1‑2 minutes).
6. Now, go to the "Variables" tab in your Railway project dashboard.
7. Add these two variables (they are required):
   - BOT_TOKEN = paste the token you got from @BotFather
   - ADMIN_ID = paste your Telegram user ID
8. (Optional) If you have a Cloudflare D1 database, add these three variables:
   - DB_PROVIDER = cloudflare
   - CLOUDFLARE_ACCOUNT_ID = your Cloudflare account ID
   - CLOUDFLARE_D1_DATABASE_ID = your D1 database ID
   - CLOUDFLARE_API_TOKEN = your API token with D1 permission
   If you don't have these, the bot will work with a local file, so skip this step.
9. After adding the variables, Railway will automatically redeploy your bot. Wait for it to finish.

That's it. Your bot is now running. Open Telegram, find your bot (by its username), and send /start. It will ask you to choose a language, then show you a list of models. But wait – there are no models yet! You need to add them.

How to add models (admin steps):

1. Send /admin to your bot (only you, the admin, can do this).
2. Use the "Add Router" button. You will be asked:
   - Base URL: the API endpoint for the model provider (e.g., https://api.openai.com/v1)
   - API Key (Token): your secret key for that provider
   - Model Name: the exact name of the model (e.g., gpt-3.5-turbo)
3. After you add a router, you can add more models to the same router using the "Add Model" button inside that router's details.

Now users (and you) can select a model and start chatting.

If you want to run this on your own computer (VPS) instead of Railway:

1. Install Python 3.9 or newer on your computer.
2. Download or clone this repository.
3. Create a file named .env in the project folder and put your BOT_TOKEN and ADMIN_ID in it.
4. Open a terminal (command prompt) in that folder and run:
   pip install aiogram aiohttp aiosqlite python-dotenv
5. Then run:
   python bot.py
6. The bot will start and stay running as long as the terminal is open. If you close the terminal, it stops – you can use screen or tmux to keep it running in the background.

Troubleshooting:

- If the bot doesn't start, check that BOT_TOKEN and ADMIN_ID are correct.
- If you see an error about "Cloudflare vars missing" but you don't want to use Cloudflare, just ignore it – the bot uses local SQLite.
- If you added cloud variables but the bot still uses local SQLite, make sure the variable names are exactly as shown above (case‑sensitive).
- To see if your bot is connected to the cloud DB, check the logs in Railway – you should see "Cloudflare D1 mode ACTIVE" or "Generic cloud DB mode ACTIVE".

That's all you need to know. The bot is ready to use. Good luck!
