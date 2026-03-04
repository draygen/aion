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
    "openai_api_key": "sk-xxxx",  # Change this if using OpenAI
    "elevenlabs_api_key": "sk_00658e431b1b66afac03c4804613864e82dfd15c7e1e2499",
    "elevenlabs_voice_id": "pNInz6obpgDQGcFmaJgB",  # "Adam" - deep male voice (default)
    "admin_key": "draygen2026",  # Secret key to access /logs
    "TTS_ENABLED": False,  # Text-to-speech output
    "VOICE_MODE": False,   # Voice input mode (uses Whisper STT)
    "whisper_model": "base",  # Whisper model: tiny, base, small, medium, large-v3
}
