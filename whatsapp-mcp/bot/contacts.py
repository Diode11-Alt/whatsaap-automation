"""
contacts.py - Loads contact profiles from contact_memory.json.
"""

import json
import os
from bot.prompts import CONTACT_PROMPT_MAP

def load_contact_memory():
    """Load per-contact personality profiles from contact_memory.json"""
    memory_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'contact_memory.json')
    try:
        with open(memory_path, 'r') as f:
            data = json.load(f)
            return data.get('contacts', {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[memory] Could not load contact_memory.json: {e}")
        return {}

CONTACT_MEMORY = load_contact_memory()
print(f"[memory] Loaded {len(CONTACT_MEMORY)} contact profiles: {list(CONTACT_MEMORY.keys())}")

def get_contact_prompt(chat_name: str, chat_jid: str) -> str | None:
    """Check if this contact has a special personality profile."""
    name_lower = (chat_name or "").lower().strip()
    for contact_key, profile in CONTACT_MEMORY.items():
        match_names = profile.get('match_names', [])
        # Check by JID first (100% precision) or fallback to name matching
        is_match = False
        if profile.get('jid') == chat_jid:
            is_match = True
        elif any(mn.lower() in name_lower for mn in match_names):
            is_match = True
            
        if is_match:
            prompt = CONTACT_PROMPT_MAP.get(contact_key)
            if prompt:
                # Dynamically inject Sujal's persona if defined
                sujal_persona = profile.get('sujal_persona')
                if sujal_persona:
                    persona_text = "\n\nSUJAL'S EXACT PERSONA (MIRROR THIS PERFECTLY):\n"
                    for key, value in sujal_persona.items():
                        persona_text += f"- {key.replace('_', ' ').title()}: {value}\n"
                    prompt += persona_text
                    
                print(f"[memory] ★ Matched contact profile: {contact_key} for {chat_name!r}")
                return prompt
    return None
