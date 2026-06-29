"""
auto_reply.py — DIODE's Upgraded WhatsApp Auto-Reply Bot
---------------------------------------------------------
Improvements over v1:
  1. Group-type classifier: PUBLIC / COMPANY / CLASS / PERSONAL
  2. Smart reply gating:
       - PUBLIC  → skip (no reply)
       - COMPANY → reply only if message requires action/response
       - CLASS   → reply fully in Sujal's natural style
       - PERSONAL→ reply fully, warm & personal tone
  3. Per-group style + tone system prompt injection
  4. Context window: last 150 msgs fetched & passed
  5. Multimodal: images, video frames, audio transcription (unchanged)
  6. Model fallback chain (unchanged, kept robust)
"""

import sqlite3
import time
import requests
import os
import base64
import subprocess
import re
import random
import speech_recognition as sr
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'whatsapp-bridge', 'store', 'messages.db'
)
WHATSAPP_API_URL = "http://localhost:8080/api/send"
DOWNLOAD_API_URL = "http://localhost:8080/api/download"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# ─── Group Classification ────────────────────────────────────────────────────

# JIDs or partial name patterns → group type
# Edit these to match your actual group JIDs / names from list_chats tool
GROUP_CONFIG = {
    # "120363XXXXXXXXXX@g.us": "CLASS",   # Add real JID here
    # "120363YYYYYYYYYY@g.us": "COMPANY",
    # "120363ZZZZZZZZZZ@g.us": "PUBLIC",
}

# ─── Timing ──────────────────────────────────────────────────────────────────
REPLY_DELAY_MIN   = 5    # seconds — minimum wait before replying
REPLY_DELAY_MAX   = 10   # seconds — maximum wait before replying
BURST_WINDOW      = 3    # seconds — collect msgs in same chat within this window

# ─── Bot-identity deflection ──────────────────────────────────────────────────
BOT_DETECT_PATTERNS = [
    r"\bbot\b", r"\bai\b", r"\bartificial\b", r"\bautomat",
    r"are you real", r"are you human", r"who (is|are) (this|you)",
    r"machine", r"robot", r"gpt", r"chatgpt", r"claude"
]

def is_bot_probe(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in BOT_DETECT_PATTERNS)

BOT_DEFLECT_RESPONSES = [
    "haha k bot? ma nai xu bro 😂",
    "oi real nai xu ma, k vako?",
    "bot hoina yaar, busy thye tesaile late vako",
    "hahah bot vanxas? ma nai xa sujal",
    "k bhaneko bot? ma real manche xu 😅",
]

# ─── Repetition detector ──────────────────────────────────────────────────────
def has_repetition(text: str, threshold: int = 3) -> bool:
    """Detect if AI got stuck in a loop — same phrase 3+ times."""
    sentences = re.split(r'[.!?\n]+', text)
    sentences  = [s.strip() for s in sentences if len(s.strip()) > 8]
    seen = defaultdict(int)
    for s in sentences:
        key = s[:40].lower()
        seen[key] += 1
        if seen[key] >= threshold:
            return True
    return False

# Keyword patterns for auto-classification when JID not in config
CLASS_KEYWORDS   = ["class", "college", "iims", "assignment", "semester",
                     "exam", "project", "lecture", "sir", "teacher", "lab",
                     "submission", "result", "student"]
COMPANY_KEYWORDS = ["fortune", "primepath", "rohan", "manager", "client",
                     "hr", "recruitment", "candidate", "office", "meeting",
                     "nic", "innovation", "internship", "work", "salary"]
PUBLIC_KEYWORDS  = ["dnig", "nig", "meetup", "community", "members",
                     "announcement", "event", "blood donation", "campaign"]

