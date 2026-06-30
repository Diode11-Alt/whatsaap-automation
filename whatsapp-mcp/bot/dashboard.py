"""
dashboard.py - FastAPI router for the Web Dashboard UI.
Provides REST endpoints to manage bot state, memory, and API keys.
"""

import os
import json
import sqlite3
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends
from bot.state import BOT_STATE_FILE, load_bot_state, save_bot_state
from bot.memory.facts_store import DB_PATH as MEMORY_DB_PATH
from dotenv import set_key

router = APIRouter(prefix="/api")

# Models
class BotStateUpdate(BaseModel):
    active: Optional[bool] = None
    mute_all_groups: Optional[bool] = None
    muted_jids: Optional[List[str]] = None
    reply_only_jids: Optional[List[str]] = None
    general_instructions: Optional[List[str]] = None

class EnvUpdate(BaseModel):
    key: str
    value: str

class FactCreate(BaseModel):
    chat_jid: str
    fact_text: str

class FactUpdate(BaseModel):
    fact_text: str

# Endpoints
@router.get("/state")
def get_state():
    return load_bot_state()

@router.post("/state")
def update_state(update: BotStateUpdate):
    state = load_bot_state()
    update_data = update.dict(exclude_unset=True)
    for k, v in update_data.items():
        state[k] = v
    save_bot_state(state)
    return {"status": "success", "state": state}

@router.get("/env")
def get_env():
    # Only return keys to avoid leaking sensitive data in plain text unnecessarily,
    # or return masked values. We'll return full values so the user can edit them,
    # but in a real production environment this should be authenticated.
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    keys = {}
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.strip().split('=', 1)
                    keys[k] = v.strip('"\'')
    return keys

@router.post("/env")
def update_env(update: EnvUpdate):
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    # Using python-dotenv set_key for safe updates
    try:
        set_key(env_file, update.key, update.value)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/facts")
def get_facts():
    try:
        conn = sqlite3.connect(MEMORY_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        # Ensure we don't send gigantic embedding strings to the frontend
        cursor.execute("SELECT id, chat_jid, fact_text, source_message_id, created_at, last_confirmed_at FROM learned_facts ORDER BY created_at DESC LIMIT 100")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/facts")
def add_fact(fact: FactCreate):
    from bot.memory.embeddings import get_embedding
    try:
        embedding = get_embedding(fact.fact_text)
        emb_str = json.dumps(embedding)
        
        conn = sqlite3.connect(MEMORY_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO learned_facts (chat_jid, fact_text, embedding, source_message_id) VALUES (?, ?, ?, ?)",
            (fact.chat_jid, fact.fact_text, emb_str, "manual_entry")
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/facts/{fact_id}")
def delete_fact(fact_id: int):
    try:
        conn = sqlite3.connect(MEMORY_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM learned_facts WHERE id = ?", (fact_id,))
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/logs")
def get_logs():
    log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ai_conversations.log')
    if not os.path.exists(log_file):
        return {"logs": ""}
    
    # Read the last 100000 bytes for performance
    with open(log_file, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(size - 100000, 0))
        lines = f.read().decode('utf-8', errors='replace')
    
    return {"logs": lines}
