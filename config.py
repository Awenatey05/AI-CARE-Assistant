import os

from dotenv import load_dotenv

APP_NAME = "AI_CARE_ASSISTANT"

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

STORAGE_URL = os.getenv("STORAGE_URL")
STORAGE_ACCESS_KEY = os.getenv("STORAGE_ACCESS_KEY")
STORAGE_SECRET_KEY = os.getenv("STORAGE_SECRET_KEY")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "aicare-originals")

TEMPERATURE = float(os.getenv("TEMPERATURE", "0"))

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")

KOBO_BASE_URL = os.getenv("KOBO_BASE_URL")
KOBO_ASSET_UID = os.getenv("KOBO_ASSET_UID")
KOBO_API_TOKEN = os.getenv("KOBO_API_TOKEN")