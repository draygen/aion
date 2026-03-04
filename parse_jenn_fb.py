"""
Parse Jennifer Frotten/Wallace's Facebook message export into structured JSONL.
Each record stores a conversation window (5 messages) with full from/to/date context.
Output: data/jenn_messages.jsonl
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

INBOX = Path("/mnt/c/jennfb/your_facebook_activity/messages/inbox")
OUT   = Path("data/jenn_messages.jsonl")
JENN  = {"jennifer frotten", "jennifer wallace", "jennifer frotten wallace"}
WINDOW = 5   # messages per chunk
STEP   = 3   # overlap step


def fix_encoding(text: str) -> str:
    """Facebook exports UTF-8 text encoded as latin-1. Fix it."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except Exception:
        return text


def load_thread(thread_dir: Path) -> dict | None:
    """Load all message_N.json files in a thread dir, return combined dict."""
    parts = sorted(thread_dir.glob("message_*.json"))
    if not parts:
        return None

    combined = None
    all_messages = []

    for part in parts:
        try:
            raw = part.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as e:
            print(f"  skip {part}: {e}", file=sys.stderr)
            continue

        if combined is None:
            combined = data
        all_messages.extend(data.get("messages", []))

    if not combined:
        return None

    combined["messages"] = all_messages
    return combined


def fmt_ts(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def fmt_date_only(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def msg_line(msg: dict) -> str:
    sender = fix_encoding(msg.get("sender_name", "Unknown"))
    ts     = fmt_ts(msg.get("timestamp_ms", 0))
    content = fix_encoding(msg.get("content", "[no text — photo/sticker/reaction]"))
    return f"[{ts}] {sender}: {content}"


def make_records(thread_dir: Path) -> list[dict]:
    data = load_thread(thread_dir)
    if not data:
        return []

    # Participants
    participants = [fix_encoding(p["name"]) for p in data.get("participants", [])]
    others = [p for p in participants if p.lower() not in JENN]
    jenn_name = next((p for p in participants if p.lower() in JENN), "Jennifer")

    # Sort messages oldest → newest
    messages = sorted(data.get("messages", []), key=lambda m: m.get("timestamp_ms", 0))

    # Filter to messages that have text content
    text_msgs = [m for m in messages if m.get("content")]
    if not text_msgs:
        return []

    thread_label = ", ".join(others) if others else "Unknown"
    thread_id = thread_dir.name

    records = []

    # Sliding window over messages
    for i in range(0, len(text_msgs), STEP):
        chunk = text_msgs[i : i + WINDOW]
        if not chunk:
            continue

        ts_start = chunk[0].get("timestamp_ms", 0)
        ts_end   = chunk[-1].get("timestamp_ms", 0)
        date_str = fmt_date_only(ts_start)

        # Build output block
        lines = [f"Thread: {jenn_name} ↔ {thread_label}"]
        lines.append(f"Participants: {', '.join(participants)}")
        lines.append("")
        for msg in chunk:
            lines.append(msg_line(msg))
        output_block = "\n".join(lines)

        # Build searchable input key
        senders_in_chunk = {fix_encoding(m.get("sender_name", "")) for m in chunk}
        input_key = (
            f"Jennifer messages with {thread_label} on {date_str} "
            f"| senders: {', '.join(sorted(senders_in_chunk))}"
        )

        records.append({
            "input":        input_key,
            "output":       output_block,
            "thread":       thread_label,
            "thread_id":    thread_id,
            "participants": participants,
            "date":         date_str,
            "ts_start":     ts_start,
            "ts_end":       ts_end,
        })

    # Also add one record per individual message for exact lookup
    for msg in text_msgs:
        sender  = fix_encoding(msg.get("sender_name", "Unknown"))
        ts      = msg.get("timestamp_ms", 0)
        content = fix_encoding(msg.get("content", ""))
        if not content.strip():
            continue

        records.append({
            "input":        f"{sender} said to {thread_label} on {fmt_date_only(ts)}",
            "output":       f"[{fmt_ts(ts)}] From: {sender} → To: {thread_label}\n\"{content}\"",
            "thread":       thread_label,
            "thread_id":    thread_id,
            "participants": participants,
            "date":         fmt_date_only(ts),
            "ts_start":     ts,
            "ts_end":       ts,
        })

    return records


def main():
    if not INBOX.exists():
        print(f"ERROR: {INBOX} not found", file=sys.stderr)
        sys.exit(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)

    thread_dirs = [d for d in INBOX.iterdir() if d.is_dir()]
    print(f"Found {len(thread_dirs)} conversation threads")

    total = 0
    with OUT.open("w", encoding="utf-8") as f:
        for thread_dir in sorted(thread_dirs):
            records = make_records(thread_dir)
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            total += len(records)
            if records:
                print(f"  {thread_dir.name}: {len(records)} records")

    print(f"\nDone. {total} total records → {OUT}")


if __name__ == "__main__":
    main()
