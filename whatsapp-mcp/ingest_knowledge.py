"""
ingest_knowledge.py — Load knowledge.txt into agent_memory.db
Run this whenever you update knowledge.txt:
    python3 ingest_knowledge.py
"""
import os
import sqlite3
import json
import time
from agent_memory import DB_PATH, get_embedding

def ingest_knowledge(source_file: str):
    if not os.path.exists(source_file):
        print(f"Error: {source_file} not found.")
        return

    with open(source_file, 'r', encoding='utf-8') as f:
        text = f.read()

    # Naive chunking: split by double newline (paragraph)
    raw_chunks = [c.strip() for c in text.split("\n\n") if len(c.strip()) > 30]

    if not raw_chunks:
        print("No valid chunks found to ingest.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Clear old chunks from this source first (re-ingest cleanly)
    source_name = os.path.basename(source_file)
    cursor.execute("DELETE FROM knowledge_chunks WHERE source = ?", (source_name,))

    count = 0
    print(f"Ingesting {len(raw_chunks)} chunks from {source_name}...")
    for i, chunk in enumerate(raw_chunks):
        # Fetch vector embedding
        vec = get_embedding(chunk)
        if not vec:
            print(f"Failed to embed chunk {i+1}/{len(raw_chunks)}")
            continue

        vec_str = json.dumps(vec)
        cursor.execute(
            "INSERT INTO knowledge_chunks (source, content, embedding) VALUES (?, ?, ?)",
            (source_name, chunk, vec_str)
        )
        count += 1
        print(f"Embedded chunk {i+1}/{len(raw_chunks)}")
        
        # Rate limit to avoid 429 Too Many Requests (Gemini has limits on free tier)
        time.sleep(1.5)

    conn.commit()
    conn.close()
    print(f"Successfully ingested {count} embedded chunks from {source_name}.")

if __name__ == "__main__":
    knowledge_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'knowledge.txt')
    ingest_knowledge(knowledge_file)
