"""
auto_reply.py - Thin entrypoint for WhatsApp Auto-Reply Bot.
"""

import os
import re
import time
import random
import asyncio
from datetime import datetime
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from bot.config import BURST_WINDOW, GROUP_CONFIG
from bot.prompts import TYPE_TO_PROMPT, STYLE_COMPANY
from bot.contacts import CONTACT_MEMORY, get_contact_prompt
from bot.classify import classify_group
from bot.routines import process_auto_routines
from bot.history import get_chat_history, get_chat_meta
from bot.bridge_client import send_whatsapp_message, download_media, send_presence
from bot.media import process_media
from bot.ai_client import get_ai_reply, should_send, clean_whatsapp_formatting
from bot.state import load_bot_state, save_bot_state, parse_command
from bot.knowledge import load_knowledge
from bot.memory.retrieval import get_context_for_reply, embed_and_store
from bot.memory.facts_store import get_learned_context, extract_and_store_facts, store_direct_fact
from bot.vision import encode_image

# Global State
bot_state = load_bot_state()
bot_active = bot_state.get('active', True)
replied_ids = set()
group_type_cache = {}
pending = {}  # { chat_jid: { msgs: [...], fire_at: float, system_prompt: str, group_type: str } }

all_data_jid = ""
for ck, profile in CONTACT_MEMORY.items():
    if ck == 'all_data':
        all_data_jid = profile.get('jid', '')

def inject_instructions(prompt: str, instructions: list) -> str:
    if not instructions:
        return prompt
    return prompt + "\n\nCRITICAL RULES FOR YOU:\n" + "\n".join(f"- {inst}" for inst in instructions)

