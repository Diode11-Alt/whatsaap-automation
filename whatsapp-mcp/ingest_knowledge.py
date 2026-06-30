import os
import json
import sqlite3
from agent_memory import embed, DB_PATH

def ingest_knowledge(source_file: str):
    if not os.path.exists(source_file):
        print(f"Error: {source_file} not found.")
        return
        
    with open(source_file, 'r', encoding='utf-8') as f:
        text = f.read()
        
    # Naive chunking: split by double newline
    raw_chunks = [c.strip() for c in text.split("\n\n") if len(c.strip()) > 30]
    
    if not raw_chunks:
        print("No valid chunks found to ingest.")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    source_name = os.path.basename(source_file)
    count = 0
    
    print(f"Ingesting {len(raw_chunks)} chunks from {source_name}...")
    for chunk in raw_chunks:
        vector = embed(chunk)
        if vector and len(vector) > 0 and vector[0] != 0.0:
            cursor.execute(
                "INSERT INTO knowledge_chunks (source, content, embedding) VALUES (?, ?, ?)",
                (source_name, chunk, json.dumps(vector))
            )
            count += 1
        else:
            print(f"Warning: Failed to get embedding for chunk: {chunk[:50]}...")
            
    conn.commit()
    conn.close()
    
    print(f"Successfully ingested {count} chunks.")

if __name__ == "__main__":
    knowledge_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'knowledge.txt')
    ingest_knowledge(knowledge_file)
