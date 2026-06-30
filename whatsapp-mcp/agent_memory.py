import sqlite3
import os
import json
import math
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_memory.db')
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

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

def embed(text: str) -> list[float]:
    if not OPENAI_API_KEY:
        print("[warn] OPENAI_API_KEY not set. Returning empty embedding.")
        return [0.0] * 1536 # text-embedding-3-small dimension
        
    url = "https://api.openai.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "text-embedding-3-small",
        "input": text
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception as e:
        print(f"[error] Failed to fetch embedding: {e}")
        return [0.0] * 1536

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

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
    return history[::-1] # return oldest to newest

def retrieve_knowledge(query: str, top_k: int = 4) -> list[dict]:
    query_vector = embed(query)
    
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
            chunk_vector = json.loads(row["embedding"])
            score = cosine_similarity(query_vector, chunk_vector)
            scored.append({
                "source": row["source"],
                "content": row["content"],
                "score": score
            })
        except Exception:
            continue
            
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
