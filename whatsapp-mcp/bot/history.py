"""
history.py - Chat history retrieval from SQLite.
"""

import sqlite3
from bot.config import DB_PATH

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
