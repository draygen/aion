import os
import json
from bs4 import BeautifulSoup

def parse_message_html(file_path):
    messages = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            html = f.read()
            soup = BeautifulSoup(html, "html.parser")

        blocks = soup.find_all("div")
        print(f"[~] {len(blocks)} <div> blocks found in {file_path}")

        if not blocks:
            print(f"[!] No <div> blocks in {file_path}")

        for idx, block in enumerate(blocks):
            try:
                user = block.find("div", class_="user") or block.find("span", class_="user") or block.find("strong")
                timestamp = block.find("div", class_="meta") or block.find("span", class_="meta")
                content = (
                    block.find("p") or 
                    block.find("div", class_="message") or 
                    block.find("div", class_="text") or 
                    block.find("span", class_="text")
                )

                if user and timestamp and content:
                    messages.append({
                        "sender": user.get_text(strip=True),
                        "timestamp": timestamp.get_text(strip=True),
                        "message": content.get_text(strip=True)
                    })
                else:
                    print(f"[-] Skipped block #{idx}: missing elements.")
                    if not user: print("    └─ Missing user")
                    if not timestamp: print("    └─ Missing timestamp")
                    if not content: print("    └─ Missing content")
            except Exception as e:
                print(f"[!] Exception parsing block #{idx} in {file_path}: {e}")
    except Exception as e:
        print(f"[!] Error opening/parsing {file_path}: {e}")

    print(f"[~] Parsed {len(messages)} messages from {os.path.basename(file_path)}")
    return messages

def walk_and_parse(root_dir):
    all_msgs = []
    total_files = 0
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname == "message_1.html":
                total_files += 1
                full_path = os.path.join(dirpath, fname)
                print(f"[>] Parsing {full_path}")
                msgs = parse_message_html(full_path)
                all_msgs.extend(msgs)

    output_path = "conversations_parsed.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for m in all_msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    print(f"[+] Found {total_files} message_1.html files.")
    print(f"[+] Wrote {len(all_msgs)} total messages to {output_path}")
    print("[✔] Done.")

if __name__ == "__main__":
    ROOT = "/mnt/c/Users/drayg/Downloads/brian_fb_dump/your_facebook_activity/messages/e2ee_cutover"
    walk_and_parse(ROOT)

