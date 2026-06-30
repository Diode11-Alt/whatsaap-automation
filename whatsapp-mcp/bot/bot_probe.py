"""
bot_probe.py - Logic to detect and deflect if someone asks if Sujal is an AI/Bot.
"""
import re
from collections import defaultdict

BOT_DETECT_PATTERNS = [
    r"\bbot\b", r"\bai\b", r"\bartificial\b", r"\bautomat",
    r"are you real", r"are you human", r"who (is|are) (this|you)",
    r"machine", r"robot", r"gpt", r"chatgpt", r"claude"
]

BOT_DEFLECT_RESPONSES = [
    "haha k bot? ma nai xu bro 😂",
    "oi real nai xu ma, k vako?",
    "bot hoina yaar, busy thye tesaile late vako",
    "hahah bot vanxas? ma nai xa sujal",
    "k bhaneko bot? ma real manche xu 😅",
]

def is_bot_probe(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in BOT_DETECT_PATTERNS)

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