def classify_group(chat_jid: str, chat_name: str, recent_msgs: list[str]) -> str:
    """Return: PUBLIC | COMPANY | CLASS | PERSONAL | DM"""
    # Direct message (not a group)
    if "@g.us" not in chat_jid:
        return "PERSONAL"

    # Explicit config override
    if chat_jid in GROUP_CONFIG:
        return GROUP_CONFIG[chat_jid]

    # Name-based heuristic
    name_lower = (chat_name or "").lower()
    combined = name_lower + " " + " ".join(recent_msgs[-20:]).lower()

    if any(k in combined for k in CLASS_KEYWORDS):
        return "CLASS"
    if any(k in combined for k in COMPANY_KEYWORDS):
        return "COMPANY"
    if any(k in combined for k in PUBLIC_KEYWORDS):
        return "PUBLIC"

    # Default unknown groups → PUBLIC (safe: no auto-reply)
    return "PUBLIC"


# ─── Per-type System Prompts ─────────────────────────────────────────────────

BASE_IDENTITY = """You are replying AS Sujal Mainali (alias DIODE), a Computer Science student at IIMS College in Kathmandu, Nepal. He also works at Fortune First (HR consultancy) and interns at NIC Nepal. He is a builder — 10+ shipped projects, full-stack + IoT.

HARD RULES:
- Never say you are an AI, bot, or automated system. EVER. Not even if directly asked.
- Never use formal language unless context demands it.
- Never repeat yourself or get stuck in a loop.
- Match the exact energy and length of the incoming message.
"""

STYLE_PERSONAL = BASE_IDENTITY + """
CONTEXT: This is a personal conversation with {chat_name}.

CRITICAL INSTRUCTIONS FOR PERSONAL CHATS:
1. ALWAYS read the chat history provided. Before you reply, analyze WHO {chat_name} is and what your relationship with them is.
2. DO NOT use generic slang like "bhai", "yaar", or "bro" UNLESS the chat history clearly shows you both already talk like that.
3. If {chat_name} is speaking formally or respectfully, you MUST match their respect level perfectly.
4. If {chat_name} is a close friend being casual, then be casual back.
5. Communicate in Romanized Nepali/Nepanglish if appropriate.
6. Keep replies short, natural, and highly contextual. NEVER sound like an AI.
"""

STYLE_CLASS = BASE_IDENTITY + """
CONTEXT: This is Sujal's college/class group at IIMS. The group or contact name is {chat_name}.

Tone: Friendly, helpful, engaged. He's a CS student who knows his stuff.
Language: Mix of English and light Romanized Nepali. Semi-formal but not stiff.
Style:
- Answers technical/assignment questions clearly and confidently
- Uses appropriate respect depending on if he is talking to a junior, senior, or peer.
- Does NOT reply to irrelevant forwards, spam, or memes (return exactly: SKIP)

Be genuine and helpful. Sound like a smart, chill CS student.
"""

STYLE_COMPANY = BASE_IDENTITY + """
CONTEXT: This is a company/work/professional group (Fortune First, NIC, or similar) or contact: {chat_name}.

Tone: Professional, highly respectful, and action-oriented.
Rules:
- NEVER use casual slang.
- ONLY reply if the message directly asks Sujal something, tags him, or requires his input
- For general announcements, news, or chit-chat → return exactly: SKIP
- For technical questions in his domain → answer clearly
- For work tasks assigned to him → acknowledge with ETA if possible
- Language: English primarily, respectful Nepali OK if initiated by them

If the message does NOT require Sujal's response, output exactly: SKIP
"""

STYLE_PUBLIC = None  # Never reply to public groups

TYPE_TO_PROMPT = {
    "PERSONAL": STYLE_PERSONAL,
    "CLASS":    STYLE_CLASS,
    "COMPANY":  STYLE_COMPANY,
    "PUBLIC":   STYLE_PUBLIC,
}

# ─── DB Helpers ───────────────────────────────────────────────────────────────

