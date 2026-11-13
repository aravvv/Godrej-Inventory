import os
from dotenv import load_dotenv
load_dotenv()
import requests
import base64
import json
import time

api_key = 'os.getenv('GROQ_API_KEY')'
headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}

test_images = [
    ("Upside-down 180 deg", r'C:\Users\aravg\.gemini\antigravity\brain\56a74191-34bd-4e7d-adc5-6ccb33946832\.user_uploaded\media_1794600447804.jpg'),
    ("Vertical 90 deg", r'C:\Users\aravg\.gemini\antigravity\brain\56a74191-34bd-4e7d-adc5-6ccb33946832\.user_uploaded\media_1794600447743.jpg'),
    ("Torn Pink Slip", r'C:\Users\aravg\.gemini\antigravity\brain\56a74191-34bd-4e7d-adc5-6ccb33946832\.user_uploaded\media_1794600433592.jpg'),
    ("Safe Locker Label", r'C:\Users\aravg\.gemini\antigravity\brain\56a74191-34bd-4e7d-adc5-6ccb33946832\.user_uploaded\media_1794600440553.jpg')
]

prompt = """You are an expert warehouse receipt scanner for Godrej products.
The image might be upside-down or sideways. Read it in any orientation.
Extract the Product Code / Item Code (pattern: 8 digits followed by SD followed by 5 digits, e.g. 56101515SD00661).
Also extract the Product name/description.
Respond ONLY with a valid JSON object:
{
  "product_code": "...",
  "product_name": "..."
}"""

for label, img_path in test_images:
    with open(img_path, 'rb') as f:
        b64_data = base64.b64encode(f.read()).decode('utf-8')

    payload = {
        'model': 'qwen/qwen3.8-27b',
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64_data}'}}
            ]
        }],
        'temperature': 0.1,
        'response_format': {'type': 'json_object'}
    }

    start = time.time()
    res = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, json=payload, timeout=30)
    dur = time.time() - start
    if res.status_code == 200:
        ans = res.json()['choices'][0]['message']['content'].strip()
        print(f"[{label}] in {dur:.2f}s -> {ans}")
    else:
        print(f"[{label}] Error {res.status_code}: {res.text}")
