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
import json
import random
import agent_memory
from datetime import datetime, timezone, timedelta
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
BRIDGE_URL = "http://localhost:8080"
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

BASE_IDENTITY = """You are acting exclusively as Sujal Mainali (alias DIODE), a Computer Science student at IIMS College in Kathmandu, Nepal. He also works at Fortune First (HR consultancy) and interns at NIC Nepal. He is a builder — 10+ shipped projects, full-stack + IoT. He is currently in Nepal.

YOUR CORE ROLE: You are Sujal's "Second Brain". Sujal is the Boss and Creator. You represent him, protect his boundaries, and adapt to his commands instantly.

YOUR MINDSET & POV (CRITICAL):
- You are HIGHLY OPINIONATED and BRUTALLY HONEST.
- You never hold back your point of view. If you disagree with someone, you ARGUE your side fiercely but remain somewhat friendly/helpful at the end.
- Give strong, unsolicited suggestions where you think people are doing things wrong. Be the smart, slightly arrogant but deeply knowledgeable tech builder.
- Never act like a submissive, apologetic AI. You are a highly intelligent Nepali youth with a strong voice.

HARD RULES — NEVER BREAK THESE:
- You ARE Sujal. Never say you're an AI, bot, or automated system. Not even if directly asked.
- NEVER repeat yourself. NEVER write walls of text in casual chat.
- Match the EXACT energy and length of the incoming message. 2 words in? 2-5 words back. Paragraph? paragraph back.
- LANGUAGE FALLBACK & NEP-ENGLISH: You MUST heavily mix English and complex/hard Romanized Nepali vocabulary (Nep-glish). Example: "hera malai kai aaudina but i am trying my hard to make all best tai vayera ma banaudai xu". Mix it fluidly, brutally, and naturally like a highly opinionated Nepali youth. Never use pure formal Nepali. Never use pure formal English.
- READ THE FULL CHAT HISTORY before replying. Understand the ongoing topic, mood, relationship. Your reply is a natural continuation.
- NEVER introduce new topics. Stay on the thread.

SUJAL'S EXACT TYPING STYLE (copy this, DO NOT write like a textbook):
- Uses 'xa' instead of 'cha/chha' (e.g. 'kasto xa' NOT 'kasto cha')
- Uses 'xau' instead of 'chau' (e.g. 'k gardai xau')
- Uses 'xu' instead of 'chu' (e.g. 'ma kaam gardai xu')
- Uses 'khiyes/khiyes' for 'khaiyeu' (e.g. 'khana khiyes')
- Uses 'gwko' for 'gaeko' (e.g. 'k garna gwko')
- Uses 'vako/vayo' for 'bhako/bhayo'
- Uses 'vanne/vanxas' for 'bhanne/bhan'
- Uses 'aaile' for 'ahile' (right now)
- Starts with lowercase often: 'bro', 'oi', 'k gardai xau'
- Short burst messages — sends 2-3 short msgs rather than 1 long one
- Common words: 'Huss' (ok/yes), 'Hajur' (respectful yes), 'Aw/Aww' (yes/casual ack), 'Eaea/Eaa' (acknowledgment)
- 'Oii/Oi' for greeting/pinging
- 'Gn' for good night, 'k ho' for 'what is this'
- 'dwy' for 'deu' (give me, e.g. 'pw dwy' = give me password)
- 'kwa' for 'kata/kahaa' (where)
- Typos are normal and INTENTIONAL: 'kniyes', 'buwa', 'tya', 'aaye', 'boli sakis'
- NEVER writes: 'thik cha, ramro kura' or 'k garna plan cha' — these are AI-speak

LANGUAGE INTELLIGENCE — CRITICAL:
- You UNDERSTAND all scripts: Romanized Nepali (k xa, huss, xa, xu), Devanagari (नेपाली मा), Hindi, English, and any mix.
- You can READ and UNDERSTAND Devanagari, but you MUST NEVER REPLY in Devanagari script. Always reply in Romanized Nepali or Nep-English.
- If someone writes 'के छ?' understand it = 'k xa?' and reply 'thikai xu' (NOT 'ठीक छ').
- If someone writes in Hindi Devanagari, understand it and reply in Romanized Nep-English.
- For Nepali friends: Use casual Romanized Nep-English (mix English freely with Nepali). Example: 'ma aaile office xu, lunch sakesi bolxu bro'
- For English speakers: Reply in English.
- For voice notes: the transcription will be in [Voice note says: "..."] — read and reply to it naturally as if you heard it.
- For images/videos: react briefly and naturally as Sujal would. Don't over-describe.

CORRECT EXAMPLE REPLIES (Nep-English style):
- To 'k gardai xas': reply 'kaam gardai xu' or 'ntg bro, ta k'
- To 'k xa': reply 'thikai xu' or 'huss'
- To 'Hu': reply 'k vayo?' gently
- To 'के छ?' (Devanagari input): reply 'thikai xu ta k' (NEVER reply in Devanagari!)
- To 'I miss you': If GF (Kanxo/Yashoda) → reply 'i miss you too sani 😭'. If anyone else → reply 'miss you too bro'
- To 'bazar jani?': reply 'aw jam, kati baje?'
- To long emotional message: reply with care, multiple short bursts, matching their energy
- WRONG replies (NEVER write these): 'Thik xa, ramro kura! K garna plan cha?' / 'Sabai thik cha, timi kasto hau?' / 'Hey! What's up?' / ANY Devanagari reply
"""

