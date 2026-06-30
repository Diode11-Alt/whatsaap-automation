import sqlite3
import os
import json
import math
import re
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_memory.db')
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_user ON messages(user_id, created_at)
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            content TEXT NOT NULL,
            embedding TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Initialize tables on load
init_db()

def save_message(user_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (user_id, role, content, int(datetime.now().timestamp()))
    )
    conn.commit()
    conn.close()

def get_history(user_id: str, limit: int = 16) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content FROM messages WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()

    history = [{"role": r["role"], "content": r["content"]} for r in rows]
    return history[::-1]  # oldest to newest

# ─── Vector Embeddings and Retrieval ─────────────────────────────────────────

def get_embedding(text: str) -> list[float]:
    """Get vector embedding using Gemini API."""
    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY not set.")
        return []
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={GEMINI_API_KEY}"
    payload = {
        "model": "models/text-embedding-004",
        "content": {
            "parts": [{"text": text}]
        }
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("embedding", {}).get("values", [])
    except Exception as e:
        print(f"Error getting embedding: {e}")
        return []

def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)

def retrieve_knowledge(query: str, top_k: int = 4) -> list[dict]:
    """Vector-based semantic retrieval using Gemini embeddings."""
    q_vec = get_embedding(query)
    if not q_vec:
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT source, content, embedding FROM knowledge_chunks")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    scored = []
    for row in rows:
        try:
            chunk_vec = json.loads(row["embedding"])
            if not isinstance(chunk_vec, list) or len(chunk_vec) == 0:
                continue
            
            score = _cosine_similarity(q_vec, chunk_vec)
            scored.append({
                "source": row["source"],
                "content": row["content"],
                "score": score
            })
        except Exception:
            continue

    # Sort by descending score
    scored.sort(key=lambda x: x["score"], reverse=True)
    
    # Filter out low-confidence matches
    return [c for c in scored[:top_k] if c["score"] > 0.5]
