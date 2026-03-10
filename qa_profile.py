"""
qa_profile.py — Full QA + performance profiling for Jarvis web server.

Phase 1: Integration tests via Flask test client (fast, deterministic)
Phase 2: End-to-end latency test via live HTTP + real LLM call timing
Phase 3: Internal profiling of the hot path (build_system_prompt → get_facts)

Run:  python3 qa_profile.py
"""

import cProfile
import io
import json
import os
import pstats
import sys
import tempfile
import threading
import time
import traceback
import unittest
from unittest.mock import patch

# ── helpers ──────────────────────────────────────────────────────────────────

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"
HDR  = "\033[1;94m"
RST  = "\033[0m"

results = []


def section(title):
    print(f"\n{HDR}{'═'*60}{RST}")
    print(f"{HDR}  {title}{RST}")
    print(f"{HDR}{'═'*60}{RST}")


def record(name, passed, duration_ms, note=""):
    icon = PASS if passed else FAIL
    dur = f"{duration_ms:7.1f}ms"
    flag = ""
    if duration_ms > 5000:
        flag = f" \033[91m[SLOW >5s]\033[0m"
    elif duration_ms > 2000:
        flag = f" \033[93m[SLOW >2s]\033[0m"
    elif duration_ms > 500:
        flag = f" \033[93m[>500ms]\033[0m"
    print(f"  {icon} {dur}  {name}{flag}")
    if note:
        print(f"          {note}")
    results.append({"name": name, "passed": passed, "ms": duration_ms, "note": note})


# ── setup ─────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import auth
from config import CONFIG

_TEMP = tempfile.TemporaryDirectory()
auth.DB_PATH = os.path.join(_TEMP.name, "jarvis-profile-test.db")
CONFIG["admin_password"] = "profiler2026!"
CONFIG["auto_extract_facts"] = False      # don't spin up background LLM calls
CONFIG["memory_enabled"] = False          # keep memory_store noise out
CONFIG["goals_enabled"] = False
auth.init_db()

from web import app  # calls init_db() again, which may re-set must_change_password

# Clear must_change_password AFTER web's init_db() runs
# (auth._mark_bootstrap_password_if_needed re-sets it when bootstrap password is detected)
_db = auth.get_db()
_db.execute("UPDATE users SET must_change_password = 0 WHERE username = 'brian'")
_db.commit()
_db.close()


def _login():
    c = app.test_client()
    r = c.post("/api/login", json={"username": "brian", "password": "profiler2026!"})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.data}"
    token = r.headers.get("Set-Cookie", "")
    # Extract token from cookie header
    for part in token.split(";"):
        part = part.strip()
        if part.startswith("jarvis_token="):
            return c, part.split("=", 1)[1]
    data = r.get_json()
    return c, None


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — Functional QA
# ═══════════════════════════════════════════════════════════════════════════════

section("PHASE 1 — Functional QA (Flask test client)")

client = app.test_client()

# 1. Login
t0 = time.perf_counter()
r = client.post("/api/login", json={"username": "brian", "password": "profiler2026!"})
record("POST /api/login", r.status_code == 200, (time.perf_counter() - t0) * 1000)

# Extract cookie
cookie_header = r.headers.get("Set-Cookie", "")
token_value = ""
for part in cookie_header.split(";"):
    part = part.strip()
    if part.startswith("jarvis_token="):
        token_value = part.split("=", 1)[1]
if not token_value:
    print(f"  {FAIL} Could not extract auth token — skipping authenticated tests")
    sys.exit(1)
client.set_cookie("jarvis_token", token_value)

# 2. Whoami
t0 = time.perf_counter()
r = client.get("/api/whoami")
record("GET /api/whoami", r.status_code == 200, (time.perf_counter() - t0) * 1000)

# 3. Chat — mocked LLM (pure server overhead)
with patch("web.ask_llm_chat", return_value="Hello, Brian."), \
     patch("web.get_facts", return_value=["Brian is the primary user."]):
    t0 = time.perf_counter()
    r = client.post("/api/chat", json={"message": "hello", "tts": False})
    chat_mock_ms = (time.perf_counter() - t0) * 1000
    note = ""
    if r.status_code != 200:
        try:
            note = f"HTTP {r.status_code}: {r.get_json()}"
        except Exception:
            note = f"HTTP {r.status_code}: {r.data[:200]}"
    record("POST /api/chat (mocked LLM)", r.status_code == 200, chat_mock_ms, note=note)
    if r.status_code == 200:
        body = r.get_json()
        has_session = "session" in body and "message_id" in body["session"]
        has_response = "response" in body
        record("  ↳ response envelope shape", has_session and has_response, 0,
               note=f"response={body.get('response','?')[:40]!r}")

