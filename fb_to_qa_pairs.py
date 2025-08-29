import os
import json

# --- CONFIG ---
INBOX_DIR = r"C:\jarvis\messages\inbox"
OUTPUT_FILE = r"C:\jarvis\data\fb_qa_pairs.jsonl"
YOUR_NAME = "Brian Wallace"  # Make sure this matches exactly how you appear in messages!

def scan_messages(folder):
    for thread in os.listdir(folder):
        thread_path = os.path.join(folder, thread)
        if not os.path.isdir(thread_path):
            continue
        for fname in os.listdir(thread_path):
            if fname.endswith('.json'):
                yield os.path.join(thread_path, fname)

def messages_to_qa_pairs():
    count = 0
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for msgfile in scan_messages(INBOX_DIR):
            try:
                with open(msgfile, encoding="utf-8") as f:
                    data = json.load(f)
                    messages = data.get("messages", [])
                    messages = list(reversed(messages))  # FB is newest-first, reverse to oldest-first
                    for i in range(len(messages) - 1):
                        msg = messages[i]
                        next_msg = messages[i + 1]
                        # Only create pair if:
                        # 1. Current msg is NOT from you, and HAS content
                        # 2. Next msg IS from you, and HAS content
                        if ("content" in msg and
                            msg.get("sender_name") != YOUR_NAME and
                            "content" in next_msg and
                            next_msg.get("sender_name") == YOUR_NAME):
                            prompt = f"{msg['sender_name']}: {msg['content'].replace(chr(10), ' ')}"
                            reply = f"{YOUR_NAME}: {next_msg['content'].replace(chr(10), ' ')}"
                            qa = {"input": prompt, "output": reply}
                            out.write(json.dumps(qa, ensure_ascii=False) + "\n")
                            count += 1
            except Exception as e:
                print(f"Error in {msgfile}: {e}")
    print(f"Done! {count} Q/A pairs written to {OUTPUT_FILE}")

if __name__ == "__main__":
    messages_to_qa_pairs()