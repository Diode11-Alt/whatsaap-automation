"""
ingest_knowledge.py — Load knowledge.txt into agent_memory.db
Run this whenever you update knowledge.txt:
    python3 ingest_knowledge.py
"""
import os
import sqlite3
from agent_memory import DB_PATH

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
    for chunk in raw_chunks:
        # Store "[]" as a placeholder — retrieval uses TF-IDF, not embeddings
        cursor.execute(
            "INSERT INTO knowledge_chunks (source, content, embedding) VALUES (?, ?, ?)",
            (source_name, chunk, "[]")
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"Successfully ingested {count} chunks from {source_name}.")

if __name__ == "__main__":
    knowledge_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'knowledge.txt')
    ingest_knowledge(knowledge_file)