# 4. Chat — real get_facts (measures TF-IDF overhead)
with patch("web.ask_llm_chat", return_value="Profiling answer."):
    t0 = time.perf_counter()
    r = client.post("/api/chat", json={"message": "who is Brian", "tts": False})
    chat_real_facts_ms = (time.perf_counter() - t0) * 1000
    record("POST /api/chat (real get_facts, mocked LLM)", r.status_code == 200,
           chat_real_facts_ms)

# 5. Second identical query (cache warm)
with patch("web.ask_llm_chat", return_value="Cached."):
    t0 = time.perf_counter()
    r = client.post("/api/chat", json={"message": "who is Brian", "tts": False})
    chat_cached_ms = (time.perf_counter() - t0) * 1000
    record("POST /api/chat (same query, cache warm)", r.status_code == 200,
           chat_cached_ms,
           note=f"speedup vs cold: {chat_real_facts_ms/max(chat_cached_ms,0.1):.1f}x")

# 6. Chat with TTS disabled vs default
with patch("web.ask_llm_chat", return_value="No TTS."):
    t0 = time.perf_counter()
    r = client.post("/api/chat", json={"message": "test tts off", "tts": False})
    record("POST /api/chat (tts=false)", r.status_code == 200,
           (time.perf_counter() - t0) * 1000)

# 7. Logout
t0 = time.perf_counter()
r = client.post("/api/logout")
record("POST /api/logout", r.status_code == 200, (time.perf_counter() - t0) * 1000)

# 8. Unauthenticated chat (should 401)
t0 = time.perf_counter()
r2 = app.test_client().post("/api/chat", json={"message": "sneak in", "tts": False})
record("POST /api/chat (no auth → 401)", r2.status_code == 401,
       (time.perf_counter() - t0) * 1000)

# 9. Empty message validation
client2 = app.test_client()
r3 = client2.post("/api/login", json={"username": "brian", "password": "profiler2026!"})
for part in r3.headers.get("Set-Cookie", "").split(";"):
    if part.strip().startswith("jarvis_token="):
        client2.set_cookie("jarvis_token", part.strip().split("=", 1)[1])
t0 = time.perf_counter()
r4 = client2.post("/api/chat", json={"message": "", "tts": False})
record("POST /api/chat (empty message → 400)", r4.status_code == 400,
       (time.perf_counter() - t0) * 1000)

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Internal Profiling: where does time actually go?
# ═══════════════════════════════════════════════════════════════════════════════

section("PHASE 2 — Internal Profiling (cProfile)")

import brain
from web import build_system_prompt

def _warm_tfidf():
    brain._tfidf_vectorizer = None
    brain._tfidf_matrix = None
    brain._ensure_tfidf()

# Profile TF-IDF build
print("\n  [cProfile] TF-IDF index build:")
pr = cProfile.Profile()
brain._tfidf_vectorizer = None
brain._tfidf_matrix = None
t0 = time.perf_counter()
pr.enable()
brain._ensure_tfidf()
pr.disable()
tfidf_build_ms = (time.perf_counter() - t0) * 1000
s = io.StringIO()
ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
ps.print_stats(15)
prof_output = s.getvalue()
record(f"TF-IDF build ({len(brain.memory)} facts)", True, tfidf_build_ms)

# Show top consumers from cProfile
print()
for line in prof_output.split("\n")[5:22]:
    if line.strip():
        print(f"    {line}")

# Profile get_facts cold
print("\n  [timing] get_facts() — cold (first call):")
brain._FACTS_RESULT_CACHE.clear()
t0 = time.perf_counter()
results_facts = brain.get_facts("who is Brian and what does he do", k=10)
get_facts_cold_ms = (time.perf_counter() - t0) * 1000
record("get_facts() cold call", True, get_facts_cold_ms,
       note=f"{len(results_facts)} snippets returned")

# Profile get_facts warm
t0 = time.perf_counter()
brain.get_facts("who is Brian and what does he do", k=10)
get_facts_warm_ms = (time.perf_counter() - t0) * 1000
record("get_facts() warm (cache hit)", True, get_facts_warm_ms,
       note=f"speedup: {get_facts_cold_ms/max(get_facts_warm_ms,0.01):.0f}x")

# Profile build_system_prompt
print("\n  [timing] build_system_prompt():")
pr2 = cProfile.Profile()
t0 = time.perf_counter()
pr2.enable()
sp = build_system_prompt("who is Brian", username="brian")
pr2.disable()
bsp_ms = (time.perf_counter() - t0) * 1000
record("build_system_prompt() (warm TF-IDF)", True, bsp_ms,
       note=f"prompt len={len(sp)} chars")
s2 = io.StringIO()
ps2 = pstats.Stats(pr2, stream=s2).sort_stats("cumulative")
ps2.print_stats(10)
for line in s2.getvalue().split("\n")[5:15]:
    if line.strip():
        print(f"    {line}")

