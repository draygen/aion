import json
import os
from typing import List, Dict, Any, Optional

from config import CONFIG

memory: List[Dict[str, Any]] = []

# TF-IDF cache
_tfidf_vectorizer = None
_tfidf_matrix = None


def _shared_facts_path() -> str:
    return CONFIG.get("shared_facts_file", "data/shared_learned.jsonl")


def _pending_facts_path() -> str:
    return CONFIG.get("pending_facts_file", "data/pending_learned.jsonl")


def _normalize_user_scope(user_scope: Optional[str]) -> str:
    return (user_scope or "").strip().lower()


def _primary_user() -> str:
    return _normalize_user_scope(CONFIG.get("primary_user", "brian"))


def _legacy_shared_fact_owner() -> str:
    return _normalize_user_scope(CONFIG.get("legacy_shared_fact_owner", _primary_user()))


def _safe_user_key(user_scope: Optional[str]) -> str:
    normalized = _normalize_user_scope(user_scope)
    return "".join(ch for ch in normalized if ch.isalnum() or ch in {"_", "-"})


def _user_memory_dir() -> str:
    return CONFIG.get("user_memory_dir", "data/users")


def _user_facts_path(user_scope: Optional[str]) -> str:
    user_key = _safe_user_key(user_scope)
    if not user_key:
        return _shared_facts_path()
    return os.path.join(_user_memory_dir(), user_key, "learned.jsonl")


def _user_pending_facts_path(user_scope: Optional[str]) -> str:
    user_key = _safe_user_key(user_scope)
    if not user_key:
        return _pending_facts_path()
    return os.path.join(_user_memory_dir(), user_key, "pending.jsonl")


def _shared_fact_files() -> List[str]:
    return list(CONFIG.get("shared_fact_files") or [])


def _configured_user_fact_files(user_scope: Optional[str]) -> List[str]:
    user_key = _normalize_user_scope(user_scope)
    configured = CONFIG.get("user_fact_files") or {}
    files = configured.get(user_key)
    if files is not None:
        return list(files)
    # Backwards compatibility: if no per-user mapping exists, preserve the old global behavior.
    return list(CONFIG.get("facts_files") or [])


def _default_files_for_user(user_scope: Optional[str], include_pending: bool = False) -> List[str]:
    files: List[str] = []
    files.extend(_shared_fact_files())
    files.extend(_configured_user_fact_files(user_scope))

    normalized = _normalize_user_scope(user_scope)
    if normalized:
        files.append(_user_facts_path(normalized))
        if include_pending or CONFIG.get("load_pending_facts", False):
            files.append(_user_pending_facts_path(normalized))

    if normalized and normalized == _legacy_shared_fact_owner():
        files.insert(0, _shared_facts_path())
        if include_pending or CONFIG.get("load_pending_facts", False):
            files.insert(1, _pending_facts_path())

    # Preserve order while removing duplicates.
    seen = set()
    unique_files: List[str] = []
    for filename in files:
        if filename not in seen:
            unique_files.append(filename)
            seen.add(filename)
    return unique_files


def _normalize_fact(raw_fact: Dict[str, Any]) -> Dict[str, Any]:
    fact = dict(raw_fact)
    if "input" not in fact and "question" in fact:
        fact["input"] = fact.pop("question")
    if "output" not in fact and "answer" in fact:
        fact["output"] = fact.pop("answer")
    if "output" not in fact and "text" in fact:
        fact["output"] = fact["text"]
    return fact


def _infer_source_type(filename: str, fact: Dict[str, Any]) -> str:
    meta = fact.get("_meta") or {}
    if meta.get("source_type"):
        return meta["source_type"]

    lower_name = os.path.basename(filename).lower()
    if filename == _shared_facts_path():
        return "manual_learned"
    if filename == _pending_facts_path():
        return "llm_extracted_pending"
    if "profile" in lower_name or "facts" in lower_name:
        return "curated_fact"
    if "qa" in lower_name:
        return "qa_pair"
    if "message" in lower_name:
        return "verbatim_message"
    return "imported_fact"


def _default_trust_for_source(source_type: str) -> bool:
    return source_type not in {"llm_extracted_pending", "llm_extracted"}


def _attach_provenance(fact: Dict[str, Any], filename: str) -> Dict[str, Any]:
    normalized = _normalize_fact(fact)
    meta = dict(normalized.get("_meta") or {})
    source_type = _infer_source_type(filename, normalized)
    meta.setdefault("source_type", source_type)
    meta.setdefault("source_file", filename)
    meta.setdefault("trusted", _default_trust_for_source(source_type))
    meta.setdefault("status", "active" if meta["trusted"] else "pending")
    normalized["_meta"] = meta
    return normalized


