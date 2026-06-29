import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get("OPENROUTER_API_KEY", "")

models = ["google/gemini-2.0-flash-exp:free", "google/gemini-exp-1206:free"]
for m in models:
    resp = requests.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": m, "messages": [{"role": "user", "content": "hi"}]}
    )
    print(f"{m} -> {resp.status_code} {resp.text[:50]}")
