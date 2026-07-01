"""
media.py - Media processing and transcription.
"""

import os
import base64
import subprocess
import requests
import speech_recognition as sr
from pydub import AudioSegment

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
            
            if not os.path.exists(wav):
                return [{"type": "text", "text": "[Voice note: failed to convert audio]"}]
                
            try:
                # Use pydub to slice audio if it's too large (>20MB) or just slice it into 5-minute chunks
                audio = AudioSegment.from_wav(wav)
                chunk_length_ms = 5 * 60 * 1000  # 5 minutes
                chunks = [audio[i:i+chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]
                
                full_transcription = []
                groq_key = os.environ.get("GROQ_API_KEY", "")
                
                for idx, chunk in enumerate(chunks):
                    chunk_wav = f"{file_path}_chunk{idx}.wav"
                    chunk.export(chunk_wav, format="wav")
                    
                    text_chunk = ""
                    if groq_key:
                        try:
                            with open(chunk_wav, 'rb') as audio_file:
                                resp = requests.post(
                                    'https://api.groq.com/openai/v1/audio/transcriptions',
                                    headers={'Authorization': f'Bearer {groq_key}'},
                                    files={'file': (os.path.basename(chunk_wav), audio_file, 'audio/wav')},
                                    data={'model': 'whisper-large-v3', 'response_format': 'text'},
                                    timeout=60
                                )
                            if resp.status_code == 200:
                                text_chunk = resp.text.strip()
                            else:
                                print(f"[whisper error] HTTP {resp.status_code}: {resp.text}")
                        except Exception as e:
                            print(f"[whisper chunk error] {e}")
                    
                    # Fallback to Google if Groq failed or not configured
                    if not text_chunk:
                        try:
                            rec = sr.Recognizer()
                            with sr.AudioFile(chunk_wav) as src:
                                audio_data = rec.record(src)
                            try:
                                text_chunk = rec.recognize_google(audio_data, language='en-US')
                            except sr.UnknownValueError:
                                text_chunk = rec.recognize_google(audio_data, language='ne-NP')
                        except Exception as e:
                            print(f"[google sr chunk error] {e}")
                    
                    if text_chunk:
                        full_transcription.append(text_chunk)
                    
                    # Clean up chunk
                    if os.path.exists(chunk_wav):
                        os.remove(chunk_wav)
                
                final_text = " ".join(full_transcription).strip()
                if final_text:
                    print(f"[transcribed] Length: {len(final_text)} chars")
                    return [{"type": "text", "text": f'[Voice note says: "{final_text}"]'}]
                else:
                    return [{"type": "text", "text": "[Voice note: couldn't transcribe audio]"}]
                    
            except Exception as e:
                import traceback
                traceback.print_exc()
                return [{"type": "text", "text": f"[Voice note: chunking failed: {e}]"}]
    except Exception as e:
        print(f"[media process error] {e}")
    return None

def index_image_memory(chat_jid: str, msg_id: str, image_path: str, caption: str = ""):
    """Multi-Modal Memory Indexing: Analyzes image with vision AI and stores description in RAG vector db."""
    from bot.vision import encode_image
    from bot.ai_client import get_ai_reply
    from bot.memory.retrieval import embed_and_store
    
    b64 = encode_image(image_path)
    if not b64:
        return
        
    prompt = "You are an AI memory indexer. Describe what is visible in this image in 1-2 concise sentences for vector search indexing (e.g. 'Screenshot showing a Python syntax error', 'Photo of Sujal eating dinner at a restaurant', etc.)."
    desc = get_ai_reply(prompt, [], f"Caption provided by user: {caption}" if caption else "No caption provided", has_media=True, image_base64_list=[b64])
    
    if desc:
        import re
        desc = re.sub(r'<thought>.*?</thought>', '', desc, flags=re.DOTALL).strip()
        memory_text = f"[Vision Memory - Image]: {caption} - {desc}" if caption else f"[Vision Memory - Image]: {desc}"
        embed_and_store(chat_jid, f"{msg_id}_vision", memory_text)
        print(f"[multi-modal RAG] Indexed image memory for {chat_jid}: {memory_text[:80]}...")