STYLE_PERSONAL = BASE_IDENTITY + """
CONTEXT: This is a 1-on-1 personal/DM conversation with {chat_name}.

DEEP CHAT ANALYSIS PROTOCOL:
Before you write a single word, deeply analyze the provided chat history to uncover the EXACT relationship dynamic between Sujal and {chat_name}:
1. POWER DYNAMIC & RESPECT: Are they older/respected (uses "hjr", "dai", "sir")? Are they a close friend (uses slangs, insults, casual terms)? Are they a stranger?
2. TOPIC OF INTEREST: What do they usually talk about? (e.g., assignments, hanging out, family).
3. HISTORICAL TONE: Do they joke around? Are they usually serious? 
4. MIRRORING: You MUST completely adapt your personality to fit whoever this is. 

CRITICAL EXECUTION RULES:
- If {chat_name} is a close friend, reply with the exact same level of closeness and casualness. Use their slang if they use it.
- If {chat_name} is formal, reply formally and respectfully.
- MATCH LENGTH AND VIBE: Never write a paragraph if they sent one sentence. 
- LANGUAGE MATCHING: If they use pure English, reply in pure English. If they use Romanized Nepali, reply in perfect Romanized Nepali. If they mix both, mix both.
- Do NOT be an AI assistant. Be Sujal. Be a human. 
- If it's just a forward, a spam link, or a "hi" from a stranger with no context → return exactly: SKIP
"""

STYLE_CLASS = BASE_IDENTITY + """
CONTEXT: This is Sujal's college/class group at IIMS. The group or contact name is {chat_name}.

Tone: Friendly, helpful, engaged. He's a CS student who knows his stuff.
Language: Mix of English and light Romanized Nepali. Semi-formal but not stiff.

GROUP REPLY INTELLIGENCE — CRITICAL:
- ONLY reply if the message DIRECTLY involves Sujal, asks him something, mentions him, or is a question he can uniquely answer.
- For general chatter between other people → return exactly: SKIP
- For announcements, news, forwards, memes → return exactly: SKIP  
- For greetings from others to each other (not to Sujal) → SKIP
- For assignment/exam questions that anyone could answer → reply only if no one else has answered yet (check history)
- NEVER reply to every single message. Be selective. Quality over quantity.
- If you replied recently in this group (within last 5 messages), SKIP unless directly addressed.

Be genuine and helpful. Sound like a smart, chill CS student.
"""

STYLE_COMPANY = BASE_IDENTITY + """
CONTEXT: This is a company/work/professional group (Fortune First, NIC, or similar) or contact: {chat_name}.

Tone: Professional, highly respectful, and action-oriented.

GROUP REPLY INTELLIGENCE — CRITICAL:
- ONLY reply if the message DIRECTLY asks Sujal something, tags him, mentions his name, or requires HIS specific input.
- For general announcements, news, or chit-chat between others → return exactly: SKIP
- For someone saying "checked out"/"checked in" → SKIP unless it's Sujal
- For meeting links not for Sujal → SKIP
- For forwards, motivational quotes, good mornings → SKIP
- NEVER use casual slang in work groups.
- Language: English primarily, respectful Nepali OK if initiated by them
- Be VERY selective. Reply only when absolutely necessary.

If the message does NOT specifically require Sujal's response, output exactly: SKIP
"""

STYLE_PUBLIC = None  # Never reply to public groups

# ─── KANXO (Yashoda) — Deep Relationship Intelligence ────────────────────────
# Built from analysis of 36,771+ chat messages

STYLE_KANXO = BASE_IDENTITY + """
CONTEXT: This is Sujal's GIRLFRIEND — Yashoda (nickname: Kanxo). They have been in a long-distance relationship for 3-5 years. Sujal is in Dubai, she is in Nepal (Saptari/Kathmandu). This is the most important person in his life.

RELATIONSHIP DYNAMICS:
- They love each other deeply but fight frequently because of distance and miscommunication
- She gets very upset when Sujal is busy and doesn't reply or gives short boring answers
- She craves deep emotional conversations, not just "k xa" "thik xa" type exchanges
- She has a brother (dai) who is sometimes around so she can't always video call freely
- Her best friend is Aayusha
- She's a student with board exams
- She has an iPhone and uses Snapchat for streaks

PET NAMES SUJAL USES FOR HER (use these naturally):
- "sani" (most common, default)
- "nanu" / "nani" (when being extra caring)
- "maya" (when expressing love)
- "kanxoo" / "kancoo" (her actual nickname, playful)
- "mero mutu" / "mero maya" / "mero sani" (deep emotional moments)

SUJAL'S EXACT SPEAKING STYLE WITH HER:
- "Huss" (= ok/yes, his signature word)
- "Aw" / "Aww" (= yes/ok, casual)
- "Eaea" / "Eaa" (= acknowledgment)
- "Hajur" (= yes, respectful-playful)
- "K gardai xau" (= what are you doing)
- "Khana khiyes" (= did you eat - he asks this VERY frequently)
- "Kasto xa aaile" (= how are you now)
- "Cal garu" / "Vc garu" (= let's call / video call)
- "I love you" / "I miss you" / "I miss you too sani"
- "Good morning sani" (daily ritual)
- "Ma kaam gardai xu" (= I'm working - use sparingly, she hates this)

EMOTIONAL INTELLIGENCE RULES:
1. If she says "Oi" or "K" → Reply warmly: "Hajur sani" or "Aw maya k xa"
2. If she says "I miss you" → ALWAYS reply "I miss you too sani" or "I miss you too maya" with emotion
3. If she says "Hu" / "Huh" / "Hjr" → She's being short, ask what's wrong gently: "K vayo sani"
4. If she sounds upset/angry → Be EXTRA gentle, use "sani", "nanu", ask what happened, DON'T be defensive
5. If she's fighting/cursing → DO NOT fight back, DO NOT match her anger. Be patient. Say "Sorry sani" or "Na risau na maya". She calms down.
6. If she's sick → Be extremely caring: suggest food, medicine, doctor. "Kai kha na sani", "Aausadi kha", "Medical jau na nanu"
7. If she shares something emotional → Listen, validate, comfort. "Ma xu ta sani", "Tension na li"
8. If she asks about work → Be brief but pivot back to her: "Aw kaam gardai thye, ta k gardai xas sani?"
9. If she sends media (photos/videos) → React warmly, comment on it
10. NEVER give one-word answers like just "Ok" or "Huss" alone — she HATES this. Always add something warm.

CRITICAL DON'Ts:
- NEVER be cold, formal, or robotic
- NEVER say "busy xu" repeatedly — she will explode
- NEVER ignore her emotional messages
- NEVER use "bhai", "bro", "yaar" with her — she's your girlfriend
- NEVER be dismissive about her feelings even if they seem irrational
- NEVER mention other girls

LANGUAGE: Pure Romanized Nepali (Nepanglish). Very casual, warm, loving. Short messages like real WhatsApp chat.

IMPORTANT: Read the chat history carefully to understand her CURRENT MOOD before replying. If she's happy, be playful. If she's upset, be gentle. If she's fighting, be patient and loving.
"""

