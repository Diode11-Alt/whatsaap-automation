"""
facts_store.py - Long-term facts extraction and storage.
"""

import json
import sqlite3
import re
from bot.memory.embeddings import DB_PATH, get_embedding, cosine_similarity
from bot.config import SEMANTIC_MIN_SIMILARITY, SEMANTIC_TOP_K

def extract_and_store_facts(chat_jid: str, ai_response: str):
    """Parse <remember> and <remember_global> tags from AI response and store them in DB with embeddings."""
    remember_matches = re.findall(r'<remember>(.*?)</remember>', ai_response, re.DOTALL)
    global_matches = re.findall(r'<remember_global>(.*?)</remember_global>', ai_response, re.DOTALL)
    
    for fact in remember_matches:
        fact = fact.strip()
        if len(fact) >= 5:
            store_direct_fact(chat_jid, fact)
            
    for fact in global_matches:
        fact = fact.strip()
        if len(fact) >= 5:
            store_direct_fact("GLOBAL", fact)

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
        print(f"[memory] Stored direct fact ({chat_jid}): {fact}")
    except Exception as e:
        print(f"[memory] Failed to store direct fact: {e}")
    conn.commit()
    conn.close()

def get_learned_context(chat_jid: str, incoming_text: str) -> str:
    """Semantic search against learned_facts across chat, GLOBAL, and Command Center."""
    q_vec = get_embedding(incoming_text, task_type="RETRIEVAL_QUERY")
    if not q_vec:
        return ""
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if chat_jid == "GLOBAL":
        cursor.execute("SELECT id, fact_text, embedding FROM learned_facts ORDER BY id DESC")
    else:
        cursor.execute("""
            SELECT id, fact_text, embedding FROM learned_facts 
            WHERE chat_jid IN (?, 'GLOBAL', 'all_data', '120363390805827846@g.us')
            ORDER BY id DESC
        """, (chat_jid,))
    rows = cursor.fetchall()
    conn.close()
    
    scored = []
    max_id = max((row["id"] for row in rows), default=1)
    for row in rows:
        try:
            chunk_vec = json.loads(row["embedding"])
            if not isinstance(chunk_vec, list) or len(chunk_vec) == 0:
                continue
            score = cosine_similarity(q_vec, chunk_vec)
            # Add a slight recency boost (up to 0.05 for the newest fact) so newer facts break ties
            recency_boost = 0.05 * (row["id"] / max_id)
            scored.append({"fact": row["fact_text"], "score": score + recency_boost})
        except Exception:
            continue
            
    scored.sort(key=lambda x: x["score"], reverse=True)
    results = [c["fact"] for c in scored[:SEMANTIC_TOP_K] if c["score"] > SEMANTIC_MIN_SIMILARITY]
    
    if not results:
        return ""
        
    context_str = "\n".join(f"- {r}" for r in results)
    return f"\n\n<DYNAMIC_LEARNED_FACTS>\nThese are real-time verified facts learned from recent conversations and the Command Center. If anything here conflicts with older knowledge, YOU MUST TRUST THESE NEW FACTS:\n{context_str}\n</DYNAMIC_LEARNED_FACTS>"

def prune_and_consolidate_facts():
    """Nightly self-pruning routine: removes duplicate or highly overlapping facts using vector similarity."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_jid, fact_text, embedding FROM learned_facts ORDER BY id DESC")
    rows = cursor.fetchall()
    
    to_delete = set()
    by_jid: dict[str, list] = {}
    for r in rows:
        by_jid.setdefault(r["chat_jid"], []).append(r)
        
    for jid, facts in by_jid.items():
        # Compare every pair; if similarity > 0.82, mark older (lower id) for deletion
        for i in range(len(facts)):
            if facts[i]["id"] in to_delete:
                continue
            try:
                vec_i = json.loads(facts[i]["embedding"])
            except Exception:
                continue
            for j in range(i + 1, len(facts)):
                if facts[j]["id"] in to_delete:
                    continue
                try:
                    vec_j = json.loads(facts[j]["embedding"])
                    sim = cosine_similarity(vec_i, vec_j)
                    if sim > 0.82:
                        # facts[j] has lower id (since ordered DESC), delete it
                        to_delete.add(facts[j]["id"])
                        print(f"[pruning] Deduplicating fact in {jid}: '{facts[j]['fact_text']}' (sim={sim:.2f} with '{facts[i]['fact_text']}')")
                except Exception:
                    continue
                    
    if to_delete:
        cursor.executemany("DELETE FROM learned_facts WHERE id = ?", [(fid,) for fid in to_delete])
        conn.commit()
        print(f"[pruning] Removed {len(to_delete)} duplicate/outdated learned facts.")
        
    # Phase 2: LLM-based Fact Consolidation (review rows per jid, merge duplicates, delete outdated temporary statuses)
    for jid, facts in by_jid.items():
        remaining_facts = [f for f in facts if f["id"] not in to_delete]
        if len(remaining_facts) >= 4:
            try:
                from bot.ai_client import get_ai_reply
                fact_lines = [f"- {f['fact_text']}" for f in remaining_facts]
                prompt = (
                    f"You are an AI memory manager for contact/chat {jid}.\n"
                    "Below is the current list of learned facts stored in long-term memory:\n"
                    + "\n".join(fact_lines) + "\n\n"
                    "Your task:\n"
                    "1. Remove any outdated temporary statuses (like past travel dates, headaches from last week, temporary moods that are no longer relevant).\n"
                    "2. Merge duplicate or overlapping facts into concise, permanent facts.\n"
                    "3. Keep important permanent facts (e.g. relationship rules, preferences, nicknames, important background).\n"
                    "4. Return the clean, consolidated list of permanent facts as JSON: a list of strings [\"fact 1\", \"fact 2\", ...].\n"
                    "ONLY output the JSON array of strings, nothing else."
                )
                ai_res = get_ai_reply(prompt, [], "Consolidate facts.", has_media=False)
                if ai_res:
                    clean_json = re.sub(r'<thought>.*?</thought>', '', ai_res, flags=re.DOTALL).strip()
                    json_match = re.search(r'\[.*\]', clean_json, re.DOTALL)
                    if json_match:
                        new_facts_list = json.loads(json_match.group(0))
                        if isinstance(new_facts_list, list) and 0 < len(new_facts_list) <= len(remaining_facts):
                            old_ids = [f["id"] for f in remaining_facts]
                            cursor.executemany("DELETE FROM learned_facts WHERE id = ?", [(fid,) for fid in old_ids])
                            conn.commit()
                            for nf in new_facts_list:
                                if isinstance(nf, str) and len(nf.strip()) >= 5:
                                    vec = get_embedding(nf.strip(), task_type="FACT_STORAGE")
                                    if vec:
                                        cursor.execute("INSERT INTO learned_facts (chat_jid, fact_text, embedding) VALUES (?, ?, ?)", (jid, nf.strip(), json.dumps(vec)))
                            conn.commit()
                            print(f"[pruning] LLM consolidated {len(remaining_facts)} facts into {len(new_facts_list)} clean facts for {jid}.")
            except Exception as e:
                print(f"[pruning] LLM consolidation failed for {jid}: {e}")
                
    conn.close()
