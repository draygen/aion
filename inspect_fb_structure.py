import os
import json
from bs4 import BeautifulSoup

def extract_messages_with_meta(html_path):
    messages = []
    with open(html_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'lxml')

    threads = soup.find_all("div", class_="message")
    for msg in threads:
        try:
            user = msg.find("div", class_="user").get_text(strip=True)
            timestamp = msg.find("div", class_="meta").get_text(strip=True)
            text_div = msg.find_next_sibling("p")
            if text_div:
                content = text_div.get_text(strip=True)
                if not content or any([
                    'reacted to' in content.lower(),
                    'liked a message' in content.lower(),
                    'removed a' in content.lower(),
                    'sent a sticker' in content.lower(),
                    'you waved' in content.lower()
                ]):
                    continue  # Skip junk
                message_str = f"[{timestamp}] {user}: {content}"
                messages.append(message_str)
        except Exception:
            continue  # Some malformed block, skip

    return messages

def gather_all_html_convos(root_dir):
    all_msgs = []
    for subdir, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith('.html'):
                filepath = os.path.join(subdir, file)
                print(f"Processing {filepath}")
                all_msgs.extend(extract_messages_with_meta(filepath))
    return all_msgs

def save_to_json(data, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    root_dir = r"c:\users\drayg\Downloads\Brian Facebook Dump"
    output_file = "facebook_messages_clean_with_meta.json"

    messages = gather_all_html_convos(root_dir)
    save_to_json(messages, output_file)

    print(f"Saved {len(messages)} cleaned messages with metadata to {output_file}")