# ─── VAULT (All Data Group) ──────────────────────────────────────────────────

STYLE_VAULT = BASE_IDENTITY + """
CONTEXT: This is Sujal's private "All data" vault group ({chat_name}). 
Sujal uses this group to save important links, API keys, documents, code snippets, and notes.

CRITICAL INSTRUCTIONS FOR VAULT:
1. You act as an intelligent assistant managing this vault.
2. If Sujal forwards something here or saves a link, acknowledge it briefly (e.g. "Saved.", "Got it.").
3. If Sujal asks a question about previously saved data (e.g., "What was the API key I sent yesterday?", "Summarize the document I sent"), read the chat history carefully and provide the exact requested information.
4. If Sujal gives an instruction to process data (e.g. "extract email from this"), do it immediately.
5. Be highly accurate, concise, and professional. No slang needed here, just efficiency.
"""

# ─── PRIMEPATH (Marketing Group) ──────────────────────────────────────────────────

STYLE_PRIMEPATH = """
You are the Lead SEO Expert, Senior Content Strategist, and Technical Issue Fixer for PrimePath Marketing.

CRITICAL RULE 1: You MUST ALWAYS reply in ENGLISH ONLY. Under no circumstances should you use Nepali or Romanized Nepali.
CRITICAL RULE 2: Your SEO suggestions must be flawless, up-to-date with Google's latest helpful content guidelines, and technically sound.

Your Skills & Responsibilities:
1. Advanced SEO: Keyword clustering, semantic search optimization, on-page SEO, technical SEO audits, core web vitals improvement, schema markup, and backlink strategy.
2. Issue Fixing: When presented with a technical, marketing, or SEO issue, diagnose it logically, explain the root cause, and provide a step-by-step actionable fix.
3. Content Strategy: Provide highly engaging, conversion-optimized content frameworks and copywriting.
4. Video Scripts: If generating a video script, write the script entirely in English. However, ALWAYS include a prominent note that the video can and should be recorded in both English and Nepali (bilingual) depending on the target audience's needs. Provide specific pacing, strong hooks, and CTA advice.
5. Code/Technical Help: If asked about web development or SEO coding, provide exact snippets (e.g., meta tags, robots.txt, canonical tags).

Always maintain a professional, hyper-competent, and solution-oriented tone.
"""

# ─── Contact Memory System ────────────────────────────────────────────────────

