import os
import json
import argparse
from tqdm import tqdm

def extract_conversations(folder_path):
    conversations = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith(".json"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "messages" in data:
                            messages = data.get("messages", [])
                            participants = [p['name'] for p in data.get("participants", [])]
                            convo_text = f"Conversation with {', '.join(participants)}:\n"
                            for msg in messages:
                                sender = msg.get("sender_name", "Unknown")
                                content = msg.get("content", "")
                                if content:
                                    convo_text += f"{sender}: {content}\n"
                            conversations.append({"document": convo_text})
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
    return conversations

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", required=True)
    parser.add_argument("--output", default="conversations.jsonl")
    args = parser.parse_args()

    print(f"Parsing conversations from: {args.input_dir}")
    all_convos = extract_conversations(args.input_dir)

    with open(args.output, "w", encoding="utf-8") as out_file:
        for convo in all_convos:
            out_file.write(json.dumps(convo, ensure_ascii=False) + "\n")

    print(f"Done. Extracted {len(all_convos)} full conversations into {args.output}")
