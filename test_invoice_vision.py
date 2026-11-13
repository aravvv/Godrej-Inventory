import os
from dotenv import load_dotenv
load_dotenv()
import fitz  # PyMuPDF
import requests
import base64
import json
import time
from PIL import Image
import io

pdf_path = r'C:\Users\aravg\Downloads\inventory_automation\invoiceSamples\Invoice No.1000-5TI-11303977.pdf'
doc = fitz.open(pdf_path)
page = doc.load_page(0)  # Page 1
pix = page.get_pixmap(dpi=150)
img_bytes = pix.tobytes("jpeg")

# Save as test invoice photo
invoice_img_path = r'C:\Users\aravg\Downloads\inventory_automation\sample_invoice_photo.jpg'
with open(invoice_img_path, 'wb') as f:
    f.write(img_bytes)

print(f"Rendered Page 1 of invoice to JPEG: {len(img_bytes)} bytes")

# Resize for Vision API
img = Image.open(io.BytesIO(img_bytes))
img.thumbnail((1024, 1024))
buf = io.BytesIO()
img.save(buf, format='JPEG', quality=85)
b64_data = base64.b64encode(buf.getvalue()).decode('utf-8')

api_key = 'os.getenv('GROQ_API_KEY')'
headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}

prompt = """You are an expert warehouse invoice reader.
Look at this Godrej Tax Invoice image.
Extract:
1. Sales Invoice No
2. Date
3. Table items: for each row, extract the 15-char Item Code (e.g. 56121403SD00226), Description, and Quantity.
Output strictly as a JSON object:
{
  "invoice_no": "...",
  "date": "...",
  "items": [
    {"item_code": "56121403SD00226", "quantity": 3},
    ...
  ]
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
res = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, json=payload, timeout=45)
dur = time.time() - start

print(f"Status: {res.status_code} in {dur:.2f}s")
if res.status_code == 200:
    data = res.json()
    print("Parsed Invoice JSON:")
    print(data['choices'][0]['message']['content'])
else:
    print("Error:", res.text)
