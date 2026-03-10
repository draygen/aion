import hashlib
import json
import os
import pickle
import threading
import time
from typing import List, Dict, Any, Optional, Tuple

from config import CONFIG

memory: List[Dict[str, Any]] = []

# Curated index: curated_fact, qa_pair, manual_learned, imported_fact (NOT verbatim_message).
# Only this smaller pool is fed into TF-IDF — verbatim messages inflate the matrix
# from ~2K to ~28K docs (25× larger), causing a 2-second build on every invalidation.
_INDEX_SOURCE_TYPES = {"curated_fact", "qa_pair", "manual_learned", "imported_fact"}
_index_memory: List[Dict[str, Any]] = []   # subset of memory used for TF-IDF
_index_lock = threading.Lock()             # guards TF-IDF build

# TF-IDF cache (built over _index_memory only)
_tfidf_vectorizer = None
_tfidf_matrix = None

# OpenAI embedding cache
_embed_vectors = None  # np.ndarray shape (N, dims) once built
_EMBED_CACHE_PATH = "data/embeddings_cache.pkl"

# Query-level caches (avoids repeat embeddings API calls)
_QUERY_VECTOR_CACHE: Dict[str, Any] = {}          # query_hash → np.ndarray
_FACTS_RESULT_CACHE: Dict[str, Tuple[List[str], float]] = {}  # cache_key → (results, ts)
_FACTS_CACHE_TTL: int = 600  # seconds (10 min)


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


def _fact_text(fact: Dict[str, Any]) -> str:
    inp = (fact.get("input") or "").strip()
    out = (fact.get("output") or "").strip()
    return (inp + " \n " + out).strip()


def _fact_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _load_embed_cache() -> dict:
    try:
        with open(_EMBED_CACHE_PATH, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def _save_embed_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(_EMBED_CACHE_PATH), exist_ok=True)
    with open(_EMBED_CACHE_PATH, "wb") as f:
        pickle.dump(cache, f)


def _ensure_openai_embeddings() -> None:
    """Build OpenAI embedding matrix for current memory, using disk cache for unchanged facts."""
    global _embed_vectors
    if _embed_vectors is not None:
        return
    if not memory:
        return
    api_key = CONFIG.get("openai_api_key", "")
    if not api_key:
        return
    try:
        import numpy as np
        import openai

        embed_model = CONFIG.get("openai_embed_model", "text-embedding-3-small")
        client = openai.OpenAI(api_key=api_key)

        texts = [_fact_text(f) for f in memory]
        hashes = [_fact_hash(t) for t in texts]
        cache = _load_embed_cache()

        to_embed = [(i, texts[i]) for i, h in enumerate(hashes) if h not in cache]
        if to_embed:
            batch_size = 100
            for start in range(0, len(to_embed), batch_size):
                batch = to_embed[start : start + batch_size]
                idxs, batch_texts = zip(*batch)
                resp = client.embeddings.create(model=embed_model, input=list(batch_texts))
                for j, emb in enumerate(resp.data):
                    cache[hashes[idxs[j]]] = np.array(emb.embedding, dtype=np.float32)
            _save_embed_cache(cache)
            print(f"[brain] Embedded {len(to_embed)} new facts (cache: {len(cache)} total).")

        _embed_vectors = np.array([cache[h] for h in hashes], dtype=np.float32)
        print(f"[brain] OpenAI embedding index ready — {len(memory)} facts, model={embed_model}.")
    except Exception as e:
        print(f"[brain] OpenAI embeddings failed, will fall back to TF-IDF: {e}")
        _embed_vectors = None


def _rebuild_index_memory() -> None:
    """Rebuild _index_memory from memory (curated facts only, no verbatim messages)."""
    global _index_memory, _tfidf_vectorizer, _tfidf_matrix
    with _index_lock:
        _index_memory = [
            f for f in memory
            if (f.get("_meta") or {}).get("source_type", "imported_fact")
            in _INDEX_SOURCE_TYPES
        ]
        _tfidf_vectorizer = None
        _tfidf_matrix = None


def load_facts(files: List[str] = None, user_scope: Optional[str] = None) -> int:
    """Load facts into memory. Returns count loaded into active retrieval memory."""
    global memory, _tfidf_vectorizer, _tfidf_matrix, _embed_vectors
    memory.clear()
    _tfidf_vectorizer = None
    _tfidf_matrix = None
    _embed_vectors = None

    if files is None:
        files = _default_files_for_user(user_scope or _primary_user())

    memory.extend(_load_fact_records(files))
    _rebuild_index_memory()

    # Pre-warm TF-IDF in background so first request doesn't stall.
    threading.Thread(target=_ensure_tfidf, daemon=True, name="tfidf-warmup").start()
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
        globals()["_embed_vectors"] = None
        _rebuild_index_memory()  # re-filters curated pool and clears TF-IDF
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
    """Build TF-IDF matrix over curated _index_memory only (not verbatim messages)."""
    global _tfidf_vectorizer, _tfidf_matrix
    if CONFIG.get("retrieval", "embed") != "embed":
        return
    with _index_lock:
        if _tfidf_vectorizer is not None and _tfidf_matrix is not None:
            return
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            texts = []
            for fact in _index_memory:
                inp = fact.get("input") or ""
                out = fact.get("output") or ""
                combined = (inp + " \n " + out).strip()
                texts.append(combined)
            if not texts:
                return
            # 10K features is ample for ~2K curated docs; was 80K causing 2s build
            _tfidf_vectorizer = TfidfVectorizer(max_features=10000, ngram_range=(1, 2))
            _tfidf_matrix = _tfidf_vectorizer.fit_transform(texts)
            print(f"[brain.py] TF-IDF index ready — {len(texts)} curated facts "
                  f"(skipped {len(memory) - len(texts)} verbatim messages).")
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


