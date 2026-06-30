"""
facts_store.py - Long-term facts extraction and storage.
"""

import json
import sqlite3
import re
from bot.memory.embeddings import DB_PATH, get_embedding, cosine_similarity
from bot.config import SEMANTIC_MIN_SIMILARITY, SEMANTIC_TOP_K

def extract_and_store_facts(chat_jid: str, ai_response: str):
    """Parse <remember> tags from AI response and store them in DB with embeddings."""
    remember_matches = re.findall(r'<remember>(.*?)</remember>', ai_response, re.DOTALL)
    if not remember_matches:
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for fact in remember_matches:
        fact = fact.strip()
        if len(fact) < 5:
            continue
            
        store_direct_fact(chat_jid, fact)

def store_direct_fact(chat_jid: str, fact: str):
    """Store a single fact string directly into the vector db."""
    vec = get_embedding(fact, task_type="RETRIEVAL_DOCUMENT")
    if not vec:
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO learned_facts (chat_jid, fact_text, embedding)
            VALUES (?, ?, ?)
        """, (chat_jid, fact, json.dumps(vec)))
        print(f"[memory] Stored direct fact: {fact}")
    except Exception as e:
        print(f"[memory] Failed to store direct fact: {e}")
    conn.commit()
    conn.close()

def get_learned_context(chat_jid: str, incoming_text: str) -> str:
    """Semantic search against learned_facts."""
    q_vec = get_embedding(incoming_text, task_type="RETRIEVAL_QUERY")
    if not q_vec:
        return ""
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT fact_text, embedding FROM learned_facts WHERE chat_jid = ?", (chat_jid,))
    rows = cursor.fetchall()
    conn.close()
    
    scored = []
    for row in rows:
        try:
            chunk_vec = json.loads(row["embedding"])
            if not isinstance(chunk_vec, list) or len(chunk_vec) == 0:
                continue
            score = cosine_similarity(q_vec, chunk_vec)
            scored.append({"fact": row["fact_text"], "score": score})
        except Exception:
            continue
            
    scored.sort(key=lambda x: x["score"], reverse=True)
    results = [c["fact"] for c in scored[:SEMANTIC_TOP_K] if c["score"] > SEMANTIC_MIN_SIMILARITY]
    
    if not results:
        return ""
        
    context_str = "\n".join(f"- {r}" for r in results)
    return f"\n\n<learned_facts>\n{context_str}\n</learned_facts>"
