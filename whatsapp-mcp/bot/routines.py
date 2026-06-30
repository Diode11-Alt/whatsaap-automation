"""
routines.py - Proactive auto-texting routine engine.
"""

import os
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from bot.config import DB_PATH
from bot.contacts import CONTACT_MEMORY
from bot.prompts import CONTACT_PROMPT_MAP
from bot.history import get_chat_history
from bot.ai_client import get_ai_reply, should_send
from bot.bridge_client import send_whatsapp_message

NPT_TZ = timezone(timedelta(hours=5, minutes=45))
ROUTINES_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'routines_state.json')

def load_routines_state():
    try:
        with open(ROUTINES_STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_routines_state(state):
    with open(ROUTINES_STATE_FILE, 'w') as f:
        json.dump(state, f)

def get_last_message_time(chat_jid: str) -> datetime:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(timestamp) FROM messages WHERE chat_jid = ?", (chat_jid,))
    res = cursor.fetchone()[0]
    conn.close()
    if not res:
        return datetime.now(NPT_TZ) - timedelta(days=1)
    
    try:
        dt = datetime.fromisoformat(res.replace(' ', 'T').replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(NPT_TZ)
    except:
        return datetime.now(NPT_TZ) - timedelta(days=1)

def get_randomized_trigger_time(today_str: str, r_id: str, start_t: str, end_t: str) -> str:
    """Generate a pseudo-random time within the window that stays constant for the given day."""
    import hashlib
    seed_str = f"{today_str}_{r_id}"
    hash_val = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    
    h1, m1 = map(int, start_t.split(':'))
    h2, m2 = map(int, end_t.split(':'))
    
    start_mins = h1 * 60 + m1
    end_mins = h2 * 60 + m2
    
    if end_mins <= start_mins:
        return start_t # Fallback
        
    random_offset = hash_val % (end_mins - start_mins)
    trigger_mins = start_mins + random_offset
    
    trigger_h = trigger_mins // 60
    trigger_m = trigger_mins % 60
    return f"{trigger_h:02d}:{trigger_m:02d}"

def process_auto_routines():
    state = load_routines_state()
    now = datetime.now(NPT_TZ)
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    for contact_key, profile in CONTACT_MEMORY.items():
        routines = profile.get("routines", [])
        chat_jid = profile.get("jid")
        if not routines or not chat_jid:
            continue
            
        contact_name = profile.get("nickname", contact_key)
        last_msg_time = get_last_message_time(chat_jid)
        hours_since_last_msg = (now - last_msg_time).total_seconds() / 3600

        for r in routines:
            r_id = f"{contact_key}_{r['id']}"
            start_t, end_t = r["time_window"]
            
            # Get today's random trigger time within the window
            trigger_time = get_randomized_trigger_time(today_str, r_id, start_t, end_t)
            
            # Fire if we have passed the random trigger time, but we are still inside the overall window
            if trigger_time <= current_time_str <= end_t:
                if state.get(r_id) != today_str:
                    
                    # Prevent auto-texting if we are already actively chatting
                    if hours_since_last_msg < 2:
                        continue 
                    
                    print(f"[routine] Firing {r_id} for {chat_jid} (Scheduled for {trigger_time})")
                    
                    system_prompt = CONTACT_PROMPT_MAP.get(contact_key)
                    if not system_prompt:
                        continue
                        
                    # Inject routine prompt
                    routine_instruction = f"\n\n[SYSTEM ROUTINE TRIGGER]: {r['prompt']}\nGenerate a short, natural message based on this routine."
                    full_prompt = system_prompt.replace("{chat_name}", contact_name) + routine_instruction
                    
                    chat_history = get_chat_history(chat_jid, limit=15)
                    reply = get_ai_reply(full_prompt, chat_history, "[SYSTEM: Execute routine]")
                    
                    if reply and should_send(reply, "PERSONAL", chat_jid):
                        send_whatsapp_message(chat_jid, reply.strip())
                        state[r_id] = today_str
                        save_routines_state(state)
