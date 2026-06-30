"""
bridge_client.py - Interacts with the Go WhatsApp Bridge API.
"""

import requests
from bot.config import BRIDGE_URL, DOWNLOAD_API_URL

def get_latest_message_rowid() -> int:
    try:
        r = requests.get(f"{BRIDGE_URL}/api/latest_rowid", timeout=5)
        if r.status_code == 200:
            return r.json().get('last_rowid', 0)
        return 0
    except Exception as e:
        print(f"[DEBUG] Exception in get_latest_message_rowid: {e}", flush=True)
        return 0

def get_new_messages(last_rowid: int) -> list:
    try:
        r = requests.get(f"{BRIDGE_URL}/api/messages?last_rowid={last_rowid}", timeout=5)
        if r.status_code == 200:
            msgs = r.json()
            if not msgs:
                return []
            return msgs
        return []
    except Exception:
        return []

def send_whatsapp_message(chat_jid: str, content: str):
    try:
        payload = {"recipient": chat_jid, "message": content}
        resp = requests.post(f"{BRIDGE_URL}/api/send", json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"[sent] -> {chat_jid}: {content!r}")
        else:
            print(f"[send error] API returned {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[send error] {e}")

def send_presence(chat_jid: str, state: str = "typing"):
    """Send presence indicator to a chat (typing, recording, paused)."""
    try:
        payload = {"recipient": chat_jid, "state": state}
        requests.post(f"{BRIDGE_URL}/api/presence", json=payload, timeout=5)
    except Exception as e:
        print(f"[presence error] {e}")

def download_media(message_id: str, chat_jid: str) -> str | None:
    try:
        response = requests.post(DOWNLOAD_API_URL,
                                  json={"message_id": message_id, "chat_jid": chat_jid},
                                  timeout=10)
        response.raise_for_status()
        res = response.json()
        if res.get('success') and 'path' in res:
            return res['path']
    except Exception as e:
        print(f"[media download error] {e}")
    return None
