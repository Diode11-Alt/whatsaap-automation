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
BURST_WINDOW      = 6    # seconds — collect msgs in same chat within this window

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
    ("openrouter", "google/gemini-2.5-flash"),      # Extremely fast, great at Nepali
    ("openrouter", "qwen/qwen-2.5-72b-instruct"),   # Powerful open-source
    ("openrouter", "openai/gpt-4o-mini"),           # Cheap, smart, fast
    ("openrouter", "anthropic/claude-3.5-haiku"),   # Super fast Anthropic
    ("openrouter", "meta-llama/llama-3.3-70b-instruct"), # Best Llama 3 on OpenRouter
    ("groq",       "llama-3.3-70b-versatile"),      # Fast free fallback
    ("gemini",     "gemini-2.0-flash"),             # Free fallback (next-gen)
    ("gemini",     "gemini-1.5-flash"),             # Free fallback (legacy)
    ("deepseek",   "deepseek-chat"),                # DeepSeek native
    ("openrouter", "anthropic/claude-3.5-sonnet"),  # Premium tier
    ("openrouter", "openai/gpt-4o"),                # Premium tier
    ("openrouter", "x-ai/grok-2-1212"),             # Premium tier Grok
    ("openrouter", "openrouter/auto"),              # Auto router fallback
]

MODELS_VISION = [
    ("openrouter", "google/gemini-2.5-flash"),      # Excellent vision, fast
    ("openrouter", "openai/gpt-4o-mini"),           # Great and cheap vision
    ("openrouter", "openai/gpt-4o"),                # Premium vision
    ("openrouter", "anthropic/claude-3.5-sonnet"),  # Premium vision
    ("openrouter", "qwen/qwen-vl-plus"),            # Qwen Vision specifically
    ("gemini",     "gemini-2.0-flash"),             # Free tier vision (next-gen)
    ("gemini",     "gemini-1.5-flash"),             # Free tier vision (legacy)
]

# ─── RAG Layer Configuration ─────────────────────────────────────────────────
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIM = 768
SEMANTIC_TOP_K = 5
SEMANTIC_MIN_SIMILARITY = 0.65
FACT_DEDUP_SIMILARITY = 0.90
EMBED_BACKFILL_BATCH_SIZE = 20
