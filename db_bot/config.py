import os

from dotenv import load_dotenv


def get_token() -> str:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN (see .env.example).")
    return token


def get_base_url() -> str:
    return os.environ.get("DB_API_BASE_URL", "https://v6.db.transport.rest")
