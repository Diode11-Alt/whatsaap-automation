"""
embeddings.py - Gemini embeddings and DB setup for Vector RAG.
"""

import os
import json
import math
import sqlite3
import requests
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', '..', 'bot_memory.db'
)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS message_embeddings (
            message_id TEXT PRIMARY KEY,
            chat_jid   TEXT NOT NULL,
            content    TEXT NOT NULL,
            embedding  TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_jid ON message_embeddings(chat_jid)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learned_facts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_jid         TEXT NOT NULL,
            fact_text        TEXT NOT NULL,
            embedding        TEXT NOT NULL,
            source_message_id TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_confirmed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Initialize tables on load
init_db()

def get_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """Get vector embedding using Gemini API with exponential backoff for rate limits."""
    import time
    
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY not set.")
        return []
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={GEMINI_API_KEY}"
    payload = {
        "model": "models/gemini-embedding-2",
        "content": {
            "parts": [{"text": text}]
        },
        "taskType": task_type
    }
    
    max_retries = 5
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 429:
                # Rate limited, back off and retry
                wait_time = (2 ** attempt) + 1  # 2, 3, 5, 9, 17 seconds
                print(f"Embedding API rate limited (429). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
                
            resp.raise_for_status()
            data = resp.json()
            return data.get("embedding", {}).get("values", [])
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Error getting embedding after {max_retries} attempts: {e}")
            else:
                print(f"Error getting embedding (attempt {attempt+1}): {e}. Retrying...")
                time.sleep(2)
                
    return []

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)
