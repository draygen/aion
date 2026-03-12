CONFIG = {
    "model": "qwen2.5:7b",
    "backend": "ollama",
    "retrieval": "embed",  # embed | lexical
    "embed_backend": "tfidf",  # tfidf | (legacy: ollama)
    "primary_user": "brian",
    "shared_fact_files": [],
    "user_fact_files": {
        "brian": [
            "data/profile.jsonl",            # curated identity facts (highest priority)
            "data/brian_facts.jsonl",
            "data/fb_qa_pairs.jsonl",
            "data/fb_messages_parsed.jsonl", # Brian's FB messages
            "data/jenn_messages.jsonl",      # Jennifer's FB messages (verbatim, with from/to/date)
        ],
    },
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
    "auto_extract_mode": "pending",      # pending | shared | off
    "shared_facts_file": "data/shared_learned.jsonl",
    "pending_facts_file": "data/pending_learned.jsonl",
    "user_memory_dir": "data/users",
    "legacy_shared_fact_owner": "brian",
    "cors_origins": [
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost:3001",   # PromptGen server (WSL → Windows via mirrored networking)
        "http://localhost:5173",   # PromptGen client (Vite)
        "null",  # Electron/file:// clients
    ],
    "cookie_samesite": "Lax",
    "cookie_secure": False,
    "memory_browser_requires_auth": True,
    "load_pending_facts": False,
    "authorized_network_targets": [
        "localhost",
        "127.0.0.1",
        "::1",
    ],
    "network_ops_enabled": True,
    "TTS_ENABLED": False,
    "VOICE_MODE": False,
    "whisper_model": "base",
    # Memory / Goals (Phase 1 — Sapphire port)
    "EMBEDDING_PROVIDER": "null",   # null | local | api
    "EMBEDDING_API_URL": "",        # remote OpenAI-compatible embeddings endpoint
    "EMBEDDING_API_KEY": "",
    "USER_TIMEZONE": "America/New_York",
    "memory_enabled": True,
    "goals_enabled": True,
}

# Load local overrides (API keys, passwords — never committed to git)
try:
    from config_local import CONFIG_LOCAL
    CONFIG.update(CONFIG_LOCAL)
except ImportError:
    pass
