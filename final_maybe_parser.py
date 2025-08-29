from bs4 import BeautifulSoup
import json
from pathlib import Path

def parse_e2ee_html(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    messages = []
    for msg in soup.select('div._a709'):
        sender = msg.select_one('._a70e')
        text = msg.select_one('._aoa9')
        timestamp = msg.select_one('._a70f')
        
        messages.append({
            'sender': sender.get_text(strip=True) if sender else '',
            'text': text.get_text(strip=True) if text else '',
            'timestamp': timestamp.get_text(strip=True) if timestamp else ''
        })

    return messages

# Example usage:
parsed = parse_e2ee_html("message_1.html")
with open("parsed_output.json", "w", encoding="utf-8") as f:
    for entry in parsed:
        f.write(json.dumps(entry) + '\n')

