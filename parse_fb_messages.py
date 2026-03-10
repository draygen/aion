#!/usr/bin/env python3
"""
Comprehensive Facebook Message Parser

Parses all Facebook message HTML files from a data dump and converts them
to JSONL format compatible with the memory system (brain.py).

Output format: {"input": "OtherPerson: their message", "output": "Brian Wallace: response"}
"""

import os
import re
import json
import html
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional

# Configuration
FB_MESSAGES_ROOT = "/mnt/c/Users/drayg/Downloads/brian_fb_dump/your_facebook_activity/messages"
OUTPUT_FILE = "data/fb_messages_parsed.jsonl"
OWNER_NAME = "Brian Wallace"  # The account owner

# Directories to scan
SCAN_DIRS = ["inbox", "e2ee_cutover", "archived_threads", "filtered_threads"]


def decode_fb_text(text: str) -> str:
    """Decode Facebook's mojibake encoding (UTF-8 stored as latin-1)."""
    if not text:
        return ""
    try:
        # Facebook exports UTF-8 as latin-1 encoded bytes
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def clean_text(text: str) -> str:
    """Clean and normalize message text."""
    if not text:
        return ""
    # Decode mojibake
    text = decode_fb_text(text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse Facebook timestamp string to datetime."""
    if not ts_str:
        return None
    ts_str = clean_text(ts_str)
    # Format: "Jun 07, 2024 10:48:59 pm"
    formats = [
        "%b %d, %Y %I:%M:%S %p",
        "%b %d, %Y %I:%M %p",
        "%B %d, %Y %I:%M:%S %p",
        "%B %d, %Y at %I:%M %p",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def parse_message_html(file_path: str) -> List[Dict]:
    """
    Parse a single Facebook message HTML file.
    Returns list of message dicts: {sender, message, timestamp, timestamp_raw}
    """
    messages = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
    except Exception as e:
        print(f"[!] Error reading {file_path}: {e}")
        return messages

    # Get conversation partner from title
    title_tag = soup.find("title")
    conversation_title = clean_text(title_tag.get_text()) if title_tag else "Unknown"

    # Find all message blocks (class="_a6-g")
    msg_blocks = soup.find_all("div", class_="_a6-g")

    for block in msg_blocks:
        try:
            # Sender (class="_a6-h" with "_a6-i")
            sender_div = block.find("div", class_="_a6-h")
            if not sender_div:
                continue
            sender = clean_text(sender_div.get_text())

            # Message content (class="_a6-p")
            content_div = block.find("div", class_="_a6-p")
            if not content_div:
                continue

            # Extract text, handling nested divs
            # The actual text is often in nested divs
            text_parts = []
            for elem in content_div.stripped_strings:
                txt = clean_text(elem)
                # Skip placeholder text
                if txt and "This message was unsent" not in txt and "Click for" not in txt:
                    text_parts.append(txt)

            message_text = " ".join(text_parts).strip()

            # Skip empty messages or media-only
            if not message_text:
                continue

            # Timestamp (class="_a72d")
            timestamp_div = block.find("div", class_="_a72d")
            timestamp_raw = clean_text(timestamp_div.get_text()) if timestamp_div else ""
            timestamp = parse_timestamp(timestamp_raw)

            messages.append({
                "sender": sender,
                "message": message_text,
                "timestamp": timestamp,
                "timestamp_raw": timestamp_raw,
                "conversation": conversation_title
            })

        except Exception:
            continue

    return messages


def find_all_message_files(root_dir: str) -> List[str]:
    """Find all message HTML files recursively."""
    files = []
    for scan_dir in SCAN_DIRS:
        dir_path = os.path.join(root_dir, scan_dir)
        if not os.path.exists(dir_path):
            continue
        for dirpath, _, filenames in os.walk(dir_path):
            for fname in filenames:
                if fname.startswith("message") and fname.endswith(".html"):
                    files.append(os.path.join(dirpath, fname))
    return files


def messages_to_qa_pairs(messages: List[Dict]) -> List[Dict]:
    """
    Convert chronological messages to Q&A pairs.
    When someone else sends a message and Brian responds, create a pair.
    """
    # Sort by timestamp (oldest first for proper conversation flow)
    sorted_msgs = sorted(
        [m for m in messages if m["timestamp"]],
        key=lambda x: x["timestamp"]
    )

    pairs = []
    i = 0
    while i < len(sorted_msgs) - 1:
        curr = sorted_msgs[i]
        next_msg = sorted_msgs[i + 1]

        # If current is from someone else and next is from Brian
        if curr["sender"] != OWNER_NAME and next_msg["sender"] == OWNER_NAME:
            pairs.append({
                "input": f"{curr['sender']}: {curr['message']}",
                "output": f"{OWNER_NAME}: {next_msg['message']}"
            })
            i += 2  # Skip both messages
        else:
            i += 1

    return pairs


def messages_to_conversation_chunks(messages: List[Dict], chunk_size: int = 5) -> List[Dict]:
    """
    Alternative: Create conversation context chunks.
    Groups messages into context windows.
    """
    sorted_msgs = sorted(
        [m for m in messages if m["timestamp"]],
        key=lambda x: x["timestamp"]
    )

    chunks = []
    for i in range(0, len(sorted_msgs), chunk_size):
        chunk = sorted_msgs[i:i + chunk_size]
        if len(chunk) < 2:
            continue

        # Build context
        context_lines = []
        for msg in chunk:
            context_lines.append(f"{msg['sender']}: {msg['message']}")

        chunks.append({
            "input": "Facebook conversation context",
            "output": "\n".join(context_lines),
            "conversation": chunk[0].get("conversation", "Unknown"),
            "date_range": f"{chunk[0]['timestamp_raw']} - {chunk[-1]['timestamp_raw']}"
        })

    return chunks


def main():
    print(f"[*] Scanning Facebook messages from: {FB_MESSAGES_ROOT}")

    # Find all message files
    message_files = find_all_message_files(FB_MESSAGES_ROOT)
    print(f"[*] Found {len(message_files)} message files")

    # Parse all messages
    all_messages = []
    for filepath in message_files:
        msgs = parse_message_html(filepath)
        all_messages.extend(msgs)
        if msgs:
            print(f"[+] Parsed {len(msgs):4d} messages from {os.path.basename(os.path.dirname(filepath))}")

    print(f"\n[*] Total messages parsed: {len(all_messages)}")

    # Convert to Q&A pairs
    qa_pairs = messages_to_qa_pairs(all_messages)
    print(f"[*] Generated {len(qa_pairs)} Q&A pairs")

    # Also create conversation chunks for context
    conv_chunks = messages_to_conversation_chunks(all_messages)
    print(f"[*] Generated {len(conv_chunks)} conversation chunks")

    # Write output
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        # Write Q&A pairs first (for direct retrieval)
        for pair in qa_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        # Write conversation chunks (for context)
        for chunk in conv_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"\n[✓] Output written to: {OUTPUT_FILE}")
    print(f"    Total entries: {len(qa_pairs) + len(conv_chunks)}")

    # Show sample output
    print("\n[*] Sample Q&A pairs:")
    for pair in qa_pairs[:3]:
        print(f"    Input:  {pair['input'][:60]}...")
        print(f"    Output: {pair['output'][:60]}...")
        print()


if __name__ == "__main__":
    main()
