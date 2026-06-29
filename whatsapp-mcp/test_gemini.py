import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY", "")

resp = requests.post(
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    json={
        "model": "gemini-2.5-flash",
        "messages": [{"role": "user", "content": "hi"}]
    }
)
print(f"Status: {resp.status_code}")
print(resp.text)