async def pending_messages_loop():
    global bot_state, bot_active, pending, group_type_cache, replied_ids, all_data_jid
    while True:
        try:
            if bot_active:
                process_auto_routines()

            now = time.time()
            to_del = []
            for chat_jid, data in list(pending.items()):
                if now >= data['fire_at']:
                    group_type = data['group_type']
                    system_prompt = data['system_prompt']
                    
                    # Deduplicate before joining
                    unique_msgs = []
                    seen = set()
                    for m in data['msgs']:
                        fingerprint = f"{m['content']}|{m['media_type']}"
                        if fingerprint not in seen:
                            seen.add(fingerprint)
                            unique_msgs.append(m)
                    
                    if group_type == "PERSONAL":
                        combined_text = "\n".join(m['content'] for m in unique_msgs if m['content'])
                    else:
                        combined_text = "\n".join(f"[{m['sender'].split('@')[0]}]: {m['content']}" for m in unique_msgs if m['content'])
                    has_media = any(m['media_type'] for m in unique_msgs)
                    media_notes = "\n".join(f"[Sent {m['media_type']}: {m['filename']}]" for m in unique_msgs if m['media_type'])
                    
                    final_payload = combined_text
                    if media_notes:
                        final_payload += f"\n{media_notes}"
                    
                    print(f"\n--- 🚀 FIRING REPLY TO {chat_jid} ---")
                    print(f"Messages:\n{final_payload}")
                    
                    if not final_payload.strip():
                        to_del.append(chat_jid)
                        continue

                    # 1. RAG - Context retrieval
                    rag_context = get_context_for_reply(chat_jid, final_payload)
                    learned_context = get_learned_context(chat_jid, final_payload)
                    static_knowledge = load_knowledge()

                    if static_knowledge:
                        system_prompt += f"\n\n<knowledge_base>\n{static_knowledge}\n</knowledge_base>"
                    if rag_context:
                        system_prompt += rag_context
                    if learned_context:
                        system_prompt += learned_context

                    system_prompt += (
                        "\n\n<CURRENT_REALITY_OVERRIDE>\n"
                        "CRITICAL FACTS ABOUT SUJAL (ALWAYS OBEY THESE OVER ANY OLD MEMORY):\n"
                        "1. LOCATION: Sujal is CURRENTLY LIVING IN KATHMANDU, NEPAL. He returned from Dubai after his college visa issue. He is studying at IIMS College Kathmandu. NEVER say you are in Dubai.\n"
                        "2. FORMATTING: NEVER prefix your reply with names, phone numbers, or brackets like [Sujal]: or [239783913721864]:. Output ONLY the raw conversational message.\n"
                        "3. UNKNOWN QUESTIONS: If someone asks a question you don't know the answer to (e.g. about someone's status or news), do NOT hallucinate or make up random stories! Ask them casually or give a neutral Sujal-style response (e.g. 'khai thaha vayena dost', 'k vanya bujhena').\n"
                        "</CURRENT_REALITY_OVERRIDE>"
                    )

                    if '@g.us' in chat_jid and chat_jid != all_data_jid:
                        system_prompt += (
                            "\n\n<GROUP_SILENCE_MANDATE>\n"
                            "CRITICAL MANDATE FROM SUJAL FOR ALL GROUP CHATS:\n"
                            "1. STRICT SILENCE: DO NOT reply unnecessarily! You MUST output exactly `SKIP` until and unless someone is explicitly calling, naming, or tagging Sujal (e.g., mentioning 'Sujal', 'Diode', 'Mainali', or asking him directly by name).\n"
                            "2. NO GENERAL REPLIES: If someone sends a general file, instructions, or speaks to others (e.g., 'yo pdf check garidinu sir', 'design ko kam', 'good morning'), DO NOT jump in! You MUST output exactly: SKIP\n"
                            "3. ZERO TOLERANCE FOR EMBARRASSING REPLIES: Sujal gets embarrassed and has to delete ('unsent') unnecessary AI replies. When in doubt, remain silent by outputting exactly: SKIP\n"
                            "</GROUP_SILENCE_MANDATE>"
                        )

                    # 2. Get AI Reply
                    chat_history = get_chat_history(chat_jid, limit=15)
                    
                    image_base64_list = []
                    for m in unique_msgs:
                        if m.get('local_image_path'):
                            b64 = encode_image(m['local_image_path'])
                            if b64:
                                image_base64_list.append(b64)
                                
                    raw_reply = get_ai_reply(system_prompt, chat_history, final_payload, has_media=has_media, image_base64_list=image_base64_list)
                    current_time = time.strftime("%Y-%m-%d %H:%M:%S")

                    if raw_reply is None:
                        to_del.append(chat_jid)
                        continue

                    # 3. Parse output tags
                    thought_match = re.search(r'<thought>(.*?)</thought>', raw_reply, re.DOTALL)
                    reply_match = re.search(r'<reply>(.*?)</reply>', raw_reply, re.DOTALL)

                    thought = thought_match.group(1).strip() if thought_match else "No thought provided."
                    
                    if reply_match:
                        reply = reply_match.group(1).strip()
                    else:
                        cleaned = re.sub(r'<thought>.*?</thought>', '', raw_reply, flags=re.DOTALL)
                        cleaned = re.sub(r'<remember>.*?</remember>', '', cleaned, flags=re.DOTALL)
                        cleaned = re.sub(r'<remember_global>.*?</remember_global>', '', cleaned, flags=re.DOTALL)
                        reply = cleaned.strip()

                    reply = clean_whatsapp_formatting(reply)

                    # 4. Long-term memory extraction
                    extract_and_store_facts(chat_jid, raw_reply)

                    # Save to AI conversation log
                    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_conversations.log')
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"=== {current_time} | Chat: {chat_jid} ===\n")
                        f.write(f"User: {str(final_payload)}\n")
                        f.write(f"AI Thought: {thought}\n")
                        f.write(f"AI Reply: {reply}\n\n")

                    # 5. Send message with Typing/Recording Simulation
                    if should_send(reply, group_type, chat_jid):
                        reply = reply.strip()
                        
                        # Check for Voice Note tag
                        voice_match = re.search(r'<voice>(.*?)</voice>', reply, re.DOTALL | re.IGNORECASE)
                        
                        if voice_match:
                            voice_text = voice_match.group(1).strip()
                            print(f"[recording...] {chat_jid}")
                            send_presence(chat_jid, "recording")
                            
                            from bot.tts_client import generate_voice_note
                            audio_path = generate_voice_note(voice_text)
                            
                            if audio_path:
                                send_whatsapp_message(chat_jid, "", media_path=audio_path)
                                print(f"[sent voice note] -> {chat_jid}: {voice_text[:60]!r}")
                            else:
                                # Fallback to text if audio generation fails
                                send_whatsapp_message(chat_jid, voice_text)
                                print(f"[sent voice fallback] -> {chat_jid}: {voice_text[:60]!r}")
                                
                            send_presence(chat_jid, "paused")
                        else:
                            # Standard Text Message — dynamic human pacing (~0.07s per char + slight jitter)
                            typing_delay = max(1.5, min(len(reply) / 14.0, 8.0)) + random.uniform(-0.2, 0.4)
                            
                            print(f"[typing...] {chat_jid} for {typing_delay:.1f}s")
                            send_presence(chat_jid, "typing")
                            await asyncio.sleep(max(1.0, typing_delay))
                            
                            send_whatsapp_message(chat_jid, reply)
                            send_presence(chat_jid, "paused")
                            
                            print(f"[sent] -> {chat_jid}: {reply[:60]!r}")
                    else:
                        print(f"[skip reply] group={group_type} | reply={reply!r}")

                    to_del.append(chat_jid)

            for jid in to_del:
                del pending[jid]

            await asyncio.sleep(0.5)

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[loop error] {e}", flush=True)
            await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(pending_messages_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

# Mount static files and dashboard API
from bot.dashboard import router as dashboard_router
app.include_router(dashboard_router)
import os
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/dashboard", StaticFiles(directory=static_dir, html=True), name="static")

@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard/")

@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    global bot_state, bot_active, all_data_jid
    msg = await request.json()
    
    chat_jid   = msg.get('chat_jid')
    content    = msg.get('content') or ""
    media_type = msg.get('media_type', '')
    is_from_me = msg.get('is_from_me', False)
    msg_id     = msg.get('id')
    sender     = msg.get('sender', '')
    filename   = msg.get('filename', '')

    # Background task to embed text messages immediately for Vector Search
    if content and not media_type:
        background_tasks.add_task(embed_and_store, chat_jid, msg_id, content)

    # ── Parse commands from Sujal's own messages in "All data" or his Alt DMs ──
    is_sujal = (sender and any(sender.startswith(sid) for sid in ["166747927797942", "181101876240397"]))
    is_alt_dm = chat_jid.startswith("166747927797942") or chat_jid.startswith("181101876240397")
    
    if is_sujal and (chat_jid == all_data_jid or is_alt_dm) and content.strip():
        if content.startswith("🤖") or content.startswith("Huss boss") or content.startswith("Bot ") or content.startswith("Muted") or content.startswith("Unmuted"):
            return {"status": "ignored"}
            
        new_state, cmd_response = parse_command(content, bot_state, CONTACT_MEMORY)
        
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_conversations.log')
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if cmd_response:
            bot_state = new_state
            bot_active = bot_state['active']
            save_bot_state(bot_state)
            print(f"[COMMAND] {content!r} → {cmd_response}")
            
            final_reply = ""
            if cmd_response.startswith("AI_CONFIRM_RULE:"):
                rule_text = cmd_response.replace("AI_CONFIRM_RULE:", "").strip()
                prompt = f"You are Sujal's AI assistant. He just added a new rule for you: '{rule_text}'. Acknowledge this rule in a short, obedient, slightly casual way (Romanized Nepali or English). Just 1 sentence. Start with 'Huss boss' or similar."
                conf_reply = get_ai_reply(prompt, [], "Acknowledge the rule.", has_media=False)
                if conf_reply:
                    clean_conf = re.sub(r'<thought>.*?</thought>', '', conf_reply, flags=re.DOTALL)
                    clean_conf = re.sub(r'<reply>(.*?)</reply>', r' ', clean_conf, flags=re.DOTALL).strip()
                    final_reply = f"🤖 {clean_conf}"
                else:
                    final_reply = f"🤖 Huss boss, noted the rule: {rule_text}"
            else:
                final_reply = f"🤖 {cmd_response}"
                
            send_whatsapp_message(chat_jid, final_reply)
            
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"=== {current_time} | Chat: {chat_jid} (Command) ===\n")
                f.write(f"User: {content}\n")
                f.write(f"AI Reply: {final_reply}\n\n")
            return {"status": "ok"}
        elif chat_jid == all_data_jid:
            txt_lower = content.strip().lower()
            query_starters = ('what ', 'who ', 'where ', 'when ', 'why ', 'how ', 'did ', 'is ', 'are ', 'can ', 'could ', 'would ', 'tell ', 'show ', 'list ', 'check ', 'summarize ', 'summary ', 'explain ', 'give me ', 'anyone ', 'has ', 'do we ', 'have ', 'any ')
            is_query = content.strip().endswith('?') or any(txt_lower.startswith(q) for q in query_starters) or 'status' in txt_lower
            
            if is_query:
                print(f"[Chief of Staff] Query detected in all_data: {content!r}")
                from bot.state import generate_executive_briefing
                from bot.memory.retrieval import get_context_for_reply
                from bot.memory.facts_store import get_learned_context
                
                rag_context = get_context_for_reply("GLOBAL", content)
                learned_context = get_learned_context("GLOBAL", content)
                briefing = generate_executive_briefing(bot_state, CONTACT_MEMORY)
                
                cos_prompt = (
                    "You are acting as Sujal's Personal AI Chief of Staff and Executive Assistant inside his private WhatsApp Command Center ('All data').\n"
                    "Sujal (your boss) is asking you a question or requesting information about his system, contacts, or learned memories.\n"
                    "Use the retrieved RAG memory context, learned facts, and system briefing below to answer him accurately, concisely, and obediently.\n"
                    "Start your response with '🤖 ' or 'Huss boss, '.\n\n"
                    f"<system_briefing>\n{briefing}\n</system_briefing>\n"
                )
                if rag_context: cos_prompt += f"\n{rag_context}\n"
                if learned_context: cos_prompt += f"\n{learned_context}\n"
                
                cos_reply = get_ai_reply(cos_prompt, [], content, has_media=False)
                if cos_reply:
                    clean_reply = re.sub(r'<thought>.*?</thought>', '', cos_reply, flags=re.DOTALL)
                    clean_reply = re.sub(r'<reply>(.*?)</reply>', r'\1', clean_reply, flags=re.DOTALL).strip()
                    if not clean_reply.startswith("🤖") and not clean_reply.lower().startswith("huss"):
                        clean_reply = f"🤖 {clean_reply}"
                else:
                    clean_reply = "🤖 I searched your database but couldn't generate a reply right now, boss."
                    
                send_whatsapp_message(chat_jid, clean_reply)
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"=== {current_time} | Chat: {chat_jid} (Chief of Staff Q&A) ===\n")
                    f.write(f"User: {content}\n")
                    f.write(f"AI Reply: {clean_reply}\n\n")
                return {"status": "ok"}
            else:
                # If it's not a query, store it directly into long-term memory facts
                store_direct_fact("GLOBAL", content.strip())
                store_direct_fact(all_data_jid, content.strip())
                send_whatsapp_message(chat_jid, f"🤖 Memo saved to long-term memory: '{content.strip()}'")
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(f"=== {current_time} | Chat: {chat_jid} (Memo) ===\n")
                    f.write(f"User: {content}\n")
                    f.write(f"AI Reply: 🤖 Memo saved to long-term memory: '{content.strip()}'\n\n")
                return {"status": "ok"}
        # If it's an alt DM and not a command, we intentionally fall through to let the AI chat naturally
        
    if is_from_me:
        replied_ids.add(msg_id)
        return {"status": "ignored"}

    if not bot_active:
        return {"status": "paused"}

    # ── Intercept "ignore" command from user in any chat ──
    if content and content.strip().lower() == "ignore":
        if chat_jid not in bot_state.get('muted_jids', []):
            if 'muted_jids' not in bot_state:
                bot_state['muted_jids'] = []
            bot_state['muted_jids'].append(chat_jid)
            save_bot_state(bot_state)
            send_whatsapp_message(chat_jid, "🤖 Muted this chat. I will not reply here anymore unless unmuted from all_data.")
        replied_ids.add(msg_id)
        return {"status": "ignored"}

    # ── Check whitelist / muting ──
    whitelist_jids = bot_state.get('reply_only_jids', [])
    if whitelist_jids and chat_jid not in whitelist_jids and chat_jid != all_data_jid:
        replied_ids.add(msg_id)
        return {"status": "ignored"}

    muted_jids = bot_state.get('muted_jids', [])
    if chat_jid in muted_jids:
        # Check if temporal mute has expired
        muted_until = bot_state.get('muted_until', {})
        if chat_jid in muted_until and time.time() > muted_until[chat_jid]:
            print(f"[unmute] Temporal mute for {chat_jid} expired. Unmuting automatically.")
            bot_state['muted_jids'].remove(chat_jid)
            del bot_state['muted_until'][chat_jid]
            save_bot_state(bot_state)
        else:
            replied_ids.add(msg_id)
            return {"status": "ignored"}
        
    if msg_id in replied_ids:
        return {"status": "ignored"}

    if not content and not media_type:
        replied_ids.add(msg_id)
        return {"status": "ignored"}

    # ── Classify group ──────────────────────────────────────────
    if chat_jid not in group_type_cache:
        meta = get_chat_meta(chat_jid)
        gtype = classify_group(chat_jid, meta['name'], meta['recent_texts'])
        group_type_cache[chat_jid] = {"type": gtype, "name": meta['name']}

    group_info = group_type_cache[chat_jid]
    group_type = group_info["type"]
    chat_name = group_info["name"] or chat_jid.split('@')[0]

    # ── All-Group Mute check ────────────────────────────────
    if bot_state.get('mute_all_groups', False) and '@g.us' in chat_jid:
        replied_ids.add(msg_id)
        return {"status": "ignored"}

    # ── Check for contact-specific memory first ─────────────
    contact_prompt = get_contact_prompt(chat_name, chat_jid)
    if contact_prompt:
        raw_prompt = contact_prompt
    else:
        raw_prompt = TYPE_TO_PROMPT.get(group_type, STYLE_COMPANY)

    if raw_prompt is None:
        replied_ids.add(msg_id)
        return {"status": "ignored"}

    system_prompt = inject_instructions(raw_prompt, bot_state.get('general_instructions', []))
    system_prompt = system_prompt.format(chat_name=chat_name)

    replied_ids.add(msg_id)

    # Convert voice notes if necessary
    if media_type == 'audio':
        print(f"[audio] Downloading voice note {msg_id} for transcription...")
        local_path = download_media(msg_id, chat_jid)
        if local_path:
            media_blocks = process_media(local_path, 'audio')
            if media_blocks and len(media_blocks) > 0 and 'text' in media_blocks[0]:
                content = media_blocks[0]['text']
                print(f"[transcribed] {content}")
            else:
                content = "[User sent a voice note but transcription failed]"
        else:
            content = "[User sent a voice note but download failed]"
    
    local_image_path = None
    if media_type == 'video':
        content = "[User sent a video]"
    elif media_type == 'image':
        print(f"[image] Downloading image {msg_id} for vision processing...")
        local_path = download_media(msg_id, chat_jid)
        caption = content.strip() if content else ""
        if local_path:
            local_image_path = local_path
            content = f"[User sent an image: {caption}. Process it using the provided vision input]" if caption else "[User sent an image. Process it using the provided vision input]"
            # Multi-modal RAG indexing in background
            from bot.media import index_image_memory
            background_tasks.add_task(index_image_memory, chat_jid, msg_id, local_path, caption)
        else:
            content = f"[User sent an image: {caption}, but it failed to download]" if caption else "[User sent an image, but it failed to download]"
    elif media_type == 'document':
        caption = content.strip() if content else ""
        content = f"[User sent a document ({filename}): {caption}]" if caption else f"[User sent a document: {filename}]"

    # Background task to embed processed media messages (transcribed audio, document text) for Vector Search
    if content and media_type and media_type != 'image': # Images are indexed by index_image_memory
        background_tasks.add_task(embed_and_store, chat_jid, msg_id, content)

    # Add to buffer (pending dictionary)
    if chat_jid not in pending:
        wait_time = BURST_WINDOW * 2 if '@g.us' in chat_jid else BURST_WINDOW
        
        if chat_jid == all_data_jid:
            wait_time = 1
            
        pending[chat_jid] = {
            'msgs': [],
            'fire_at': time.time() + wait_time,
            'system_prompt': system_prompt,
            'group_type': group_type
        }
    
    pending[chat_jid]['msgs'].append({
        'sender': sender,
        'content': content,
        'media_type': media_type,
        'filename': filename,
        'local_image_path': local_image_path
    })
    
    print(f"[buffer] Added msg from {sender} in {chat_jid}. Firing in {pending[chat_jid]['fire_at'] - time.time():.1f}s")
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("auto_reply:app", host="0.0.0.0", port=port)
