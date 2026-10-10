import os

from dotenv import load_dotenv

APP_NAME = "AI_CARE_ASSISTANT"

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL")
MODEL_NAME = os.getenv("MODEL_NAME")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
DATABASE_URL = os.getenv("DATABASE_URL")

TEMPERATURE = float(os.getenv("TEMPERATURE", "0"))