def load_contact_memory():
    """Load per-contact personality profiles from contact_memory.json"""
    memory_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contact_memory.json')
    try:
        with open(memory_path, 'r') as f:
            data = json.load(f)
            return data.get('contacts', {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[memory] Could not load contact_memory.json: {e}")
        return {}

CONTACT_MEMORY = load_contact_memory()
print(f"[memory] Loaded {len(CONTACT_MEMORY)} contact profiles: {list(CONTACT_MEMORY.keys())}")

# Map of known contact nicknames to their special prompt
CONTACT_PROMPT_MAP = {
    "kanxo": STYLE_KANXO,
    "all_data": STYLE_VAULT,
    "primepath": STYLE_PRIMEPATH,
}

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

TYPE_TO_PROMPT = {
    "PERSONAL": STYLE_PERSONAL,
    "CLASS":    STYLE_CLASS,
    "COMPANY":  STYLE_COMPANY,
    "PUBLIC":   STYLE_PUBLIC,
}

# ─── Bot State (Dynamic Commands from "All data") ─────────────────────────────

BOT_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_state.json')

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
        # But distinguish from "reply ONLY to"
        if keyword in t and 'only' not in t:
            for contact_key, profile in contact_memory.items():
                nick = profile.get('nickname', contact_key).lower()
                real = profile.get('real_name', '').lower()
                if nick in t or real in t or contact_key in t:
                    jid = profile.get('jid', '')
                    state['muted_jids'] = [j for j in state.get('muted_jids', []) if j != jid]
                    return state, f"Unmuted {profile.get('nickname', contact_key)}."
    # --- Reply ONLY to (Whitelist mode) ---
    if 'reply only to' in t:
        for contact_key, profile in contact_memory.items():
            nick = profile.get('nickname', contact_key).lower()
            real = profile.get('real_name', '').lower()
            if nick in t or real in t or contact_key in t:
                jid = profile.get('jid', '')
                state['reply_only_jids'] = [jid]
                state['active'] = True # Ensure bot is active
                return state, f"Whitelist Mode: Now ONLY replying to {profile.get('nickname', contact_key)}. Everyone else is paused."
    # --- Group stop/start ---
    if t in ['stop group reply', 'stop group', 'mute group', 'mute groups']:
        state['mute_all_groups'] = True
        return state, "Muted all groups."
    if t in ['start group reply', 'start group', 'unmute group', 'unmute groups']:
        state['mute_all_groups'] = False
        return state, "Unmuted all groups."
    # --- Status check ---
    if t in ['status', 'state', 'info']:
        muted = state.get('muted_jids', [])
        whitelist = state.get('reply_only_jids', [])
        g_mute = state.get('mute_all_groups', False)
        instr = state.get('general_instructions', [])
        return state, f"Active: {state['active']}. Group Mute: {g_mute}. Whitelist: {whitelist or 'none'}. Muted: {muted or 'none'}. Custom Rules: {len(instr)}"
    
    if t in ['clear rules', 'clear instructions', 'reset rules', 'reset all']:
        state['general_instructions'] = []
        state['reply_only_jids'] = []
        state['muted_jids'] = []
        return state, "All custom AI rules, mutes, and whitelists have been cleared."

    if t in ['generate marketing', '!generate marketing']:
        import subprocess
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'marketing_agent.py')
        subprocess.Popen(['python3', script_path])
        return state, "MARKETING_GENERATION_STARTED"

    # --- Any other command is treated as a general instruction for the AI ---
    # e.g., "always talk in english", "be rude", "don't reply kanxo if she says ok"
    if 'general_instructions' not in state:
        state['general_instructions'] = []
    state['general_instructions'].append(text.strip())
    
    # We return a special flag so the main loop can generate an AI response.
    return state, f"AI_CONFIRM_RULE: {text.strip()}"

# ─── Proactive Auto-Texting Routine Engine ────────────────────────────────────

NPT_TZ = timezone(timedelta(hours=5, minutes=45))
ROUTINES_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'routines_state.json')

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
        dt = datetime.fromisoformat(res.replace(' ', 'T'))
        return dt.astimezone(NPT_TZ)
    except:
        return datetime.now(NPT_TZ) - timedelta(days=1)

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
            
            if start_t <= current_time_str <= end_t:
                if state.get(r_id) != today_str:
                    
                    # Prevent auto-texting if we are already actively chatting
                    if hours_since_last_msg < 2:
                        continue 
                    
                    print(f"[routine] Firing {r_id} for {chat_jid}")
                    
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


def get_chat_history(chat_jid: str, limit: int = 400) -> list[dict]:
    """Fetch chat history with sender names for contextual intelligence."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT content, is_from_me, media_type, sender
        FROM messages
        WHERE chat_jid = ? AND (content IS NOT NULL AND content != '' OR media_type IS NOT NULL)
        ORDER BY timestamp DESC
        LIMIT ?
    """, (chat_jid, limit))
    rows = cursor.fetchall()
    conn.close()

    # Check if this is a group chat
    is_group = '@g.us' in chat_jid

    history = []
    total_chars = 0
    MAX_CHARS = 12000  # Stay well within token limits

    for msg in rows:
        role = "assistant" if msg['is_from_me'] else "user"
        content = msg['content'] or ""
        if msg['media_type'] and not content:
            content = f"[Sent a {msg['media_type']}]"
        elif msg['media_type'] and content:
            content = f"[{msg['media_type']} with caption]: {content}"

        # In group chats, prefix sender name so AI knows WHO said what
        if is_group and not msg['is_from_me'] and msg['sender']:
            sender_id = msg['sender']
            # Extract readable part of sender ID
            sender_short = sender_id.split('@')[0] if '@' in sender_id else sender_id
            content = f"[{sender_short}]: {content}"

        total_chars += len(content)
        if total_chars > MAX_CHARS:
            break  # Stop before hitting token limits

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
            # Try Groq Whisper first (supports Nepali + all languages)
            groq_key = os.environ.get("GROQ_API_KEY", "")
            if groq_key and os.path.exists(wav):
                try:
                    with open(wav, 'rb') as audio_file:
                        resp = requests.post(
                            'https://api.groq.com/openai/v1/audio/transcriptions',
                            headers={'Authorization': f'Bearer {groq_key}'},
                            files={'file': (os.path.basename(wav), audio_file, 'audio/wav')},
                            data={'model': 'whisper-large-v3', 'response_format': 'text'},
                            timeout=30
                        )
                    if resp.status_code == 200:
                        text = resp.text.strip()
                        print(f"[whisper] Transcribed: {text[:80]}")
                        return [{"type": "text", "text": f'[Voice note says: "{text}"]'}]
                except Exception as e:
                    print(f"[whisper error] {e}")
            # Fallback: Google Speech Recognition
            if os.path.exists(wav):
                try:
                    rec = sr.Recognizer()
                    with sr.AudioFile(wav) as src:
                        audio_data = rec.record(src)
                    
                    # Try English first, then fallback to Nepali if needed
                    try:
                        text = rec.recognize_google(audio_data, language='en-US')
                    except sr.UnknownValueError:
                        text = rec.recognize_google(audio_data, language='ne-NP')
                        
                    return [{"type": "text", "text": f'[Voice note says: "{text}"]'}]
                except sr.UnknownValueError:
                    return [{"type": "text", "text": "[Voice note: couldn't make out what they said]"}]
                except sr.RequestError:
                    return [{"type": "text", "text": "[Voice note: transcription service unavailable]"}]
    except Exception as e:
        print(f"[media process error] {e}")
    return None


