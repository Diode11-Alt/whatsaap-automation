import requests
import json

key = "AIzaSyAaGbeGN4h7wxsAZ2WwPfdgBPmXy9sW0v8"
url = f"https://generativelanguage.googleapis.com/v1beta/models/embedding-001:embedContent?key={key}"
payload = {
    "model": "models/embedding-001",
    "content": {
        "parts": [{"text": "Hello world"}]
    }
}
resp = requests.post(url, json=payload)
print(resp.status_code)
print(resp.text)
