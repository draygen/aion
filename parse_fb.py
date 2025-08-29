import os
import json
from bs4 import BeautifulSoup

# Set this to your actual extracted folder
base_path = r"C:\Users\drayg\Downloads\brian_fb_dump\your_facebook_activity\messages\e2ee_cutover"
output_path = os.path.join(base_path, "conversations.jsonl")

def extract_messages_from_file(file_path):
    messages = []
    with open(file_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
        thread_title = soup.title.string.strip() if soup.title else os.path.basename(file_path)

        for msg_div in soup.select("div[class*=message]"):
            sender = msg_div.find("div", class_="from")
            timestamp = msg_div.find("div", class_="meta")
            content = msg_div.find("div", class_="content")

            if sender and timestamp and content:
                messages.append({
                    "thread": thread_title,
                    "sender": sender.get_text(strip=True),
                    "timestamp": timestamp.get_text(strip=True),
                    "content": content.get_text(strip=True)
                })
    return messages

all_messages = []
for file in os.listdir(base_path):
    if file.endswith(".html"):
        file_path = os.path.join(base_path, file)
        print(f"Parsing: {file}")
        all_messages.extend(extract_messages_from_file(file_path))

with open(output_path, 'w', encoding='utf-8') as out:
    for message in all_messages:
        out.write(json.dumps(message, ensure_ascii=False) + '\n')

print(f"✅ Parsed {len(all_messages)} messages.")
print(f"📄 Output written to: {output_path}")