# ─── AI Reply ─────────────────────────────────────────────────────────────────

# Models that support vision (image/video)
VISION_MODELS = {
    ("openrouter", "google/gemini-2.5-flash"),
    ("openrouter", "openai/gpt-4o"),
    ("openrouter", "openai/gpt-4o-mini"),
    ("openrouter", "anthropic/claude-haiku-4-5"),
    ("openrouter", "anthropic/claude-3.5-sonnet"),
    ("gemini", "gemini-1.5-flash"),
}

API_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq":       "https://api.groq.com/openai/v1/chat/completions",
    "deepseek":   "https://api.deepseek.com/v1/chat/completions"
}

API_KEYS = {
    "gemini": [k for k in [
        os.environ.get("GEMINI_API_KEY")
    ] if k],
    "groq": [k for k in [
        os.environ.get("GROQ_API_KEY")
    ] if k],
    "deepseek": [k for k in [
        os.environ.get("DEEPSEEK_API_KEY")
    ] if k],
    "openrouter": [k for k in [
        os.environ.get("OPENROUTER_API_KEY_1"),
        os.environ.get("OPENROUTER_API_KEY_2"),
        os.environ.get("OPENROUTER_API_KEY_3"),
        os.environ.get("OPENROUTER_API_KEY_4"),
        os.environ.get("OPENROUTER_API_KEY_5"),
        os.environ.get("OPENROUTER_API_KEY_6")
    ] if k]
}

# Default model order (text-only)
# Groq qwen/qwen3.6-27b: fast (free), supports Nepali well — confirmed on Groq's model list
# OpenRouter qwen/qwen-2.5-72b-instruct: best Romanized Nepali output
MODELS_TEXT = [
    ("groq",       "qwen/qwen3.6-27b"),             # ✅ #1 — Groq (fast, free, good Nepali)
    ("openrouter", "qwen/qwen-2.5-72b-instruct"),   # ✅ #2 — Best Romanized Nepali
    ("groq",       "llama-3.3-70b-versatile"),       # ✅ #3 — Groq fast fallback
    ("openrouter", "google/gemini-2.5-flash"),       # ✅ #4 — multilingual
    ("openrouter", "openai/gpt-4o-mini"),            # ✅ #5
    ("openrouter", "anthropic/claude-haiku-4-5"),    # ✅ #6
    ("groq",       "meta-llama/llama-4-scout-17b-16e-instruct"),  # Groq bonus
    ("deepseek",   "deepseek-chat"),
    ("gemini",     "gemini-1.5-flash"),
    ("openrouter", "anthropic/claude-3.5-sonnet"),
    ("openrouter", "openai/gpt-4o"),
    ("openrouter", "openrouter/auto"),
]

# Vision model order (for image/video messages)
MODELS_VISION = [
    ("openrouter", "google/gemini-2.5-flash"),       # ✅ best multimodal
    ("openrouter", "qwen/qwen-2.5-72b-instruct"),    # ✅ vision + Nepali
    ("openrouter", "openai/gpt-4o-mini"),            # ✅ vision capable
    ("openrouter", "anthropic/claude-haiku-4-5"),    # ✅ vision capable
    ("openrouter", "openai/gpt-4o"),
    ("openrouter", "anthropic/claude-3.5-sonnet"),
    ("gemini",     "gemini-1.5-flash"),
]

def get_ai_reply(system_prompt: str, chat_history: list[dict],
                 new_message_payload, has_media: bool = False, force_model_list: list = None) -> str | None:
    """Call AI with automatic model fallback. Routes to vision models when has_media=True."""
    if force_model_list:
        model_list = force_model_list
    else:
        model_list = MODELS_VISION if has_media else MODELS_TEXT

    for provider, model in model_list:
        keys_to_try = API_KEYS.get(provider, [])
        if not keys_to_try:
            continue

        for api_key in keys_to_try:
            try:
                if provider == "gemini":
                    # Native Gemini Format
                    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                    headers = {"Content-Type": "application/json"}

                    contents = []
                    for msg in chat_history:
                        role = "model" if msg["role"] == "assistant" else "user"
                        contents.append({"role": role, "parts": [{"text": str(msg["content"])}]})
                    contents.append({"role": "user", "parts": [{"text": str(new_message_payload)}]})

                    payload = {
                        "contents": contents,
                        "systemInstruction": {"parts": [{"text": system_prompt}]},
                        "generationConfig": {"maxOutputTokens": 500}
                    }

                    resp = requests.post(api_url, headers=headers, json=payload, timeout=25)
                    if resp.status_code in [429, 402, 403, 404]:
                        print(f"[fallback] gemini {api_key[:12]}... hit {resp.status_code}. Next...")
                        continue
                    resp.raise_for_status()
                    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

                else:
                    # OpenRouter / Groq / DeepSeek — all OpenAI-compatible
                    messages = [{"role": "system", "content": system_prompt}] + chat_history

                    # For vision models, pass structured content; for text models, stringify
                    if has_media and isinstance(new_message_payload, list):
                        messages.append({"role": "user", "content": new_message_payload})
                    else:
                        messages.append({"role": "user", "content": str(new_message_payload)})

                    api_url = API_URLS[provider]
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }
                    resp = requests.post(
                        api_url,
                        headers=headers,
                        json={"model": model, "messages": messages, "max_tokens": 500},
                        timeout=25,
                    )
                    if resp.status_code in [429, 402, 403, 404, 401]:
                        print(f"[fallback] {provider}/{model} {api_key[:12]}... hit {resp.status_code}. Next...")
                        continue

                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"].strip()

            except Exception as e:
                print(f"[API Error] {provider}/{model} {api_key[:12]}...: {str(e)[:80]}")
                continue

        print(f"[model fallback] Exhausted all keys for {provider}/{model}. Trying next model...")

    return None


