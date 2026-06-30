
import sqlite3
import os
import json
import math
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_memory.db')

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

# ─── Local TF-IDF based retrieval (no external API needed) ─────────────────────
# This works offline and is sufficient for small knowledge bases (<1000 chunks).

def _tokenize(text: str) -> list[str]:
    return re.findall(r'\b\w+\b', text.lower())

def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    total = len(tokens) or 1
    return {t: (count / total) * idf.get(t, 1.0) for t, count in tf.items()}

def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
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
    return history[::-1]  # oldest to newest


def retrieve_knowledge(query: str, top_k: int = 4) -> list[dict]:
    """Local TF-IDF retrieval — no external API required."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT source, content FROM knowledge_chunks")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    # Build corpus token lists
    corpus = [(row["source"], row["content"], _tokenize(row["content"])) for row in rows]

    # Compute IDF over corpus
    N = len(corpus)
    df: dict[str, int] = {}
    for _, _, tokens in corpus:
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(N / freq + 1) for t, freq in df.items()}

    # Score query against each chunk
    q_tokens = _tokenize(query)
    q_vec = _tfidf_vector(q_tokens, idf)

    scored = []
    for source, content, tokens in corpus:
        chunk_vec = _tfidf_vector(tokens, idf)
        score = _cosine(q_vec, chunk_vec)
        scored.append({"source": source, "content": content, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return [c for c in scored[:top_k] if c["score"] > 0]