# Profile build_system_prompt cold (TF-IDF not built)
brain._tfidf_vectorizer = None
brain._tfidf_matrix = None
brain._FACTS_RESULT_CACHE.clear()
t0 = time.perf_counter()
sp_cold = build_system_prompt("what are Brian's hobbies", username="brian")
bsp_cold_ms = (time.perf_counter() - t0) * 1000
record("build_system_prompt() (cold TF-IDF)", True, bsp_cold_ms)

# Memory breakdown
print("\n  [memory] Fact pool breakdown:")
msg_types = {}
for fact in brain.memory:
    st = (fact.get("_meta") or {}).get("source_type", "unknown")
    msg_types[st] = msg_types.get(st, 0) + 1
for k, v in sorted(msg_types.items(), key=lambda x: -x[1]):
    print(f"    {v:6d}  {k}")

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Per-request overhead breakdown
# ═══════════════════════════════════════════════════════════════════════════════

section("PHASE 3 — Per-request hot path breakdown")

def _time_fn(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return (time.perf_counter() - t0) * 1000, result

# Simulate a full request pipeline breakdown
from profile_builder import get_profile_summary
from brain import get_facts as gf

brain._FACTS_RESULT_CACHE.clear()
brain._ensure_tfidf()  # pre-warm

ms_profile, _ = _time_fn(get_profile_summary)
record("get_profile_summary()", True, ms_profile, note="profile.txt cache read")

ms_facts, snippets = _time_fn(gf, "what does Brian like to do", k=10, user_scope="brian")
record("get_facts() (warm TF-IDF, cold result cache)", True, ms_facts,
       note=f"{len(snippets)} results")

ms_facts2, _ = _time_fn(gf, "what does Brian like to do", k=10, user_scope="brian")
record("get_facts() (result cache hit)", True, ms_facts2)

from auth import get_db
def _load_history(uid=1, session_id="test:session"):
    db = get_db()
    rows = db.execute(
        "SELECT role, content FROM history WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT 40",
        (uid, session_id)
    ).fetchall()
    db.close()
    return rows

ms_hist, _ = _time_fn(_load_history)
record("load_user_history() (empty)", True, ms_hist)

print()

# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

section("SUMMARY")

passed = sum(1 for r in results if r["passed"])
failed = sum(1 for r in results if not r["passed"])
slow   = sum(1 for r in results if r["ms"] > 500)

print(f"\n  Tests: {passed} passed, {failed} failed, {slow} slow (>500ms)")
print(f"\n  Key timings:")
for name, ms in [
    ("TF-IDF build", tfidf_build_ms),
    ("get_facts() cold", get_facts_cold_ms),
    ("get_facts() warm", get_facts_warm_ms),
    ("build_system_prompt() cold", bsp_cold_ms),
    ("build_system_prompt() warm", bsp_ms),
    ("chat (mocked LLM)", chat_mock_ms),
    ("chat (real facts, mocked LLM)", chat_real_facts_ms),
    ("chat (cached query)", chat_cached_ms),
]:
    bar_len = min(int(ms / 50), 40)
    bar = "█" * bar_len
    flag = " ← BOTTLENECK" if ms > 2000 else (" ← slow" if ms > 500 else "")
    print(f"    {name:<35} {ms:8.1f}ms  {bar}{flag}")

print(f"\n  Fact pool: {len(brain.memory)} facts loaded")
print(f"  TF-IDF: max_features={brain._tfidf_vectorizer.max_features if brain._tfidf_vectorizer else 'N/A'}")

print("\n  Detected bottlenecks:")
bottlenecks = []

index_size = len(brain._index_memory) if hasattr(brain, "_index_memory") else len(brain.memory)
verbatim_count = sum(1 for f in brain.memory
                     if (f.get("_meta") or {}).get("source_type") == "verbatim_message")
if tfidf_build_ms > 1000:
    bottlenecks.append(f"[1] TF-IDF build still takes {tfidf_build_ms:.0f}ms "
                       f"— index has {index_size} docs")
if verbatim_count > 0 and index_size > len(brain.memory) - verbatim_count + 100:
    bottlenecks.append(f"[2] {verbatim_count} verbatim_message facts in TF-IDF pool "
                       f"— these inflate index with no retrieval benefit")
if get_facts_cold_ms > 200:
    bottlenecks.append(f"[3] get_facts() taking {get_facts_cold_ms:.0f}ms cold")

# Check if OpenAI client is being re-instantiated
import llm, inspect
src = inspect.getsource(llm._openai_chat)
if "openai.OpenAI(api_key=" in src:
    bottlenecks.append("[4] OpenAI client re-instantiated on every request — "
                       "no singleton/connection reuse")

if not bottlenecks:
    bottlenecks.append("No major bottlenecks detected.")

for b in bottlenecks:
    print(f"    \033[93m{b}\033[0m")

_TEMP.cleanup()

print()
sys.exit(0 if failed == 0 else 1)