def _is_active_fact(fact: Dict[str, Any]) -> bool:
    meta = fact.get("_meta") or {}
    status = meta.get("status", "active")
    if status != "active":
        return CONFIG.get("load_pending_facts", False)
    return True


def _load_fact_records(files: List[str]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for filename in files:
        if not os.path.exists(filename):
            continue
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    fact = _attach_provenance(json.loads(line), filename)
                    if not _is_active_fact(fact):
                        continue
                    records.append(fact)
                except Exception:
                    pass
    return records


def load_facts(files: List[str] = None, user_scope: Optional[str] = None) -> int:
    """Load facts into memory. Returns count loaded into active retrieval memory."""
    global memory, _tfidf_vectorizer, _tfidf_matrix
    memory.clear()
    _tfidf_vectorizer = None
    _tfidf_matrix = None

    if files is None:
        files = _default_files_for_user(user_scope or _primary_user())

    memory.extend(_load_fact_records(files))
    return len(memory)


def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def add_fact(
    input_text: Optional[str],
    output_text: str,
    metadata: Optional[Dict[str, Any]] = None,
    destination: str = "shared",
    user_scope: Optional[str] = None,
) -> str:
    """Persist a fact, optionally as pending review, and refresh active retrieval state."""
    global _tfidf_vectorizer, _tfidf_matrix
    fact: Dict[str, Any] = {}
    if input_text:
        fact["input"] = input_text.strip()
    if output_text:
        fact["output"] = output_text.strip()
    if not fact:
        return "Nothing to save."

    meta = dict(metadata or {})
    owner = _normalize_user_scope(user_scope or meta.get("owner") or meta.get("source_user"))
    if owner:
        meta.setdefault("owner", owner)
    if destination == "pending":
        meta.setdefault("source_type", "llm_extracted_pending")
        meta.setdefault("trusted", False)
        meta.setdefault("status", "pending")
        path = _user_pending_facts_path(owner) if owner else _pending_facts_path()
    else:
        meta.setdefault("source_type", "manual_learned")
        meta.setdefault("trusted", True)
        meta.setdefault("status", "active")
        path = _user_facts_path(owner) if owner else _shared_facts_path()

    fact["_meta"] = meta

    if meta.get("status", "active") == "active" and (not owner or owner == _primary_user()):
        memory.insert(0, fact)
        _tfidf_vectorizer = None
        _tfidf_matrix = None
    try:
        _append_jsonl(path, fact)
    except Exception as e:
        return f"Saved in memory but failed to persist: {e}"
    return "Saved for review." if destination == "pending" else "Saved."


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
        _tfidf_vectorizer = TfidfVectorizer(max_features=80000, ngram_range=(1, 2))
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
        s = s[: max_len - 3] + "..."
    return s


def get_facts(input_str: str, k: int = 12, user_scope: Optional[str] = None) -> List[str]:
    """Return up to k relevant snippets. Prefer TF-IDF if enabled and available."""
    normalized_scope = _normalize_user_scope(user_scope)
    use_global_cache = not normalized_scope or normalized_scope == _primary_user()
    fact_pool = memory if use_global_cache else _load_fact_records(_default_files_for_user(normalized_scope))

    if use_global_cache:
        _ensure_tfidf()
    if use_global_cache and _tfidf_vectorizer is not None and _tfidf_matrix is not None:
        try:
            q = _tfidf_vectorizer.transform([input_str])
            from sklearn.metrics.pairwise import cosine_similarity

            sims = cosine_similarity(q, _tfidf_matrix).ravel()
            ranked = sorted(enumerate(sims), key=lambda t: t[1], reverse=True)
            results: List[str] = []
            seen = set()
            for idx, score in ranked[: k * 3]:
                if score <= 0:
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

    if not fact_pool:
        return []
    scored = []
    for fact in fact_pool:
        source = fact.get("input") or fact.get("output") or ""
        out = fact.get("output") or fact.get("input") or ""
        if not out:
            continue
        scored.append((_score(input_str, source + " " + out), _format_snippet(fact)))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [snip for score, snip in scored[:k] if score > 0]


def get_fact(input_str: str, user_scope: Optional[str] = None):
    """Backwards-compatible: return a single best fact (first of top-k)."""
    facts = get_facts(input_str, k=1, user_scope=user_scope)
    return facts[0] if facts else None


def remember(message):
    # For future runtime learning
    pass


def recall(n: int = 10):
    lines = []
    for fact in memory[:n]:
        i = fact.get("input")
        o = fact.get("output")
        meta = fact.get("_meta") or {}
        label = meta.get("source_type", "unknown")
        if i and o:
            lines.append(f"[{label}] {i} -> {o}")
        else:
            lines.append(f"[{label}] {o or i or '(empty)'}")
    return "\n".join(lines)


load_facts()
