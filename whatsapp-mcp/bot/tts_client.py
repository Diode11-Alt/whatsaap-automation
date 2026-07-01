"""
tts_client.py - Generates Text-to-Speech (Voice Notes) using multi-engine failover:
1. edge-tts (Microsoft Edge Neural Voice - 100% Free, life-like Nepali male voice ne-NP-SagarNeural)
2. gTTS (Google Text-to-Speech - 100% Free backup)
3. OpenRouter API (Fallback if paid keys are available)
Always converts to WhatsApp-compatible Opus .ogg format using FFmpeg.
"""
import os
import requests
import uuid
import asyncio
import subprocess

def convert_to_opus_ogg(input_path: str, output_path: str) -> bool:
    """Convert any audio file to WhatsApp voice note compatible Opus OGG format."""
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:a", "libopus", "-b:a", "32k", "-ar", "24000",
            "-application", "voip", "-vbr", "on", output_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[tts] FFmpeg opus conversion failed: {e}")
        return False

def generate_voice_note(text: str, model_name: str = "google/gemini-3.1-flash-tts-preview") -> str | None:
    """
    Generates an OGG voice note from text using a multi-engine failover pipeline.
    Returns the file path to the saved .ogg file, or None if failed.
    """
    if not text or not text.strip():
        return None
    text = text.strip()
    
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tmp')
    os.makedirs(output_dir, exist_ok=True)
    
    unique_id = uuid.uuid4().hex[:8]
    mp3_path = os.path.join(output_dir, f"tmp_vn_{unique_id}.mp3")
    ogg_path = os.path.join(output_dir, f"vn_{unique_id}.ogg")
    
    # --- ENGINE 1: Edge-TTS (Free Microsoft Edge Neural Voice) ---
    try:
        print(f"[tts] Trying Engine 1 (edge-tts ne-NP-SagarNeural) for: {text[:40]}...")
        import edge_tts
        import threading
        
        def run_edge_sync(target_text, target_path):
            def target():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    communicate = edge_tts.Communicate(target_text, "ne-NP-SagarNeural")
                    loop.run_until_complete(communicate.save(target_path))
                finally:
                    loop.close()
            t = threading.Thread(target=target)
            t.start()
            t.join()
            
        run_edge_sync(text, mp3_path)
            
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
            if convert_to_opus_ogg(mp3_path, ogg_path):
                if os.path.exists(mp3_path):
                    try: os.remove(mp3_path)
                    except: pass
                print(f"[tts] Successfully generated voice note via edge-tts: {ogg_path}")
                return ogg_path
    except Exception as e:
        print(f"[tts] Engine 1 (edge-tts) failed: {e}")
        if os.path.exists(mp3_path):
            try: os.remove(mp3_path)
            except: pass

    # --- ENGINE 2: gTTS (Free Google Text-to-Speech) ---
    try:
        print(f"[tts] Trying Engine 2 (gTTS) for: {text[:40]}...")
        from gtts import gTTS
        # Detect simple English vs Nepali or use 'ne' / 'en'
        lang = 'ne' if any('\u0900' <= c <= '\u097F' for c in text) else 'en'
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(mp3_path)
        
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
            if convert_to_opus_ogg(mp3_path, ogg_path):
                if os.path.exists(mp3_path):
                    try: os.remove(mp3_path)
                    except: pass
                print(f"[tts] Successfully generated voice note via gTTS: {ogg_path}")
                return ogg_path
    except Exception as e:
        print(f"[tts] Engine 2 (gTTS) failed: {e}")
        if os.path.exists(mp3_path):
            try: os.remove(mp3_path)
            except: pass

    # --- ENGINE 3: OpenRouter Fallback ---
    print(f"[tts] Trying Engine 3 (OpenRouter API) for: {text[:40]}...")
    from bot.config import API_KEYS
    openrouter_keys = API_KEYS.get("openrouter", [])
    
    for api_key in openrouter_keys:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": f"Read the following text out loud: {text}"}],
                "modalities": ["audio", "text"],
                "audio": {"voice": "alloy", "format": "wav"}
            }
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            if response.status_code == 200:
                data = response.json()
                message = data["choices"][0]["message"]
                if "audio" in message and "data" in message["audio"]:
                    import base64
                    wav_path = os.path.join(output_dir, f"tmp_vn_{unique_id}.wav")
                    with open(wav_path, "wb") as f:
                        f.write(base64.b64decode(message["audio"]["data"]))
                    
                    if convert_to_opus_ogg(wav_path, ogg_path):
                        if os.path.exists(wav_path):
                            try: os.remove(wav_path)
                            except: pass
                        print(f"[tts] Successfully generated voice note via OpenRouter: {ogg_path}")
                        return ogg_path
        except Exception as e:
            print(f"[tts] OpenRouter key {api_key[:8]} failed: {e}")

    print("[tts] Failed to generate voice note across all engines.")
    return None
