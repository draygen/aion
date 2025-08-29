import os
import json
from bs4 import BeautifulSoup

def parse_html_file(file_path):
    messages = []
    with open(file_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')
        message_blocks = soup.find_all('div', class_='message')

        for block in message_blocks:
            try:
                header = block.find('div', class_='message_header')
                if not header:
                    continue
                sender_tag = header.find('span', class_='user')
                timestamp_tag = header.find('span', class_='meta')
                content_block = block.find_next_sibling('p')

                sender = sender_tag.text.strip() if sender_tag else None
                timestamp = timestamp_tag.text.strip() if timestamp_tag else None
                content = content_block.text.strip() if content_block else None

                if sender and timestamp and content:
                    messages.append({
                        'sender': sender,
                        'timestamp': timestamp,
                        'content': content
                    })
            except Exception as e:
                print(f"[!] Parse error in {file_path}: {e}")
    return messages

def collect_messages_recursively(root_dir):
    all_messages = []
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname.startswith("message_") and fname.endswith(".html"):
                full_path = os.path.join(dirpath, fname)
                parsed = parse_html_file(full_path)
                print(f"[~] Parsed {len(parsed)} messages from {os.path.basename(full_path)}")
                all_messages.extend(parsed)
    return all_messages

if __name__ == "__main__":
    base_path = "/mnt/c/Users/drayg/Downloads/brian_fb_dump/your_facebook_activity/messages/e2ee_cutover"
    output_file = "conversations.jsonl"

    print(f"[+] Recursively parsing: {base_path}")
    all_convos = collect_messages_recursively(base_path)

    print(f"[+] Writing {len(all_convos)} parsed messages to {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        for convo in all_convos:
            f.write(json.dumps(convo, ensure_ascii=False) + "\n")
    print("[✔] Done.")
