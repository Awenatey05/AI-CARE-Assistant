import os

from dotenv import load_dotenv

APP_NAME = "AI_CARE_ASSISTANT"

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL")
DATABASE_URL = os.getenv("DATABASE_URL")

TEMPERATURE = float(os.getenv("TEMPERATURE", "0"))