def _query_hash(input_str: str, k: int, user_scope: Optional[str]) -> str:
    key = f"{input_str.strip().lower()}|{k}|{user_scope or ''}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def get_facts(input_str: str, k: int = 12, user_scope: Optional[str] = None) -> List[str]:
    """Return up to k relevant snippets. Prefer OpenAI embeddings, then TF-IDF, then lexical.

    Results are cached in memory for _FACTS_CACHE_TTL seconds to avoid redundant
    embedding API calls for identical or near-identical queries.
    """
    # Check full-result cache first
    cache_key = _query_hash(input_str, k, user_scope)
    cached = _FACTS_RESULT_CACHE.get(cache_key)
    if cached is not None:
        results, ts = cached
        if time.time() - ts < _FACTS_CACHE_TTL:
            return results
        del _FACTS_RESULT_CACHE[cache_key]

    normalized_scope = _normalize_user_scope(user_scope)
    use_global_cache = not normalized_scope or normalized_scope == _primary_user()
    fact_pool = memory if use_global_cache else _load_fact_records(_default_files_for_user(normalized_scope))

    # Keep the curated TF-IDF pool aligned with in-memory facts when callers mutate
    # `memory` directly in tests or ad hoc scripts.
    if use_global_cache and memory:
        curated_count = sum(
            1
            for fact in memory
            if (fact.get("_meta") or {}).get("source_type", "imported_fact") in _INDEX_SOURCE_TYPES
        )
        if curated_count != len(_index_memory):
            _rebuild_index_memory()

    # Path 1: OpenAI semantic embeddings
    if use_global_cache and CONFIG.get("embed_backend") == "openai":
        _ensure_openai_embeddings()
        if _embed_vectors is not None:
            try:
                import numpy as np
                import openai

                embed_model = CONFIG.get("openai_embed_model", "text-embedding-3-small")

                # Cache the query vector itself to avoid repeat embedding API calls
                q_hash = hashlib.md5(input_str.strip().lower().encode()).hexdigest()
                if q_hash in _QUERY_VECTOR_CACHE:
                    q_vec = _QUERY_VECTOR_CACHE[q_hash]
                else:
                    client = openai.OpenAI(api_key=CONFIG["openai_api_key"])
                    resp = client.embeddings.create(model=embed_model, input=[input_str])
                    q_vec = np.array(resp.data[0].embedding, dtype=np.float32)
                    _QUERY_VECTOR_CACHE[q_hash] = q_vec

                norms = np.linalg.norm(_embed_vectors, axis=1)
                q_norm = np.linalg.norm(q_vec)
                sims = (_embed_vectors @ q_vec) / (norms * q_norm + 1e-9)
                ranked = sorted(enumerate(sims), key=lambda t: t[1], reverse=True)
                results: List[str] = []
                seen: set = set()
                for idx, score in ranked[: k * 3]:
                    if score < 0.1:
                        continue
                    snip = _format_snippet(memory[idx])
                    if not snip or snip in seen:
                        continue
                    seen.add(snip)
                    results.append(snip)
                    if len(results) >= k:
                        break
                if results:
                    _FACTS_RESULT_CACHE[cache_key] = (results, time.time())
                    return results
            except Exception as e:
                print(f"[brain] OpenAI embedding query failed, falling back: {e}")

    # Path 2: TF-IDF (queries over _index_memory — curated facts only)
    if use_global_cache:
        _ensure_tfidf()
    if use_global_cache and _tfidf_vectorizer is not None and _tfidf_matrix is not None:
        try:
            import numpy as np
            from sklearn.metrics.pairwise import cosine_similarity

            q = _tfidf_vectorizer.transform([input_str])
            sims = cosine_similarity(q, _tfidf_matrix).ravel()

            # Use argpartition for O(n) top-k selection instead of O(n log n) full sort
            n = len(sims)
            top_k = min(k * 3, n)
            if top_k < n:
                top_idx = np.argpartition(sims, -top_k)[-top_k:]
                top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]
            else:
                top_idx = np.argsort(sims)[::-1]

            results: List[str] = []
            seen = set()
            for idx in top_idx:
                score = sims[idx]
                if score <= 0:
                    continue
                snip = _format_snippet(_index_memory[idx])
                if not snip or snip in seen:
                    continue
                seen.add(snip)
                results.append(snip)
                if len(results) >= k:
                    break
            if results:
                _FACTS_RESULT_CACHE[cache_key] = (results, time.time())
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
    results = [snip for score, snip in scored[:k] if score > 0]
    if results:
        _FACTS_RESULT_CACHE[cache_key] = (results, time.time())
    return results


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
