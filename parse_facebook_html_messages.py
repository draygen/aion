import os
import json
from bs4 import BeautifulSoup
from tqdm import tqdm
import argparse

def extract_messages_from_html(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f, 'html.parser')

    convo = {
        "participants": [],
        "messages": []
    }

    # Get participants
    participants_div = soup.find_all('div', class_='participants')
    if participants_div:
        convo["participants"] = [p.strip() for p in participants_div[0].text.split(',')]

    # Get messages
    messages_divs = soup.find_all('div', class_='message')
    for div in messages_divs:
        try:
            user = div.find('div', class_='user').text.strip()
            timestamp = div.find('div', class_='meta').text.strip()
            text_div = div.find_next_sibling('p')
            text = text_div.text.strip() if text_div else ""
            convo["messages"].append({
                "sender": user,
                "timestamp": timestamp,
                "text": text
            })
        except Exception:
            continue

    return convo

def process_all_html(root_dir):
    output = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename == "message_1.html":
                full_path = os.path.join(dirpath, filename)
                convo = extract_messages_from_html(full_path)
                if convo["messages"]:
                    output.append(convo)
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", required=True, help="Directory containing message_1.html files in nested folders")
    parser.add_argument("--output", default="conversations.jsonl", help="Output file path")
    args = parser.parse_args()

    print(f"Parsing HTML message files in: {args.input_dir}")
    conversations = process_all_html(args.input_dir)

    with open(args.output, 'w', encoding='utf-8') as out_file:
        for convo in tqdm(conversations, desc="Writing"):
            json.dump(convo, out_file)
            out_file.write("\n")

    print(f"Done. Extracted {len(conversations)} conversations into {args.output}")

