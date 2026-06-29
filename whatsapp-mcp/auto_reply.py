import sqlite3
import time
import requests
import os
import base64
import subprocess
import speech_recognition as sr
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'whatsapp-bridge', 'store', 'messages.db')
WHATSAPP_API_URL = "http://localhost:8080/api/send"
DOWNLOAD_API_URL = "http://localhost:8080/api/download"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

PROMPT = """You are a proxy representing the user of this WhatsApp account.
CRITICAL INSTRUCTIONS:
1. Do not use generic or scripted responses. Use your intelligence to dynamically analyze the provided chat history.
2. Carefully observe the exact language, dialect, spelling habits (e.g. Romanized Nepali/English mix), slang, abbreviations, and emotional tone used by the 'assistant' (the account owner) in the past messages.
3. Perfectly adopt this dynamic persona. Respond exactly how the account owner would naturally respond based on the established context and tone.
4. Keep replies sensible, highly contextual, and directly address the  message. NEVER sound like an AI. Do not break character."""

def get_new_messages(last_timestamp):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, timestamp, chat_jid, sender, content, is_from_me, media_type
        FROM messages
        WHERE is_from_me = 0 AND timestamp > ?
        ORDER BY timestamp ASC
    """, (last_timestamp,))
    messages = cursor.fetchall()
    conn.close()
    return messages

def get_chat_history(chat_jid, limit=150):
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
    messages = cursor.fetchall()
    conn.close()
    
    history = []
    for msg in messages:
        role = "assistant" if msg['is_from_me'] else "user"
        content = msg['content']
        if msg['media_type'] and (not content or content == ''):
            content = f"[Sent a {msg['media_type']}]"
        elif msg['media_type'] and content:
            content = f"[Sent a {msg['media_type']} with caption]: {content}"
            
        history.append({"role": role, "content": content})
    return history[::-1]

def download_media(message_id, chat_jid):
    data = {"message_id": message_id, "chat_jid": chat_jid}
    try:
        response = requests.post(DOWNLOAD_API_URL, json=data, timeout=10)
        response.raise_for_status()
        res = response.json()
        if res.get('success') and 'path' in res:
            return res['path']
    except Exception as e:
        print(f"Error downloading media {message_id}: {e}")
    return None

def process_media(file_path, media_type):
    if not file_path or not os.path.exists(file_path):
        return None
        
    try:
        if media_type == "image":
            with open(file_path, "rb") as f:
                base64_data = base64.b64encode(f.read()).decode('utf-8')
            return [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_data}"}}]
            
        elif media_type == "video":
            frame_path = file_path + "_frame.jpg"
            subprocess.run(["ffmpeg", "-y", "-i", file_path, "-vframes", "1", "-f", "image2", frame_path], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(frame_path):
                with open(frame_path, "rb") as f:
                    base64_data = base64.b64encode(f.read()).decode('utf-8')
                return [{"type": "text", "text": "[Sent a video. Here is a frame from the video:]"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_data}"}}]
            return [{"type": "text", "text": "[Sent a video but failed to extract frame]"}]
            
        elif media_type == "audio":
            wav_path = file_path + ".wav"
            subprocess.run(["ffmpeg", "-y", "-i", file_path, wav_path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(wav_path):
                recognizer = sr.Recognizer()
                with sr.AudioFile(wav_path) as source:
                    audio_data = recognizer.record(source)
                try:
                    text = recognizer.recognize_google(audio_data)
                    return [{"type": "text", "text": f"[Voice Note Transcription: '{text}']"}]
                except sr.UnknownValueError:
                    return [{"type": "text", "text": "[Voice Note: Inaudible or silent]"}]
                except sr.RequestError:
                    return [{"type": "text", "text": "[Voice Note: Transcription service unavailable]"}]
                    
    except Exception as e:
        print(f"Error processing {media_type}: {e}")
        
    return None

def get_ai_reply(chat_history, new_message_payload=None):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": PROMPT}] + chat_history
    if new_message_payload:
        messages.append({"role": "user", "content": new_message_payload})
        
    models_to_try = [
        "openai/gpt-4o-mini",
        "openrouter/auto",
        "google/gemma-4-31b-it:free"
    ]
    
    for model in models_to_try:
        data = {"model": model, "messages": messages, "max_tokens": 500}
        for attempt in range(2):
            try:
                response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=20)
                if response.status_code in [429, 402]:
                    print(f"Token/Rate limit on {model} (Attempt {attempt+1}/2). Waiting...")
                    time.sleep(2)
                    continue
                response.raise_for_status()
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content']
                else:
                    break
            except Exception as e:
                print(f"Error with model {model}: {e}")
                time.sleep(1)
    return "I am busy right now, I'll text you later!"

def send_whatsapp_message(recipient_jid, content):
    try:
        response = requests.post(WHATSAPP_API_URL, json={"recipient": recipient_jid, "message": content}, timeout=10)
        response.raise_for_status()
        print(f"Sent reply to {recipient_jid}")
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}")

def main():
    print("Starting SUPERIOR Multimodal WhatsApp Auto-Reply Bot...")
    if not os.path.exists(DB_PATH):
        print("Database not found.")
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(timestamp) FROM messages")
    result = cursor.fetchone()[0]
    conn.close()
    
    last_timestamp = result if result else time.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    print(f"Listening for instant new messages (Text, Audio, Video, Photo) after {last_timestamp}...")
    
    while True:
        try:
            new_messages = get_new_messages(last_timestamp)
            for msg in new_messages:
                content = msg['content']
                chat_jid = msg['chat_jid']
                msg_time = msg['timestamp']
                media_type = msg['media_type']
                msg_id = msg['id']
                
                if msg_time > last_timestamp:
                    last_timestamp = msg_time
                    
                if not content and not media_type:
                    continue
                    
                print(f"New message in {chat_jid}: Content='{content}', Media={media_type}")
                
                new_message_payload = []
                
                if media_type:
                    file_path = download_media(msg_id, chat_jid)
                    media_payload = process_media(file_path, media_type)
                    if media_payload:
                        new_message_payload.extend(media_payload)
                        
                if content:
                    new_message_payload.append({"type": "text", "text": content})
                    
                if not new_message_payload:
                    continue
                    
                # For basic text requests, we can just pass the string payload
                if len(new_message_payload) == 1 and new_message_payload[0]["type"] == "text":
                    final_payload = new_message_payload[0]["text"]
                else:
                    final_payload = new_message_payload
                    
                chat_history = get_chat_history(chat_jid, limit=150)
                reply_text = get_ai_reply(chat_history, new_message_payload=final_payload)
                
                if reply_text:
                    print(f"AI Reply: {reply_text}")
                    send_whatsapp_message(chat_jid, reply_text)
                    
            time.sleep(0.5) 
            
        except Exception as e:
            print(f"Error in polling loop: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
