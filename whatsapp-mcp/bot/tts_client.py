"""
tts_client.py - Generates Text-to-Speech (Voice Notes) using OpenRouter.
"""
import os
import requests
import uuid

def generate_voice_note(text: str, model_name: str = "google/gemini-3.1-flash-tts-preview") -> str | None:
    """
    Generates an OGG voice note from text using OpenRouter API.
    Returns the file path to the saved .ogg file, or None if failed.
    """
    if not text.strip():
        return None
        
    from bot.config import API_KEYS
    openrouter_keys = API_KEYS.get("openrouter", [])
    if not openrouter_keys:
        print("[tts] No OPENROUTER_API_KEY found.")
        return None
        
    print(f"[tts] Generating voice note for: {text[:30]}... across {len(openrouter_keys)} keys")
    
    for api_key in openrouter_keys:
        # 1. First try the OpenAI compatible audio/speech endpoint
        try:
            url = "https://openrouter.ai/api/v1/audio/speech"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model_name,
                "input": text,
                "voice": "alloy",
                "response_format": "opus"
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if response.status_code == 200:
                output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tmp')
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir, f"vn_{uuid.uuid4().hex[:8]}.ogg")
                
                with open(output_path, "wb") as f:
                    f.write(response.content)
                print(f"[tts] Generated voice note: {output_path}")
                return output_path
            else:
                print(f"[tts] audio/speech HTTP {response.status_code} with key {api_key[:8]}...")
        except Exception as e:
            print(f"[tts] audio/speech error: {e}")
            
        # 2. If audio/speech fails, try chat/completions with audio modality
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
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                message = data["choices"][0]["message"]
                if "audio" in message and "data" in message["audio"]:
                    import base64
                    import subprocess
                    
                    audio_b64 = message["audio"]["data"]
                    wav_data = base64.b64decode(audio_b64)
                    
                    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tmp')
                    os.makedirs(output_dir, exist_ok=True)
                    wav_path = os.path.join(output_dir, f"tmp_{uuid.uuid4().hex[:8]}.wav")
                    ogg_path = os.path.join(output_dir, f"vn_{uuid.uuid4().hex[:8]}.ogg")
                    
                    with open(wav_path, "wb") as f:
                        f.write(wav_data)
                        
                    subprocess.run(["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "32k", ogg_path], 
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    if os.path.exists(wav_path):
                        os.remove(wav_path)
                        
                    if os.path.exists(ogg_path):
                        print(f"[tts] Generated voice note via chat completions: {ogg_path}")
                        return ogg_path
            else:
                print(f"[tts] chat/completions HTTP {response.status_code} with key {api_key[:8]}...")
        except Exception as e:
            print(f"[tts] chat/completions error: {e}")

    print("[tts] Failed to generate voice note via all keys and endpoints.")
    return None
