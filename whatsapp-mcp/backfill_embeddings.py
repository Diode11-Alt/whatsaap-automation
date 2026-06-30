"""
backfill_embeddings.py - Script to retroactively compute embeddings for existing chat history.
"""

import sqlite3
import json
import time
from bot.memory.embeddings import DB_PATH, get_embedding
from bot.memory.retrieval import BRIDGE_DB_PATH

def backfill():
    # Connect to the source DB (messages)
    try:
        conn_src = sqlite3.connect(BRIDGE_DB_PATH)
        conn_src.row_factory = sqlite3.Row
        cur_src = conn_src.cursor()
        cur_src.execute("""
            SELECT id, chat_jid, content FROM messages 
            WHERE content IS NOT NULL AND content != ''
        """)
        messages = cur_src.fetchall()
        conn_src.close()
    except Exception as e:
        print(f"Error reading source messages: {e}")
        return

    # Connect to the target DB (embeddings)
    conn_dest = sqlite3.connect(DB_PATH)
    cur_dest = conn_dest.cursor()

    # Check which ones are already embedded
    cur_dest.execute("SELECT message_id FROM message_embeddings")
    existing_ids = {row[0] for row in cur_dest.fetchall()}
    
    print(f"Found {len(messages)} total messages.")
    to_process = [m for m in messages if str(m['id']) not in existing_ids]
    print(f"Found {len(to_process)} messages needing embeddings.")

    count = 0
    for m in to_process:
        m_id = str(m['id'])
        jid = m['chat_jid']
        content = m['content']
        
        vec = get_embedding(content, task_type="RETRIEVAL_DOCUMENT")
        if vec:
            cur_dest.execute("""
                INSERT INTO message_embeddings (message_id, chat_jid, content, embedding)
                VALUES (?, ?, ?, ?)
            """, (m_id, jid, content, json.dumps(vec)))
            count += 1
            if count % 10 == 0:
                print(f"Processed {count}/{len(to_process)} embeddings...")
                conn_dest.commit()
                # Respect rate limits for free tier API
                time.sleep(2)
        else:
            print(f"Failed to get embedding for message {m_id}")
            time.sleep(5) # Backoff
            
    conn_dest.commit()
    conn_dest.close()
    print(f"Backfill complete! Generated {count} new embeddings.")

if __name__ == "__main__":
    backfill()
