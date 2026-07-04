# Rika AI Bot by cruz

This repository contains a Telegram AI bot built with python-telegram-bot and OpenAI. It provides conversational AI, memory, image generation, and admin controls.

This branch has been updated to run on Railway using webhook mode. To deploy on Railway you'll set environment variables in the Railway dashboard and run the web service.

Quick start (Railway)

1. In the Railway project, create environment variables (Settings > Variables):
   - TELEGRAM_TOKEN - your Telegram bot token
   - OPENAI_API_KEY - your OpenAI API key
   - BOT_ADMIN_IDS - comma-separated Telegram user IDs (admins)
   - WEBHOOK_URL - the public URL Railway gives your service (for example: "https://your-project.up.railway.app")
   - DB_PATH - optional, default: ./data/bot.db
   - SYSTEM_PROMPT - optional
   - TEMPERATURE - optional

2. Make sure the Start Command / Procfile is set to run the web process. The repo contains a Procfile with:

   web: python -m bot.bot

   Railway will run that command and expose a public HTTPS URL. The bot uses that URL to register the Telegram webhook.

3. Deploy. After the service is live, the bot will set its webhook to the Railway URL automatically.

Local development

- Copy .env.example to .env and fill in values for local testing.
- Run locally with polling (if WEBHOOK_URL is not set):
  python -m bot.bot

- Or run with Docker (the Dockerfile is included).

Security

- Do not commit secrets. Use Railway environment variables or a secret manager.

