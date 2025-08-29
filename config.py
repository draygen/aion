CONFIG = {
    "model": "mistral",
    "backend": "ollama",
    "retrieval": "embed",  # embed | lexical
    "embed_backend": "tfidf",  # tfidf | (legacy: ollama)
    "facts_files": [
        "data/profile.jsonl",            # curated, high-precision identity facts (load first)
        "data/brian_facts.jsonl",
        "data/fb_qa_pairs.jsonl",
    ],
    "openai_api_key": "sk-xxxx"  # Change this if using OpenAI
}
