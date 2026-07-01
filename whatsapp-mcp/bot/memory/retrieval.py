"""
retrieval.py - Vector and keyword search for chat history.
"""

import json
import sqlite3
import re
from bot.memory.embeddings import DB_PATH, get_embedding, cosine_similarity
from bot.config import SEMANTIC_MIN_SIMILARITY, SEMANTIC_TOP_K

# Get the bridge DB path for keyword fallback
import os
BRIDGE_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', '..', 'whatsapp-bridge', 'store', 'messages.db'
)

def extract_keywords(text: str) -> list[str]:
    words = re.findall(r'\b[a-zA-Z0-9_]+\b', text.lower())
    stop_words = {"a","an","the","and","or","but","if","then","else","when","up","down","left","right","to","from","in","out","on","off","with","without","for","about","k","xa","chu","xu","ta","timi","ma","ko","hai","ho","ki","ni"}
    return [w for w in words if w not in stop_words and len(w) > 3]

def keyword_search_fallback(chat_jid: str, text: str, top_k: int = SEMANTIC_TOP_K) -> list[str]:
    keywords = extract_keywords(text)
    if not keywords:
        return []
    
    conn = sqlite3.connect(BRIDGE_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query_parts = []
    for kw in keywords[:3]:
        query_parts.append("content LIKE ?")
        
    if chat_jid == "GLOBAL":
        query = f"""
            SELECT content FROM messages 
            WHERE ({' OR '.join(query_parts)})
            ORDER BY timestamp DESC
            LIMIT {top_k * 2}
        """
        params = [f"%{kw}%" for kw in keywords[:3]]
    else:
        query = f"""
            SELECT content FROM messages 
            WHERE (chat_jid = ? OR chat_jid = '120363390805827846@g.us') AND ({' OR '.join(query_parts)})
            ORDER BY timestamp DESC
            LIMIT {top_k * 2}
        """
        params = [chat_jid] + [f"%{kw}%" for kw in keywords[:3]]
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [r['content'] for r in rows if r['content']]
    except Exception:
        return []
    finally:
        conn.close()

def get_context_for_reply(chat_jid: str, incoming_text: str) -> str:
    """Semantic search first; on any embedding API failure, fall back to keyword search."""
    q_vec = get_embedding(incoming_text, task_type="RETRIEVAL_QUERY")
    
    results = []
    if q_vec:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if chat_jid == "GLOBAL":
            cursor.execute("SELECT content, embedding FROM message_embeddings")
        else:
            cursor.execute("SELECT content, embedding FROM message_embeddings WHERE chat_jid IN (?, '120363390805827846@g.us')", (chat_jid,))
        rows = cursor.fetchall()
        conn.close()
        
        scored = []
        for row in rows:
            try:
                chunk_vec = json.loads(row["embedding"])
                if not isinstance(chunk_vec, list) or len(chunk_vec) == 0:
                    continue
                score = cosine_similarity(q_vec, chunk_vec)
                scored.append({"content": row["content"], "score": score})
            except Exception:
                continue
                
        scored.sort(key=lambda x: x["score"], reverse=True)
        results = [c["content"] for c in scored[:SEMANTIC_TOP_K] if c["score"] > SEMANTIC_MIN_SIMILARITY]
        
    if not results:
        # Fallback to keyword search
        results = keyword_search_fallback(chat_jid, incoming_text)
        
    if not results:
        return ""
        
    context_str = "\n".join(f"- {r}" for r in results[:SEMANTIC_TOP_K])
    return f"\n\n<relevant_memory>\n{context_str}\n</relevant_memory>"

def embed_and_store(chat_jid: str, message_id: str, content: str):
    vec = get_embedding(content, task_type="RETRIEVAL_DOCUMENT")
    if not vec:
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO message_embeddings (message_id, chat_jid, content, embedding)
            VALUES (?, ?, ?, ?)
        """, (message_id, chat_jid, content, json.dumps(vec)))
        conn.commit()
    except Exception as e:
        print(f"[memory] failed to store embedding: {e}")
    finally:
        conn.close()
