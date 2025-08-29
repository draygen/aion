import json
import os
import math
from typing import List, Dict, Any, Optional

from config import CONFIG

memory: List[Dict[str, Any]] = []

# TF-IDF cache
_tfidf_vectorizer = None
_tfidf_matrix = None

# Persistent user-learned facts
_LEARNED_PATH = "data/user_learned.jsonl"

def load_facts(files: List[str] = None) -> int:
    """Load facts into memory. Returns count loaded.
    Uses CONFIG['facts_files'] by default so both personal and FB pairs are included.
    """
    global memory, _tfidf_vectorizer, _tfidf_matrix
    memory.clear()
    _tfidf_vectorizer = None
    _tfidf_matrix = None
    _embed_vectors = []

    if files is None:
        base = CONFIG.get("facts_files") or [
            "data/brian_facts.jsonl",
            "data/fb_qa_pairs.jsonl",
        ]
        # Learned facts first so they rank highly
        files = [_LEARNED_PATH] + base

    total = 0
    for filename in files:
        if not os.path.exists(filename):
            print(f"[brain.py] File not found: {filename}")
            continue
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    fact = json.loads(line)
                    # Normalize: allow either {input, output} or {question, answer} or {text}
                    if "input" not in fact and "question" in fact:
                        fact["input"] = fact.pop("question")
                    if "output" not in fact and "answer" in fact:
                        fact["output"] = fact.pop("answer")
                    if "output" not in fact and "text" in fact:
                        fact["output"] = fact["text"]
                    memory.append(fact)
                    total += 1
                except Exception as e:
                    print(f"[brain.py] Skipped bad line: {e}")

    print(f"[brain.py] Loaded {total} facts from {len(files)} file(s).")
    return total


def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def add_fact(input_text: Optional[str], output_text: str) -> str:
    """Add a new fact to memory and persist to user_learned.jsonl. Resets TF-IDF so it's rebuilt on next query."""
    global _tfidf_vectorizer, _tfidf_matrix
    fact: Dict[str, Any] = {}
    if input_text:
        fact["input"] = input_text.strip()
    if output_text:
        fact["output"] = output_text.strip()
    if not fact:
        return "Nothing to save."
    memory.insert(0, fact)  # prioritize new facts
    try:
        _append_jsonl(_LEARNED_PATH, fact)
    except Exception as e:
        return f"Saved in memory but failed to persist: {e}"
    # Invalidate TF-IDF to rebuild lazily
    _tfidf_vectorizer = None
    _tfidf_matrix = None
    return "Saved."


def _score(a: str, b: str) -> int:
    """Very simple overlap score for relevance ranking."""
    la = a.lower()
    lb = b.lower()
    score = 0
    for tok in set(la.split()):
        if tok and tok in lb:
            score += 1
    return score


def _ensure_tfidf():
    """Build TF-IDF matrix for current memory if configured and available."""
    global _tfidf_vectorizer, _tfidf_matrix
    if CONFIG.get("retrieval", "embed") != "embed":
        return
    if _tfidf_vectorizer is not None and _tfidf_matrix is not None:
        return
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        texts = []
        for fact in memory:
            inp = fact.get("input") or ""
            out = fact.get("output") or ""
            combined = (inp + " \n " + out).strip()
            texts.append(combined)
        if not texts:
            return
        _tfidf_vectorizer = TfidfVectorizer(max_features=80000, ngram_range=(1,2))
        _tfidf_matrix = _tfidf_vectorizer.fit_transform(texts)
        print(f"[brain.py] TF-IDF index ready for {len(texts)} facts.")
    except Exception as e:
        print(f"[brain.py] TF-IDF unavailable, falling back to lexical: {e}")
        _tfidf_vectorizer = None
        _tfidf_matrix = None


def _format_snippet(fact: Dict[str, Any], max_len: int = 280) -> str:
    inp = (fact.get("input") or "").strip()
    out = (fact.get("output") or "").strip()
    if inp and out:
        s = f"Q: {inp}\nA: {out}"
    else:
        s = out or inp
    s = s.replace("\r", " ").replace("\n", " ")
    if len(s) > max_len:
        s = s[:max_len-3] + "..."
    return s


def get_facts(input_str: str, k: int = 12) -> List[str]:
    """Return up to k relevant snippets. Prefer TF-IDF if enabled and available."""
    # TF-IDF retrieval
    _ensure_tfidf()
    if _tfidf_vectorizer is not None and _tfidf_matrix is not None:
        try:
            q = _tfidf_vectorizer.transform([input_str])
            from sklearn.metrics.pairwise import cosine_similarity
            sims = cosine_similarity(q, _tfidf_matrix).ravel()
            ranked = sorted(enumerate(sims), key=lambda t: t[1], reverse=True)
            results: List[str] = []
            seen = set()
            for idx, s in ranked[:k*3]:  # over-fetch
                if s <= 0:
                    continue
                snip = _format_snippet(memory[idx])
                if not snip or snip in seen:
                    continue
                seen.add(snip)
                results.append(snip)
                if len(results) >= k:
                    break
            if results:
                return results
        except Exception as e:
            print(f"[brain.py] TF-IDF query failed, falling back to lexical: {e}")

    # Lexical fallback
    if not memory:
        return []
    scored = []
    for fact in memory:
        source = fact.get("input") or fact.get("output") or ""
        out = fact.get("output") or fact.get("input") or ""
        if not out:
            continue
        scored.append((_score(input_str, source + " " + out), _format_snippet(fact)))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [snip for s, snip in scored[:k] if s > 0]


def get_fact(input_str: str):
    """Backwards-compatible: return a single best fact (first of top-k)."""
    facts = get_facts(input_str, k=1)
    return facts[0] if facts else None


def remember(message):
    # For future runtime learning
    pass


def recall(n: int = 10):
    # Dump the first n memory entries for debug
    lines = []
    for fact in memory[:n]:
        i = fact.get('input')
        o = fact.get('output')
        if i and o:
            lines.append(f"{i} -> {o}")
        else:
            lines.append(o or i or "(empty)")
    return "\n".join(lines)


# Load facts at import
load_facts()
