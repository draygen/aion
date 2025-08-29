import os
import json
from bs4 import BeautifulSoup

BASE_DIR = "/mnt/c/Users/drayg/Downloads/brian_fb_dump/your_facebook_activity/messages/inbox"
OUTPUT_FILE = "conversations_parsed.jsonl"

def extract_message_blocks(soup):
    return soup.find_all("div", class_="pam _3-95 _2pi0 _2lej uiBoxWhite noborder")

def parse_block(block):
    user = block.find("div", class_="_2ph_")
    timestamp = block.find("div", class_="_3-94 _2lem")
    content = block.find("div", class_="_3-96 _2let")

    user_text = user.get_text(strip=True) if user else None
    timestamp_text = timestamp.get_text(strip=True) if timestamp else None
    content_text = content.get_text(strip=True) if content else None

    missing = []
    if not user_text:
        missing.append("user")
    if not timestamp_text:
        missing.append("timestamp")
    if not content_text:
        missing.append("content")

    if missing:
        return None, missing

    return {
        "user": user_text,
        "timestamp": timestamp_text,
        "content": content_text
    }, None

def process_html_file(file_path):
    with open(file_path, "r", encoding="utf8") as f:
        soup = BeautifulSoup(f, "html.parser")

    blocks = extract_message_blocks(soup)
    messages = []
    skipped = []

    for idx, block in enumerate(blocks, start=1):
        msg, missing = parse_block(block)
        if msg:
            messages.append(msg)
        else:
            skipped.append((idx, missing))
    return messages, skipped

def walk_and_parse(base_dir):
    all_messages = []
    total_skipped = 0
    total_files = 0

    for root, _, files in os.walk(base_dir):
        for file in files:
            if file == "message_1.html":
                file_path = os.path.join(root, file)
                print(f"[>] Parsing {file_path}")
                messages, skipped = process_html_file(file_path)
                print(f"[~] Found {len(messages)} messages, Skipped {len(skipped)} blocks.")

                for idx, reasons in skipped:
                    print(f"[-] Skipped block #{idx}:")
                    for reason in reasons:
                        print(f"    └─ Missing {reason}")

                all_messages.extend(messages)
                total_skipped += len(skipped)
                total_files += 1

    print(f"[+] Parsed {len(all_messages)} total messages from {total_files} files.")
    print(f"[+] Skipped {total_skipped} message blocks due to missing fields.")

    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        for msg in all_messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    print(f"[✔] Output saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    walk_and_parse(BASE_DIR)

