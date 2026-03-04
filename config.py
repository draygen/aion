CONFIG = {
    "model": "qwen2.5:7b",
    "backend": "ollama",
    "retrieval": "embed",  # embed | lexical
    "embed_backend": "tfidf",  # tfidf | (legacy: ollama)
    "facts_files": [
        "data/profile.jsonl",            # curated identity facts (highest priority)
        "data/brian_facts.jsonl",
        "data/fb_qa_pairs.jsonl",
        "data/fb_messages_parsed.jsonl", # Brian's FB messages
        "data/jenn_messages.jsonl",      # Jennifer's FB messages (verbatim, with from/to/date)
    ],
    "openai_api_key": "",
    "elevenlabs_api_key": "",            # set in config.local.py
    "elevenlabs_voice_id": "pNInz6obpgDQGcFmaJgB",  # "Adam" - deep male voice (default)
    "vast_api_key": "",                  # set in config.local.py
    "vast_ssh_key": "~/.ssh/id_ed25519",
    "admin_key": "",                     # set in config.local.py
    "admin_password": "",                # set in config.local.py
    "auto_extract_facts": True,
    "shared_facts_file": "data/shared_learned.jsonl",
    "TTS_ENABLED": False,
    "VOICE_MODE": False,
    "whisper_model": "base",
}

# Load local overrides (API keys, passwords — never committed to git)
try:
    from config_local import CONFIG_LOCAL
    CONFIG.update(CONFIG_LOCAL)
except ImportError:
    pass
