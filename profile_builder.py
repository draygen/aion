"""Generate and cache a rich Brian profile summary using GPT-4o.

Reads all curated facts from profile.jsonl, shared_learned.jsonl, and
user memory, synthesizes them into a cohesive narrative profile via GPT-4o,
and saves to data/brian_profile_summary.txt.

The saved summary is injected as a STATIC prefix in every system prompt,
enabling OpenAI prompt caching on the consistent portion of the context.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from config import CONFIG

PROFILE_SUMMARY_PATH = "data/brian_profile_summary.txt"
_PROFILE_SOURCE_FILES = [
    "data/profile.jsonl",
    "data/shared_learned.jsonl",
]
_profile_cache: Optional[str] = None


def _load_source_facts() -> list[str]:
    facts: list[str] = []
    for path in _PROFILE_SOURCE_FILES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    inp = (obj.get("input") or "").strip()
                    out = (obj.get("output") or "").strip()
                    if inp and out:
                        facts.append(f"Q: {inp}\nA: {out}")
                    elif out:
                        facts.append(out)
                except Exception:
                    pass
    return facts


def _build_with_gpt4o(facts: list[str]) -> str:
    from llm import _get_openai_client

    facts_text = "\n\n".join(facts)
    client = _get_openai_client()
    resp = client.chat.completions.create(
        model=CONFIG.get("openai_model", "gpt-4o"),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a knowledge synthesizer. Your job is to produce a rich, "
                    "detailed, cohesive profile from a raw set of facts. Be specific. "
                    "Include every name, date, relationship, and detail you find. "
                    "Never invent anything not present in the source facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Below are curated facts about Brian Wallace and the people in his life. "
                    "Synthesize them into a detailed 3rd-person profile covering:\n"
                    "- Identity & background (full name, aliases, location)\n"
                    "- Family in detail: wife, children (with birth dates), parents, siblings, "
                    "extended family, relationships between them\n"
                    "- Personality, character, communication style\n"
                    "- Technical skills, projects, and passions (Jarvis, hacking, music, cooking)\n"
                    "- Life philosophy and outlook\n"
                    "- Any notable details, preferences, or context\n\n"
                    "This profile will be permanently injected into an AI assistant's context "
                    "so it can answer questions about Brian and his circle with depth and accuracy. "
                    "Write in flowing prose. Be verbose and specific.\n\n"
                    f"SOURCE FACTS:\n{facts_text}\n\n"
                    "Write the full profile now:"
                ),
            },
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def build_profile_summary(save: bool = True) -> str:
    """Synthesize all source facts into a rich profile via GPT-4o and optionally save."""
    facts = _load_source_facts()
    if not facts:
        print("[profile] No source facts found.")
        return ""

    print(f"[profile] Building profile summary from {len(facts)} facts via GPT-4o...")
    summary = _build_with_gpt4o(facts)

    if save and summary:
        os.makedirs(os.path.dirname(PROFILE_SUMMARY_PATH), exist_ok=True)
        with open(PROFILE_SUMMARY_PATH, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"[profile] Saved to {PROFILE_SUMMARY_PATH} ({len(summary)} chars).")

    return summary


def get_profile_summary(force_rebuild: bool = False) -> str:
    """Return the cached profile summary, building it if missing or forced."""
    global _profile_cache

    if not force_rebuild and _profile_cache:
        return _profile_cache

    if not force_rebuild and os.path.exists(PROFILE_SUMMARY_PATH):
        with open(PROFILE_SUMMARY_PATH, encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            _profile_cache = content
            return content

    summary = build_profile_summary(save=True)
    _profile_cache = summary
    return summary


def invalidate_cache() -> None:
    """Clear the in-memory profile cache (e.g. after adding new facts)."""
    global _profile_cache
    _profile_cache = None


if __name__ == "__main__":
    print(build_profile_summary())