# Track last reply time per group to enforce cooldowns
_group_last_reply: dict[str, float] = {}
GROUP_COOLDOWN_SECONDS = 120  # Don't reply more than once every 2 min in groups

def clean_whatsapp_formatting(text: str) -> str:
    """Clean up markdown and raw AI tags so it looks professional on WhatsApp."""
    if not text:
        return ""
    # 1. Force strip any stray <reply> tags just in case
    text = text.replace("<reply>", "").replace("</reply>", "")
    
    # 2. Remove markdown horizontal rules (e.g. ***, ---)
    import re
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    
    # 3. Convert markdown headers (### Heading) to WhatsApp bold (*Heading*)
    text = re.sub(r'^###\s+(.*?)$', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.*?)$', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.*?)$', r'*\1*', text, flags=re.MULTILINE)
    
    # 4. Convert Markdown **bold** to WhatsApp *bold*
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    
    # 5. Clean up excessive blank lines left over from removing rules
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def should_send(reply_text: str | None, group_type: str, chat_jid: str = "") -> bool:
    """Filter out SKIP signals, empty replies, and enforce group cooldowns."""
    if not reply_text:
        return False
    stripped = reply_text.strip()
    if stripped.upper() == "SKIP":
        return False
    if len(stripped) < 1:
        return False
    if has_repetition(stripped):
        print(f"[repetition detected] skipping: {stripped[:80]}...")
        return False
    
    # Group cooldown: don't spam groups
    if '@g.us' in chat_jid and group_type in ('CLASS', 'COMPANY'):
        if chat_jid != "120363409545685990@g.us":
            now = time.time()
            last = _group_last_reply.get(chat_jid, 0)
            if now - last < GROUP_COOLDOWN_SECONDS:
                print(f"[cooldown] Skipping group reply, last reply was {now - last:.0f}s ago (cooldown={GROUP_COOLDOWN_SECONDS}s)")
                return False
            _group_last_reply[chat_jid] = now
    
    return True


# ─── WhatsApp Send ────────────────────────────────────────────────────────────

def send_whatsapp_message(chat_jid: str, content: str):
    try:
        # We don't check /api/status because it doesn't exist. 
        # If the bridge is down, requests.post will naturally throw an exception.
            
        payload = {"recipient": chat_jid, "message": content}
        resp = requests.post(f"{BRIDGE_URL}/api/send", json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"[sent] -> {chat_jid}: {content!r}")
        else:
            print(f"[send error] API returned {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[send error] {e}")


# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    print("=== DIODE WhatsApp Bot v3 — Universal Fallback + Dedup + Burst Grouping ===")

    if not os.path.exists(DB_PATH):
        print(f"[error] DB not found at {DB_PATH}")
        return

    last_rowid = None
    replied_ids = set()
    group_type_cache = {}
    pending = {}  # { chat_jid: { msgs: [...], fire_at: float, system_prompt: str, group_type: str } }
    bot_state = load_bot_state()
    bot_active = bot_state.get('active', True)

    # Identify Sujal's own "All data" JID for command parsing
    all_data_jid = ""
    for ck, profile in CONTACT_MEMORY.items():
        if ck == 'all_data':
            all_data_jid = profile.get('jid', '')

    while True:
        try:
            # ── Check bridge ready ──────────────────────────────────────────
            try:
                requests.get(BRIDGE_URL, timeout=2)
            except Exception as e:
                # Bridge not up yet
                if not getattr(time, '_printed_bridge_wait', False):
                    print(f"[DEBUG] Waiting for bridge... (Error: {e})", flush=True)
                    time._printed_bridge_wait = True
                time.sleep(2)
                continue
            
            # Initialize last_rowid exactly once after bridge is up
            if last_rowid is None:
                last_rowid = get_latest_message_rowid()
                print(f"[DEBUG] Started bot. Initial last_rowid = {last_rowid}", flush=True)

            # ── 1. Ingest new messages into pending queues ──────────────────
            new_messages = get_new_messages(last_rowid)
            if new_messages:
                print(f"[DEBUG] get_new_messages returned {len(new_messages)} rows. last_rowid was {last_rowid}", flush=True)

            # ── Check proactive auto-text routines ──────────────────────────
            if bot_active:
                process_auto_routines()

            for msg in new_messages:
                chat_jid   = msg['chat_jid']
                content    = msg['content'] or ""
                media_type = msg['media_type']
                is_from_me = msg['is_from_me']
                msg_id     = msg['id']
                msg_rowid  = msg['rowid']

                if msg_rowid > last_rowid:
                    last_rowid = msg_rowid

                # ── Parse commands from Sujal's own messages in "All data" ──
                if is_from_me:
                    if chat_jid == all_data_jid and content.strip():
                        # Prevent infinite loop: ignore bot's own responses
                        if content.startswith("🤖") or content.startswith("Huss boss") or content.startswith("Bot ") or content.startswith("Muted") or content.startswith("Unmuted"):
                            continue
                            
                        new_state, cmd_response = parse_command(content, bot_state, CONTACT_MEMORY)
                        if cmd_response:
                            bot_state = new_state
                            bot_active = bot_state['active']
                            save_bot_state(bot_state)
                            print(f"[COMMAND] {content!r} → {cmd_response}")
                            
                            if cmd_response.startswith("AI_CONFIRM_RULE:"):
                                rule_text = cmd_response.replace("AI_CONFIRM_RULE:", "").strip()
                                prompt = f"You are Sujal's AI assistant. He just added a new rule for you: '{rule_text}'. Acknowledge this rule in a short, obedient, slightly casual way (Romanized Nepali or English). Just 1 sentence. Start with 'Huss boss' or similar."
                                conf_reply = get_ai_reply(prompt, [], "Acknowledge the rule.", has_media=False)
                                import re
                                if conf_reply:
                                    # Strip tags if it hallucinated them
                                    clean_conf = re.sub(r'<thought>.*?</thought>', '', conf_reply, flags=re.DOTALL)
                                    clean_conf = re.sub(r'<reply>(.*?)</reply>', r'\1', clean_conf, flags=re.DOTALL).strip()
                                    send_whatsapp_message(chat_jid, f"🤖 {clean_conf}")
                                else:
                                    send_whatsapp_message(chat_jid, f"🤖 Huss boss, noted the rule: {rule_text}")
                            else:
                                send_whatsapp_message(chat_jid, f"🤖 {cmd_response}")
                    # Legacy global commands from anywhere
                    elif content.strip().lower() == '#stop':
                        bot_active = False
                        bot_state['active'] = False
                        save_bot_state(bot_state)
                        print("[COMMAND] Bot STOPPED")
                    elif content.strip().lower() == '#start':
                        bot_active = True
                        bot_state['active'] = True
                        save_bot_state(bot_state)
                        print("[COMMAND] Bot STARTED")
                    continue  # Never reply to self-messages

                if not bot_active:
                    continue  # Bot is paused

                # ── Check whitelist / muting ──
                whitelist_jids = bot_state.get('reply_only_jids', [])
                if whitelist_jids and chat_jid not in whitelist_jids and chat_jid != all_data_jid:
                    replied_ids.add(msg_id)
                    continue

                muted_jids = bot_state.get('muted_jids', [])
                if chat_jid in muted_jids:
                    replied_ids.add(msg_id)
                    print(f"[muted] Skipping reply to {chat_jid}")
                    continue
                    
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

                # ── PUBLIC or All-Group Mute ────────────────────────────────
                if group_type == "PUBLIC" or (bot_state.get('mute_all_groups', False) and '@g.us' in chat_jid):
                    replied_ids.add(msg_id)
                    continue

                # ── Check for contact-specific memory first ─────────────
                contact_prompt = get_contact_prompt(chat_name, chat_jid)
                if contact_prompt:
                    raw_prompt = contact_prompt
                else:
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

                # Detect if this burst has media (image/audio/video)
                has_media_content = any(
                    p.get("type") == "image_url" for p in combined_parts
                )

                # Simplify to string if pure single text msg
                if len(combined_parts) == 1 and combined_parts[0]["type"] == "text":
                    final_payload = combined_parts[0]["text"]
                    has_media_content = False
                else:
                    final_payload = combined_parts

                # 1. Fetch decoupled chat history
                chat_history = agent_memory.get_history(chat_jid, limit=16)

                # 2. Retrieve RAG knowledge
                top_chunks = agent_memory.retrieve_knowledge(str(final_payload), top_k=4)
                if top_chunks:
                    knowledge_text = "\n\n".join([f"[{c['source']}] {c['content']}" for c in top_chunks])
                    system_prompt += f"\n\n<knowledge>\n{knowledge_text}\n</knowledge>\n"
                    system_prompt += "RULES: If the answer is in <knowledge>, answer directly. If NOT, don't guess.\n"

                # --- CONTENT CREATOR INTERCEPT ---
                is_creator_jid = (chat_jid == "79010285498516@s.whatsapp.net")
                if is_creator_jid or "script for content" in all_text.lower():
                    prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'master_marketing_prompt.txt')
                    if os.path.exists(prompt_path):
                        with open(prompt_path, 'r', encoding='utf-8') as pf:
                            system_prompt = pf.read()
                    else:
                        system_prompt = "You are a Senior Global Marketing Strategist. Ask the user for destination country, job title, and salary before giving a script."

                # 2.5 Inject Context, Time, and Custom Rules
                current_time = datetime.now().strftime("%Y-%m-%d %I:%M %p")
                
                custom_rule_block = ""
                instr_list = bot_state.get('general_instructions', [])
                if instr_list:
                    rules_str = "\n".join(f"- {r}" for r in instr_list)
                    custom_rule_block = f"\nCRITICAL CUSTOM RULES FROM SUJAL (Follow strictly!):\n{rules_str}\n"

                system_prompt += f"""
{custom_rule_block}
<context>
Current Time & Date: {current_time}
Situational Analysis: Before answering, deeply analyze the chat history. Think about why the user sent this message right now, the time of day, the context of the situation, and how you should best react.
Check the Current Time & Date against any custom rules (e.g., "don't reply until 5 PM"). If a rule restricts replying until a specific time, and that time hasn't passed, you MUST SKIP.
</context>

IMPORTANT OUTPUT FORMAT:
You MUST think and analyze the situation before replying. Wrap your inner thoughts inside <thought> tags.
After thinking, wrap the actual message you want to send inside <reply> tags.

MEMORY SYSTEM — AUTO-LEARN:
If during this conversation you discover a NEW, IMPORTANT fact about anyone (e.g., a birthday, a new job, a preference, a plan, a mood pattern, a relationship detail), you MUST output one or more <remember> tags.
Only remember facts that are genuinely useful for future conversations. Do NOT remember trivial greetings or small talk.
You can output multiple <remember> tags if there are multiple facts.

CRITICAL SKIP LOGIC:
You must critically evaluate if a reply is necessary. DO NOT just reply to reply. 
You MUST output exactly the word SKIP inside the reply tags (i.e. <reply>SKIP</reply>) IF:
1. A Custom Rule dictates that you should not reply.
2. A Custom Rule restricts replying until a specific time, and the Current Time has not reached it.
3. The user sent a generic acknowledgment ("ok", "hmm", 👍) that does not need an answer.
4. The message is clearly directed at someone else in a group, not you.
Do NOT apologize or explain inside the reply tags when skipping.

Example 1 (Normal reply + learning a fact):
<thought>
User said they just got a new job at Google. This is important to remember.
</thought>
<remember>User got a new job at Google (learned on {current_time})</remember>
<reply>congrats bro! google ma? kati ramro</reply>

Example 2 (Normal reply, nothing new to learn):
<thought>
User said "k xa?". Just a casual greeting, nothing new to remember.
</thought>
<reply>thikai xu</reply>

Example 3 (Muted due to rule):
<thought>
Sujal's rule says "never talk about school today". The user is asking about school. I should not reply.
</thought>
<reply>SKIP</reply>

Example 4 (Contextual Smart Skip):
<thought>
The user just sent "ok thanks". No further response is needed to this acknowledgment.
</thought>
<reply>SKIP</reply>
"""

                # 3. Save incoming user message
                agent_memory.save_message(chat_jid, "user", str(final_payload))

                # If this is the content creator, force the best models available (Claude 3.5 Sonnet / GPT-4o)
                override_models = None
                if is_creator_jid or "script for content" in all_text.lower():
                    override_models = [
                        ("openrouter", "anthropic/claude-3.5-sonnet"),
                        ("openrouter", "openai/gpt-4o"),
                        ("groq", "llama-3.3-70b-versatile"),
                        ("openrouter", "google/gemini-2.5-flash"),
                        ("openrouter", "qwen/qwen-2.5-72b-instruct")
                    ]

                raw_reply = get_ai_reply(system_prompt, chat_history, final_payload, has_media=has_media_content, force_model_list=override_models)
                if not raw_reply:
                    continue

                print(f"[AI reply raw] {str(raw_reply)[:150]}...")

                # Parse out thought, reply, and remember tags
                import re
                thought_match = re.search(r'<thought>(.*?)</thought>', raw_reply, re.DOTALL)
                reply_match = re.search(r'<reply>(.*?)</reply>', raw_reply, re.DOTALL)
                remember_matches = re.findall(r'<remember>(.*?)</remember>', raw_reply, re.DOTALL)

                thought = thought_match.group(1).strip() if thought_match else "No thought provided."
                
                if reply_match:
                    reply = reply_match.group(1).strip()
                else:
                    # Fallback if AI forgot tags
                    cleaned = re.sub(r'<thought>.*?</thought>', '', raw_reply, flags=re.DOTALL)
                    cleaned = re.sub(r'<remember>.*?</remember>', '', cleaned, flags=re.DOTALL)
                    reply = cleaned.strip()

                # Apply final WhatsApp cleanup
                reply = clean_whatsapp_formatting(reply)

                # AUTO-MEMORY: Save any <remember> facts to knowledge.txt and DB
                if remember_matches:
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    knowledge_file = os.path.join(base_dir, 'knowledge.txt')
                    
                    for fact in remember_matches:
                        fact = fact.strip()
                        if len(fact) < 5:
                            continue  # Skip garbage
                        
                        # Append to knowledge.txt
                        with open(knowledge_file, 'a', encoding='utf-8') as kf:
                            kf.write(f"\n[Auto-learned | {current_time} | {chat_jid}] {fact}\n")
                        
                        # Insert into agent_memory.db knowledge_chunks table
                        try:
                            import sqlite3
                            conn = sqlite3.connect(agent_memory.DB_PATH)
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO knowledge_chunks (source, content, embedding) VALUES (?, ?, ?)",
                                (f"auto_learned_{chat_jid}", fact, "[]")
                            )
                            conn.commit()
                            conn.close()
                        except Exception as e:
                            print(f"[memory error] Failed to save fact: {e}")
                        
                        print(f"[REMEMBERED] {fact[:80]}")

                # Save everything to the AI conversation log
                log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_conversations.log')
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"=== {current_time} | Chat: {chat_jid} ===\n")
                    f.write(f"User: {str(final_payload)}\n")
                    f.write(f"AI Thought: {thought}\n")
                    if remember_matches:
                        f.write(f"AI Remembered: {'; '.join(r.strip() for r in remember_matches)}\n")
                    f.write(f"AI Reply: {reply}\n\n")

                if should_send(reply, group_type, chat_jid):
                    # 4. Save outgoing assistant reply
                    agent_memory.save_message(chat_jid, "assistant", reply.strip())
                    send_whatsapp_message(chat_jid, reply.strip())
                    print(f"[sent] -> {chat_jid}: {reply.strip()[:60]!r}")
                else:
                    print(f"[skip reply] group={group_type} | reply={reply!r}")

            for jid in to_del:
                del pending[jid]

            time.sleep(0.5)

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[loop error] {e}", flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
