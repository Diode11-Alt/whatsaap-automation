"""
config.py - Core configuration constants for the bot.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── File Paths and Endpoints ─────────────────────────────────────────────────
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', 'whatsapp-bridge', 'store', 'messages.db'
)
WHATSAPP_API_URL = "http://localhost:3000/api/send"
DOWNLOAD_API_URL = "http://localhost:3000/api/download"
BRIDGE_URL = "http://localhost:3000"

# ─── Group Classification ────────────────────────────────────────────────────
GROUP_CONFIG = {
    # "120363XXXXXXXXXX@g.us": "CLASS",   # Add real JID here
    # "120363YYYYYYYYYY@g.us": "COMPANY",
    # "120363ZZZZZZZZZZ@g.us": "PUBLIC",
}

# ─── Timing ──────────────────────────────────────────────────────────────────
REPLY_DELAY_MIN   = 5    # seconds — minimum wait before replying
REPLY_DELAY_MAX   = 10   # seconds — maximum wait before replying
BURST_WINDOW      = 3    # seconds — collect msgs in same chat within this window

# ─── AI API Keys & Models ────────────────────────────────────────────────────
API_KEYS = {
    "gemini": [k for k in [
        os.environ.get("GEMINI_API_KEY")
    ] if k],
    "groq": [k for k in [
        os.environ.get("GROQ_API_KEY")
    ] if k],
    "deepseek": [k for k in [
        os.environ.get("DEEPSEEK_API_KEY")
    ] if k],
    "openrouter": [k for k in [
        os.environ.get("OPENROUTER_API_KEY_1"),
        os.environ.get("OPENROUTER_API_KEY_2"),
        os.environ.get("OPENROUTER_API_KEY_3"),
        os.environ.get("OPENROUTER_API_KEY_4"),
        os.environ.get("OPENROUTER_API_KEY_5"),
        os.environ.get("OPENROUTER_API_KEY_6"),
        os.environ.get("OPENROUTER_API_KEY")
    ] if k]
}

MODELS_TEXT = [
    ("groq",       "qwen/qwen3.6-27b"),             
    ("openrouter", "qwen/qwen-2.5-72b-instruct"),   
    ("groq",       "llama-3.3-70b-versatile"),      
    ("openrouter", "google/gemini-2.5-flash"),      
    ("openrouter", "openai/gpt-4o-mini"),           
    ("openrouter", "anthropic/claude-haiku-4-5"),   
    ("groq",       "meta-llama/llama-4-scout-17b-16e-instruct"), 
    ("deepseek",   "deepseek-chat"),
    ("gemini",     "gemini-1.5-flash"),
    ("openrouter", "anthropic/claude-3.5-sonnet"),
    ("openrouter", "openai/gpt-4o"),
    ("openrouter", "openrouter/auto"),
]

MODELS_VISION = [
    ("openrouter", "google/gemini-2.5-flash"),      
    ("openrouter", "qwen/qwen-2.5-72b-instruct"),   
    ("openrouter", "openai/gpt-4o-mini"),           
    ("openrouter", "anthropic/claude-haiku-4-5"),   
    ("openrouter", "openai/gpt-4o"),
    ("openrouter", "anthropic/claude-3.5-sonnet"),
    ("gemini",     "gemini-1.5-flash"),
]

# ─── RAG Layer Configuration ─────────────────────────────────────────────────
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIM = 768
SEMANTIC_TOP_K = 5
SEMANTIC_MIN_SIMILARITY = 0.55
FACT_DEDUP_SIMILARITY = 0.90
EMBED_BACKFILL_BATCH_SIZE = 20
