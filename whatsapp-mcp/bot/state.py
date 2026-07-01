"""
state.py - Global bot state and command parsing.
"""

import os
import json

BOT_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bot_state.json')

def load_bot_state():
    try:
        with open(BOT_STATE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "active": True,
            "muted_jids": [],        # JIDs to never reply to
            "reply_only_jids": [],   # If non-empty, ONLY reply to these
            "mute_all_groups": False, # Stop replying to all groups
            "general_instructions": [] # List of custom instructions provided
        }

def save_bot_state(state):
    with open(BOT_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def parse_command(text: str, state: dict, contact_memory: dict) -> tuple[dict, str]:
    """Parse natural language commands from Sujal in 'All data'. Returns updated state and response."""
    t = text.strip().lower()
    # --- Global stop/start ---
    if t in ['#stop', 'stop', 'pause']:
        state['active'] = False
        return state, "Bot paused. Send 'start' to resume."
    if t in ['#start', 'start', 'resume']:
        state['active'] = True
        return state, "Bot active. Replying to all."
    # --- Executive Briefing ---
    if t in ['#summary', 'summary', '#status', 'status', 'report', 'briefing', '#report', '#briefing']:
        report = generate_executive_briefing(state, contact_memory)
        return state, report

    # --- Mute a contact ---
    for keyword in ['mute', "don't reply", 'dont reply', 'stop replying']:
        if keyword in t:
            import re
            import time
            duration_sec = 0
            duration_str = ""
            dur_match = re.search(r'(?:for\s+)?(\d+)\s*(h|hr|hour|hours|m|min|mins|minute|minutes|d|day|days)', t)
            if dur_match:
                val = int(dur_match.group(1))
                unit = dur_match.group(2)
                if unit.startswith('h'):
                    duration_sec = val * 3600
                    duration_str = f"for {val} hour(s)"
                elif unit.startswith('m'):
                    duration_sec = val * 60
                    duration_str = f"for {val} min(s)"
                elif unit.startswith('d'):
                    duration_sec = val * 86400
                    duration_str = f"for {val} day(s)"
            
            for contact_key, profile in contact_memory.items():
                nick = profile.get('nickname', contact_key).lower()
                real = profile.get('real_name', '').lower()
                if nick in t or real in t or contact_key in t:
                    jid = profile.get('jid', '')
                    if jid and jid not in state.get('muted_jids', []):
                        if 'muted_jids' not in state: state['muted_jids'] = []
                        state['muted_jids'].append(jid)
                    if duration_sec > 0:
                        if 'muted_until' not in state: state['muted_until'] = {}
                        state['muted_until'][jid] = time.time() + duration_sec
                        return state, f"Muted {profile.get('nickname', contact_key)} {duration_str}. Will auto-unmute when time expires."
                    else:
                        if 'muted_until' in state and jid in state['muted_until']:
                            del state['muted_until'][jid]
                        return state, f"Muted {profile.get('nickname', contact_key)}. Will not reply."
    # --- Unmute a contact ---
    for keyword in ['unmute', 'start replying to', 'reply to']:
        if keyword in t and 'only' not in t:
            for contact_key, profile in contact_memory.items():
                nick = profile.get('nickname', contact_key).lower()
                real = profile.get('real_name', '').lower()
                if nick in t or real in t or contact_key in t:
                    jid = profile.get('jid', '')
                    state['muted_jids'] = [j for j in state.get('muted_jids', []) if j != jid]
                    if 'muted_until' in state and jid in state['muted_until']:
                        del state['muted_until'][jid]
                    return state, f"Unmuted {profile.get('nickname', contact_key)}."
    
    # Check for general rule
    if t.startswith("rule:") or t.startswith("always"):
        if 'general_instructions' not in state:
            state['general_instructions'] = []
        state['general_instructions'].append(text.strip())
        return state, f"AI_CONFIRM_RULE: {text.strip()}"
        
    return state, ""

def generate_executive_briefing(state: dict, contact_memory: dict) -> str:
    """Generate bulleted report: unread/recent activity, new facts, muted contacts, system health."""
    import sqlite3
    import time
    from datetime import datetime
    from bot.config import DB_PATH
    
    lines = ["📊 *EXECUTIVE BRIEFING & SYSTEM STATUS* 📊\n"]
    
    # 1. System Health & Active Status
    status_icon = "🟢 ACTIVE" if state.get('active', True) else "🔴 PAUSED (Not replying)"
    lines.append(f"• *System Status*: {status_icon}")
    
    # 2. Currently Muted Contacts
    muted_jids = state.get('muted_jids', [])
    muted_until = state.get('muted_until', {})
    if muted_jids:
        muted_names = []
        for jid in muted_jids:
            name = jid
            for k, p in contact_memory.items():
                if p.get('jid') == jid:
                    name = p.get('nickname', k)
                    break
            if jid in muted_until:
                rem_mins = max(0, int((muted_until[jid] - time.time()) / 60))
                muted_names.append(f"{name} ({rem_mins}m left)")
            else:
                muted_names.append(name)
        lines.append(f"• *Muted Contacts*: {', '.join(muted_names)}")
    else:
        lines.append("• *Muted Contacts*: None")
        
    # 3. Active Routines Count
    routine_count = sum(len(p.get('routines', [])) for p in contact_memory.values())
    lines.append(f"• *Active Proactive Routines*: {routine_count} scheduled across close friends")
    
    # 4. New Facts Learned Today / Recently
    try:
        bot_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bot_memory.db')
        conn = sqlite3.connect(bot_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT fact_text FROM learned_facts ORDER BY id DESC LIMIT 5")
        rows = cursor.fetchall()
        conn.close()
        if rows:
            lines.append("\n🧠 *Recent Learned Facts / Memories*:")
            for r in rows:
                lines.append(f"  - {r[0]}")
        else:
            lines.append("\n🧠 *Recent Learned Facts*: None recorded yet.")
    except Exception as e:
        lines.append(f"\n🧠 *Recent Learned Facts*: [Error reading DB: {e}]")
        
    return "\n".join(lines)

def get_chief_of_staff_context(query: str, contact_memory: dict) -> str:
    """Pull real-time SQL messages, contact history, and learned facts for Chief of Staff Q&A."""
    import sqlite3
    import re
    from bot.config import DB_PATH
    
    q_lower = query.lower()
    lines = []
    
    # 1. Check if any specific contact is mentioned
    target_jids = []
    target_names = []
    for key, prof in contact_memory.items():
        nick = prof.get('nickname', key).lower()
        real = prof.get('real_name', '').lower()
        if nick in q_lower or (real and real in q_lower) or key in q_lower:
            jid = prof.get('jid')
            if jid and jid not in target_jids:
                target_jids.append(jid)
                target_names.append(prof.get('nickname', key))
                
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 2. If target contact mentioned, fetch their last 15 messages
        if target_jids:
            lines.append(f"📌 *Recent Chat History with {', '.join(target_names)}*:")
            for jid in target_jids:
                cursor.execute("""
                    SELECT sender, content, timestamp, is_from_me FROM messages 
                    WHERE chat_jid = ? AND content IS NOT NULL AND content != '' 
                    ORDER BY timestamp DESC LIMIT 15
                """, (jid,))
                rows = cursor.fetchall()
                for r in reversed(rows):
                    sender_label = "Sujal (You)" if r['is_from_me'] else (r['sender'].split('@')[0] if r['sender'] else "Contact")
                    lines.append(f"  [{sender_label}]: {r['content']}")
        else:
            # Otherwise, fetch last 15 general incoming/outgoing messages across private chats
            lines.append("📌 *Recent WhatsApp Activity (Last 15 Messages Across All Private Chats)*:")
            cursor.execute("""
                SELECT chat_jid, sender, content, timestamp, is_from_me FROM messages 
                WHERE content IS NOT NULL AND content != '' AND chat_jid NOT LIKE '%@g.us%' 
                ORDER BY timestamp DESC LIMIT 15
            """)
            rows = cursor.fetchall()
            for r in reversed(rows):
                c_jid = r['chat_jid']
                c_name = c_jid.split('@')[0]
                for k, p in contact_memory.items():
                    if p.get('jid') == c_jid:
                        c_name = p.get('nickname', k)
                        break
                sender_label = "Sujal" if r['is_from_me'] else c_name
                lines.append(f"  [{c_name} chat - {sender_label}]: {r['content']}")
        conn.close()
    except Exception as e:
        lines.append(f"📌 *SQL Messages Query Error*: {e}")
        
    # 3. Keyword query against learned_facts in bot_memory.db
    try:
        bot_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bot_memory.db')
        conn2 = sqlite3.connect(bot_db)
        cursor2 = conn2.cursor()
        
        # Extract meaningful keywords from query (>3 chars)
        words = [w for w in re.findall(r'\w+', q_lower) if len(w) > 3 and w not in ('what', 'when', 'where', 'who', 'how', 'why', 'did', 'does', 'that', 'this', 'have', 'from', 'about', 'summary', 'status')]
        if words:
            query_conds = " OR ".join(["fact_text LIKE ?" for _ in words])
            params = [f"%{w}%" for w in words]
            cursor2.execute(f"SELECT fact_text, created_at FROM learned_facts WHERE {query_conds} ORDER BY id DESC LIMIT 15", params)
        else:
            cursor2.execute("SELECT fact_text, created_at FROM learned_facts ORDER BY id DESC LIMIT 15")
        rows2 = cursor2.fetchall()
        conn2.close()
        
        if rows2:
            lines.append("\n🧠 *Relevant Learned Facts / Long-term Memories*:")
            for r in rows2:
                lines.append(f"  - {r[0]} (recorded: {r[1]})")
    except Exception as e:
        lines.append(f"\n🧠 *Facts Query Error*: {e}")
        
    return "\n".join(lines)

