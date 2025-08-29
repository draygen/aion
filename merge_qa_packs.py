import json
import os
os.environ["HF_HOME"] = r"C:\jarvis\hf_cache"
import random
from datasets import load_dataset


# --- SETTINGS ---
YOUR_QA_FILE = r"C:\jarvis\data\brian_facts.jsonl"
MERGED_FILE = r"C:\jarvis\data\mega_qa.jsonl"

def download_openhermes():
    print("Loading OpenHermes dataset from Hugging Face...")
    dataset = load_dataset("teknium/OpenHermes-2.5", split="train")
    print(f"Loaded {len(dataset)} entries from OpenHermes.")
    return dataset

def convert_openhermes_to_jsonl(dataset, out_path):
    print("Converting OpenHermes format to JSONL...")
    count = 0
    with open(out_path, "w", encoding="utf-8") as outfile:
        for entry in dataset:
            conversations = entry.get("conversations", [])
            if len(conversations) >= 2:
                for i in range(1, len(conversations)):
                    if conversations[i-1]["from"] == "human" and conversations[i]["from"] == "gpt":
                        question = conversations[i-1]["value"].strip()
                        answer = conversations[i]["value"].strip()
                        if question and answer:
                            json.dump({"input": question, "output": answer}, outfile, ensure_ascii=False)
                            outfile.write("\n")
                            count += 1
    print(f"Converted {count} Q/A pairs from OpenHermes.")

def merge_jsonl_files(files, out_path, shuffle=True):
    print("Merging all Q/A files...")
    all_pairs = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    all_pairs.append(json.loads(line))
                except Exception:
                    continue
    if shuffle:
        random.shuffle(all_pairs)
    with open(out_path, "w", encoding="utf-8") as f:
        for obj in all_pairs:
            json.dump(obj, f, ensure_ascii=False)
            f.write("\n")
    print(f"Total merged Q/A pairs: {len(all_pairs)}")
    print(f"Merged file saved to: {out_path}")

def main():
    tmp_hermes_clean = r"C:\jarvis\data\openhermes_clean.jsonl"
    # Step 1: Download OpenHermes dataset
    dataset = download_openhermes()
    # Step 2: Convert to your Q/A format
    convert_openhermes_to_jsonl(dataset, tmp_hermes_clean)
    # Step 3: Merge your Q/A and the open set
    merge_jsonl_files([YOUR_QA_FILE, tmp_hermes_clean], MERGED_FILE)

if __name__ == "__main__":
    main()
