import os
from dotenv import load_dotenv
load_dotenv()
import requests
import base64
import json
import time

api_key = 'os.getenv('GROQ_API_KEY')'
headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}

img_path = r'C:\Users\aravg\.gemini\antigravity\brain\56a74191-34bd-4e7d-adc5-6ccb33946832\.user_uploaded\media_1794600433581.jpg'
with open(img_path, 'rb') as f:
    b64_data = base64.b64encode(f.read()).decode('utf-8')

prompt = """You are an expert warehouse receipt scanner for Godrej products.
Extract the Product Code / Item Code (usually 15 chars, 8 digits followed by SD followed by 5 digits, e.g. 30161803SD00344).
Also extract the Product name/description and Package info.
Respond ONLY with a valid JSON object with keys:
{
  "product_code": "...",
  "product_name": "...",
  "package_info": "..."
}"""

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
duration = time.time() - start

print(f"Status: {res.status_code} in {duration:.2f}s")
if res.status_code == 200:
    print("Groq Result:", res.json()['choices'][0]['message']['content'])
else:
    print("Error:", res.text)
