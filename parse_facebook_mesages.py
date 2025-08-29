import os
import json
from bs4 import BeautifulSoup
from tqdm import tqdm

def parse_html_file(file_path):
    messages = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            for msg_block in soup.find_all('div', class_='message'):
                try:
                    sender = msg_block.find('span', class_='user')
                    timestamp = msg_block.find('span', class_='meta')
                    content = msg_block.find('p')

                    if sender and timestamp and content:
                        messages.append({
                            'sender': sender.text.strip(),
                            'timestamp': timestamp.text.strip(),
                            'content': content.text.strip()
                        })
                except Exception as inner_e:
                    print(f"[!] Error parsing a message in {file_path}: {inner_e}")
    except Exception as e:
        print(f"[!] Error reading file {file_path}: {e}")
    print(f"[~] Parsed {len(messages)} messages from {os.path.basename(file_path)}")
    return messages

def collect_all_messages(root_dir):
    all = []
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname.startswith("message_") and fname.endswith(".html"):
                path = os.path.join(dirpath, fname)
                all.extend(parse_html_file(path))
    return all

if __name__ == "__main__":
    input_dir = "/mnt/c/Users/drayg/Downloads/brian_fb_dump/your_facebook_activity/messages/e2ee_cutover"
    print(f"[+] Recursively parsing: {input_dir}")
    all_msgs = collect_all_messages(input_dir)

    output_file = "conversations_parsed.jsonl"
    with open(output_file, 'w', encoding='utf-8') as f:
        for msg in all_msgs:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')

    print(f"[+] Writing {len(all_msgs)} parsed messages to {output_file}")
    print("[✔] Done.")