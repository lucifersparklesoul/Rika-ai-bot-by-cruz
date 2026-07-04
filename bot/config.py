from pydantic import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    TELEGRAM_TOKEN: str
    OPENAI_API_KEY: str
    BOT_ADMIN_IDS: Optional[str] = ""
    DB_PATH: str = "./data/bot.db"
    SYSTEM_PROMPT: str = "You are a helpful, friendly, and concise AI assistant for Telegram users."
    TEMPERATURE: float = 0.2
    OPENAI_CHAT_MODEL: str = "gpt-3.5-turbo"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    WEBHOOK_URL: Optional[str] = None
    PORT: int = 8000

    class Config:
        env_file = ".env"

settings = Settings()