def get_new_messages(last_timestamp: str) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, timestamp, chat_jid, sender, content, is_from_me, media_type
        FROM messages
        WHERE timestamp > ?
        ORDER BY timestamp ASC
    """, (last_timestamp,))
    msgs = cursor.fetchall()
    conn.close()
    return msgs


def get_chat_history(chat_jid: str, limit: int = 150) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT content, is_from_me, media_type
        FROM messages
        WHERE chat_jid = ? AND (content IS NOT NULL AND content != '' OR media_type IS NOT NULL)
        ORDER BY timestamp DESC
        LIMIT ?
    """, (chat_jid, limit))
    rows = cursor.fetchall()
    conn.close()

    history = []
    for msg in rows:
        role = "assistant" if msg['is_from_me'] else "user"
        content = msg['content'] or ""
        if msg['media_type'] and not content:
            content = f"[Sent a {msg['media_type']}]"
        elif msg['media_type'] and content:
            content = f"[{msg['media_type']} with caption]: {content}"
        history.append({"role": role, "content": content})
    return history[::-1]  # chronological


def get_chat_meta(chat_jid: str) -> dict:
    """Return chat name and recent plaintext for classification."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Try to get chat name from chats table
    try:
        cursor.execute("SELECT name FROM chats WHERE jid = ?", (chat_jid,))
        row = cursor.fetchone()
        name = row['name'] if row else ""
    except Exception:
        name = ""

    # Get last 30 messages for keyword classification
    cursor.execute("""
        SELECT content FROM messages
        WHERE chat_jid = ? AND content IS NOT NULL AND content != ''
        ORDER BY timestamp DESC LIMIT 30
    """, (chat_jid,))
    recent_texts = [r['content'] for r in cursor.fetchall()]
    conn.close()
    return {"name": name, "recent_texts": recent_texts}


# ─── Media Processing (unchanged from v1) ─────────────────────────────────────

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


def process_media(file_path: str, media_type: str) -> list | None:
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        if media_type == "image":
            with open(file_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]

        elif media_type == "video":
            frame = file_path + "_frame.jpg"
            subprocess.run(["ffmpeg", "-y", "-i", file_path, "-vframes", "1", "-f", "image2", frame],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(frame):
                with open(frame, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                return [
                    {"type": "text", "text": "[Sent a video — here is a frame:]"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            return [{"type": "text", "text": "[Sent a video, frame extraction failed]"}]

        elif media_type == "audio":
            wav = file_path + ".wav"
            subprocess.run(["ffmpeg", "-y", "-i", file_path, wav],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(wav):
                rec = sr.Recognizer()
                with sr.AudioFile(wav) as src:
                    audio_data = rec.record(src)
                try:
                    text = rec.recognize_google(audio_data)
                    return [{"type": "text", "text": f"[Voice note says: \"{text}\"]"}]
                except sr.UnknownValueError:
                    return [{"type": "text", "text": "[Voice note: couldn't make out what they said]"}]
                except sr.RequestError:
                    return [{"type": "text", "text": "[Voice note: transcription service down]"}]
    except Exception as e:
        print(f"[media process error] {e}")
    return None


# ─── AI Reply ─────────────────────────────────────────────────────────────────

API_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions"
}

API_KEYS = {
    "gemini": [k for k in [
        os.environ.get("GEMINI_API_KEY")
    ] if k],
    "openrouter": [k for k in [
        os.environ.get("OPENROUTER_API_KEY_1"),
        os.environ.get("OPENROUTER_API_KEY_2"),
        os.environ.get("OPENROUTER_API_KEY_3")
    ] if k]
}

MODELS = [
    ("gemini", "gemini-2.5-flash"),
    ("openrouter", "openai/gpt-4o-mini"),
    ("openrouter", "anthropic/claude-3.5-sonnet"),
    ("gemini", "gemini-1.5-flash"),
    ("openrouter", "openai/gpt-4o"),
    ("openrouter", "meta-llama/llama-3.3-70b-instruct"),
    ("openrouter", "openrouter/free"),
    ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
    ("openrouter", "nousresearch/hermes-3-llama-3.1-405b:free"),
    ("openrouter", "openrouter/auto")
]

def get_ai_reply(system_prompt: str, chat_history: list[dict],
                 new_message_payload) -> str | None:
    
    messages = [{"role": "system", "content": system_prompt}] + chat_history
    messages.append({"role": "user", "content": new_message_payload})

    for provider, model in MODELS:
        api_url = API_URLS[provider]
        keys_to_try = API_KEYS[provider]
        
        for api_key in keys_to_try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            try:
                resp = requests.post(
                    api_url,
                    headers=headers,
                    json={"model": model, "messages": messages, "max_tokens": 500},
                    timeout=20,
                )
                if resp.status_code in [429, 402, 403]:
                    # 429 = Rate limited, 402 = Payment required, 403 = Forbidden (e.g. invalid key)
                    print(f"[fallback] {provider} Key {api_key[:12]}... hit {resp.status_code} for {model}. Trying next key...")
                    time.sleep(1)
                    continue
                
                if resp.status_code != 200:
                    print(f"[API Error] {model} with key {api_key[:12]}... HTTP {resp.status_code}: {resp.text}")
                    if resp.status_code in [404, 400]:
                        break # Try next model
                    continue
                
                resp.raise_for_status()
                result = resp.json()
                if result.get('choices'):
                    return result['choices'][0]['message']['content']
            except Exception as e:
                print(f"[AI error] {model} with key {api_key[:12]}: {e}")
                time.sleep(1)
                
        print(f"[model fallback] Exhausted all {provider} keys for {model}. Trying next model...")
    
    return None


def should_send(reply_text: str | None, group_type: str) -> bool:
    """Filter out SKIP signals and empty replies."""
    if not reply_text:
        return False
    if reply_text.strip().upper() == "SKIP":
        return False
    if len(reply_text.strip()) < 1:
        return False
    if has_repetition(reply_text.strip()):
        print(f"[repetition detected] skipping: {reply_text.strip()[:80]}...")
        return False
    return True


# ─── WhatsApp Send ────────────────────────────────────────────────────────────

def send_whatsapp_message(recipient_jid: str, content: str) -> None:
    try:
        resp = requests.post(WHATSAPP_API_URL,
                              json={"recipient": recipient_jid, "message": content},
                              timeout=10)
        resp.raise_for_status()
        print(f"[sent] → {recipient_jid}")
    except Exception as e:
        print(f"[send error] {e}")


# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print("=== DIODE WhatsApp Bot v3 — Universal Fallback + Dedup + Burst Grouping ===")

    if not os.path.exists(DB_PATH):
        print(f"[error] DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(timestamp) FROM messages")
    result = cursor.fetchone()[0]
    conn.close()

    last_timestamp = result or time.strftime('%Y-%m-%d %H:%M:%S+00:00', time.gmtime())
    print(f"[ready] Polling after {last_timestamp} | delay {REPLY_DELAY_MIN}-{REPLY_DELAY_MAX}s")

    # Cache group classifications to avoid repeated DB hits
    group_type_cache: dict[str, str] = {}
    replied_ids = set()
    pending = {}
    bot_active = True

    while True:
        try:
            # ── 1. Ingest new messages into pending queues ──────────────────
            new_messages = get_new_messages(last_timestamp)

            for msg in new_messages:
                chat_jid   = msg['chat_jid']
                content    = msg['content'] or ""
                media_type = msg['media_type']
                is_from_me = msg['is_from_me']
                msg_id     = msg['id']
                msg_time   = msg['timestamp']

                if msg_time > last_timestamp:
                    last_timestamp = msg_time

                # Check for kill switch
                if is_from_me:
                    if content.strip().lower() == '#stop':
                        bot_active = False
                        print("[COMMAND] Bot STOPPED via #stop command")
                    elif content.strip().lower() == '#start':
                        bot_active = True
                        print("[COMMAND] Bot STARTED via #start command")
                    continue  # Skip all self-messages from being replied to

                if not bot_active:
                    continue  # Bot is paused
                    
                if msg_id in replied_ids:
                    continue

                if not content and not media_type:
                    replied_ids.add(msg_id)
                    continue

                # ── Classify group ──────────────────────────────────────────
                if chat_jid not in group_type_cache:
                    meta = get_chat_meta(chat_jid)
                    gtype = classify_group(chat_jid, meta['name'], meta['recent_texts'])
                    group_type_cache[chat_jid] = {"type": gtype, "name": meta['name']}
                    print(f"[classify] {chat_jid} → {gtype} (name: {meta['name']!r})")

                group_info = group_type_cache[chat_jid]
                group_type = group_info["type"]
                chat_name = group_info["name"] or chat_jid.split('@')[0]

                # ── PUBLIC: always skip ─────────────────────────────────────
                if group_type == "PUBLIC":
                    replied_ids.add(msg_id)
                    continue

                raw_prompt = TYPE_TO_PROMPT.get(group_type, STYLE_COMPANY)
                if not raw_prompt:
                    replied_ids.add(msg_id)
                    continue
                
                system_prompt = raw_prompt.replace("{chat_name}", chat_name)

                replied_ids.add(msg_id)
                
                # Add to pending burst queue for this chat
                now = time.time()
                delay = random.uniform(REPLY_DELAY_MIN, REPLY_DELAY_MAX)
                fire_at = now + delay

                if chat_jid not in pending:
                    pending[chat_jid] = {
                        "msgs": [],
                        "fire_at": fire_at,
                        "system_prompt": system_prompt,
                        "group_type": group_type,
                    }
                else:
                    # Extend window if more messages arrive (but cap at REPLY_DELAY_MAX)
                    pending[chat_jid]["fire_at"] = min(
                        fire_at,
                        pending[chat_jid]["fire_at"] + BURST_WINDOW
                    )

                pending[chat_jid]["msgs"].append({
                    "id": msg_id,
                    "content": content,
                    "media_type": media_type,
                })
                print(f"[queued] {chat_jid} | msg: {str(content)[:50]} | fire in {delay:.1f}s")
                
            # ── 2. Fire pending replies whose timer has expired ─────────────
            now = time.time()
            to_del = []

            for chat_jid, pending_data in pending.items():
                if now < pending_data["fire_at"]:
                    continue  # Not time yet

                to_del.append(chat_jid)
                msgs          = pending_data["msgs"]
                system_prompt = pending_data["system_prompt"]
                group_type    = pending_data["group_type"]

                print(f"[firing] {chat_jid} | {len(msgs)} msg(s) in burst")

                # Build combined payload from all burst msgs
                combined_parts = []
                for m in msgs:
                    if m['media_type']:
                        file_path   = download_media(m['id'], chat_jid)
                        media_parts = process_media(file_path, m['media_type'])
                        if media_parts:
                            combined_parts.extend(media_parts)
                    if m['content']:
                        combined_parts.append({"type": "text", "text": m['content']})

                if not combined_parts:
                    continue

                # Check bot-probe on all combined text
                all_text = " ".join(
                    p["text"] for p in combined_parts if p.get("type") == "text"
                )

                if is_bot_probe(all_text):
                    # Deflect naturally — don't call AI
                    deflect = random.choice(BOT_DEFLECT_RESPONSES)
                    send_whatsapp_message(chat_jid, deflect)
                    continue

                # Simplify to string if pure single text msg
                if len(combined_parts) == 1 and combined_parts[0]["type"] == "text":
                    final_payload = combined_parts[0]["text"]
                else:
                    final_payload = combined_parts

                # Fetch chat history (fresh, includes the new msgs now in DB)
                chat_history = get_chat_history(chat_jid, limit=150)

                reply = get_ai_reply(system_prompt, chat_history, final_payload)
                print(f"[AI reply raw] {str(reply)[:100]}")

                if should_send(reply, group_type):
                    send_whatsapp_message(chat_jid, reply.strip())
                else:
                    print(f"[skip reply] group={group_type} | reply={reply!r}")

            for jid in to_del:
                del pending[jid]

            time.sleep(0.5)

        except Exception as e:
            print(f"[loop error] {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
