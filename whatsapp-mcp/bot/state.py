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
    # --- Mute a contact ---
    for keyword in ['mute', "don't reply", 'dont reply', 'stop replying']:
        if keyword in t:
            for contact_key, profile in contact_memory.items():
                nick = profile.get('nickname', contact_key).lower()
                real = profile.get('real_name', '').lower()
                if nick in t or real in t or contact_key in t:
                    jid = profile.get('jid', '')
                    if jid and jid not in state.get('muted_jids', []):
                        if 'muted_jids' not in state: state['muted_jids'] = []
                        state['muted_jids'].append(jid)
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
                    return state, f"Unmuted {profile.get('nickname', contact_key)}."
    
    # Check for general rule
    if t.startswith("rule:") or t.startswith("always"):
        if 'general_instructions' not in state:
            state['general_instructions'] = []
        state['general_instructions'].append(text.strip())
        return state, f"AI_CONFIRM_RULE: {text.strip()}"
        
    return state, ""
