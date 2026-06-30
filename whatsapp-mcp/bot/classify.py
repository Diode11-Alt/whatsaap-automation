"""
classify.py - Auto-classifies chat groups based on keywords and JIDs.
"""

from bot.config import GROUP_CONFIG

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
