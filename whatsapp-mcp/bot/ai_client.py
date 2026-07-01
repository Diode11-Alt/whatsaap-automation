"""
ai_client.py - LLM client wrapper and fallback mechanism.
"""

import os
import time
import requests
from bot.config import MODELS_TEXT, MODELS_VISION, API_KEYS
from bot.bot_probe import has_repetition

# Track last reply time per group to enforce cooldowns
_group_last_reply: dict[str, float] = {}
GROUP_COOLDOWN_SECONDS = 120  # Don't reply more than once every 2 min in groups

def clean_whatsapp_formatting(text: str) -> str:
    """Clean up markdown and raw AI tags so it looks professional on WhatsApp."""
    if not text:
        return ""
    # 1. Force strip any stray <reply> tags just in case
    text = text.replace("<reply>", "").replace("</reply>", "")
    
    # 1.5 Strip blockquotes which models sometimes output
    text = text.replace("<blockquote>", "").replace("</blockquote>", "")
    
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
    
    # 6. Fix common Romanized Nepali phonetic spelling hallucinations from LLM
    text = re.sub(r'\bkhasle\b', 'kasle', text, flags=re.IGNORECASE)
    text = re.sub(r'\bkhaslai\b', 'kaslai', text, flags=re.IGNORECASE)
    text = re.sub(r'\bkhaso\b', 'kaso', text, flags=re.IGNORECASE)
    
    # 7. Clean up excessive punctuation symbol spam (??, .., !!)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'\?{2,}', '?', text)
    text = re.sub(r'!{2,}', '!', text)
    
    return text.strip()

def enforce_clean_language(text: str, group_type: str, is_audio: bool = False) -> str:
    """Enforce zero vulgarity in group chats/audio and prevent confidential data leaks universally."""
    if not text:
        return ""
    import re
    # 1. Universal Confidentiality Scrubber: block any 14+ digit numbers or passport patterns
    if re.search(r'\b\d{14,20}\b', text) or re.search(r'\bBA\d{6,8}\b', text, flags=re.IGNORECASE):
        print(f"[SECURITY BLOCKED] Prevented confidential number/ID leak in reply: {text!r}")
        return "tyo ta private kura ho ta ma sanga xaina dost"
        
    # 2. In groups or audio voice notes, strictly scrub out vulgar/rough slang
    if group_type != "private" or is_audio or "<voice>" in text.lower():
        # Replace common rough Nepali/English slang with friendly clean terms
        text = re.sub(r'\bmu[jg]i\b', 'dost', text, flags=re.IGNORECASE)
        text = re.sub(r'\brandi\b', 'bro', text, flags=re.IGNORECASE)
        text = re.sub(r'\bmachikne\b', 'yaaar', text, flags=re.IGNORECASE)
        text = re.sub(r'\bmadarchod\b', 'bhai', text, flags=re.IGNORECASE)
        text = re.sub(r'\bbitch\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bfuck(?:ing)?\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\bgandu\b', 'dost', text, flags=re.IGNORECASE)
        # Clean up double spaces left by removal
        text = re.sub(r'\s{2,}', ' ', text).strip()
    return text

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
    if '@g.us' in chat_jid and group_type in ('CLASS', 'COMPANY', 'PUBLIC'):
        if chat_jid not in ("120363409545685990@g.us", "120363390805827846@g.us"):
            import random
            now = time.time()
            last = _group_last_reply.get(chat_jid, 0)
            
            # Short, random cooldown between 15s to 40s to feel more natural
            current_cooldown = random.randint(15, 40)
            
            if now - last < current_cooldown:
                print(f"[cooldown] Skipping group reply, last reply was {now - last:.0f}s ago (random cooldown={current_cooldown}s)")
                return False
            _group_last_reply[chat_jid] = now
    
    return True

API_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq":       "https://api.groq.com/openai/v1/chat/completions",
    "deepseek":   "https://api.deepseek.com/v1/chat/completions"
}

def get_ai_reply(system_prompt: str, chat_history: list[dict],
                 new_message_payload, has_media: bool = False, force_model_list: list = None,
                 image_base64_list: list[str] = None) -> str | None:
    """Call AI with automatic model fallback. Routes to vision models when has_media=True."""
    
    models_to_try = force_model_list if force_model_list else (MODELS_VISION if has_media else MODELS_TEXT)

    # Standardize system prompt
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(chat_history)
    
    # Handle multimodal input
    if image_base64_list:
        content_array = [{"type": "text", "text": str(new_message_payload)}]
        for img_b64 in image_base64_list:
            content_array.append({"type": "image_url", "image_url": {"url": img_b64}})
        messages.append({"role": "user", "content": content_array})
    else:
        messages.append({"role": "user", "content": new_message_payload})

    for provider, model in models_to_try:
        keys = API_KEYS.get(provider, [])
        if not keys:
            continue
            
        api_url = API_URLS.get(provider)

        # Gemini via direct REST (not OpenAI compatible)
        if provider == "gemini":
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            for api_key in keys:
                try:
                    gemini_msgs = []
                    for m in messages:
                        if m["role"] == "system":
                            pass
                        elif m["role"] == "user":
                            # Simplistic conversion: ignores images for native gemini API for now, since OpenRouter handles vision better for our setup
                            if isinstance(m["content"], list):
                                text_only = " ".join([c["text"] for c in m["content"] if c["type"] == "text"])
                                gemini_msgs.append({"role": "user", "parts": [{"text": text_only}]})
                            else:
                                gemini_msgs.append({"role": "user", "parts": [{"text": m["content"]}]})
                        else:
                            gemini_msgs.append({"role": "model", "parts": [{"text": m["content"]}]})

                    payload = {
                        "system_instruction": {"parts": [{"text": system_prompt}]},
                        "contents": gemini_msgs
                    }
                    resp = requests.post(
                        f"{api_url}?key={api_key}",
                        json=payload,
                        timeout=25
                    )
                    
                    if resp.status_code in [429, 402, 403, 404, 401]:
                        print(f"[fallback] gemini {api_key[:12]}... hit {resp.status_code}. Next...")
                        continue
                        
                    resp.raise_for_status()
                    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                except Exception as e:
                    print(f"[API Error] gemini {api_key[:12]}...: {str(e)[:80]}")
                    continue
            continue

        # OpenAI compatible providers (OpenRouter, Groq, DeepSeek)
        for api_key in keys:
            try:
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
