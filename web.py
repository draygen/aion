"""Flask web server for Aion chat interface."""
import base64
import io
import json
import re
import urllib.request
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from flask import Flask, g, redirect, render_template, request, jsonify, make_response
from gtts import gTTS

try:
    from flask_cors import CORS
except ImportError:  # pragma: no cover - test/dev fallback when CORS extras are missing
    def CORS(app, *args, **kwargs):
        return app

import auth
import vast
from auth import (
    init_db, login_required, admin_required, vast_required,
    verify_login, create_token, delete_token,
    create_user, delete_user, get_db, get_user_by_token, change_password,
)
from brain import get_facts, add_fact
from config import CONFIG

# Memory / Goals (Phase 1 — optional, graceful fallback)
try:
    from memory_store import _save_memory, _search_memory
    from goals_store import _list_goals
    _MEMORY_AVAILABLE = True
except ImportError:
    _MEMORY_AVAILABLE = False
from events import list_events, log_event
from extractor import extract_and_save
from llm import ask_llm_chat
from profile_builder import get_profile_summary, build_profile_summary, invalidate_cache as invalidate_profile_cache
from tools import available_tool_status, dispatch_tool_message, handle_ops_command

app = Flask(__name__)
CORS(app, origins=CONFIG.get("cors_origins"), supports_credentials=True)

# Initialize DB (creates tables + Brian's account + migrates facts)
init_db()

# Store recent chat logs (max 100 entries)
chat_logs = deque(maxlen=100)

# Memory browser constants
_JENN_MSGS_FILE = 'data/jenn_messages.jsonl'
_MEMORY_CATEGORIES = {
    'Birth & Pregnancy': ['pregnant', 'pregnancy', 'baby', 'birth', 'newborn', 'expecting', 'due date'],
    'Love & Relationships': ['married', 'wedding', 'divorce', 'engaged', 'boyfriend', 'girlfriend', 'broke up', 'breakup', 'cheating'],
    'Family & Parenting': ['custody', 'dcf', 'child support', 'sole custody', 'visitation', 'foster'],
    'Health & Wellbeing': ['sick', 'hospital', 'surgery', 'cancer', 'mental health', 'therapy', 'depression', 'anxiety', 'self harm', 'self-harm', 'cutting'],
    'Loss & Grief': ['died', 'death', 'passed away', 'funeral', 'grief', 'rest in peace', 'rip'],
    'Major Life Events': ['moved', 'new apartment', 'new house', 'new job', 'fired', 'arrested', 'jail', 'graduated', 'graduation'],
}
_mem_browse_cache = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _should_use_secure_cookie() -> bool:
    if CONFIG.get("cookie_secure"):
        return True
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
    return "https" in forwarded_proto.lower()


def _authenticate_request():
    token = request.cookies.get("aion_token")
    if not token:
        return jsonify({"error": "Unauthorized", "login_required": True}), 401
    user = get_user_by_token(token)
    if not user:
        return jsonify({"error": "Unauthorized", "login_required": True}), 401
    g.user = user
    return None


def log_chat(ip: str, user_msg: str, assistant_msg: str):
    chat_logs.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ip": ip,
        "user": user_msg,
        "assistant": assistant_msg,
    })


def handle_network_command(message: str, client_ip: str) -> str | None:
    execution = dispatch_tool_message(message, client_ip)
    if not execution:
        return None
    return execution.output


_SYSTEM_STATIC_HEADER = """\
You are AION, an AI assistant created by Brian Wallace (aka draygen).
Style: informal, witty, direct, occasionally sarcastic but always loyal to Brian.
Keep answers concise unless Brian asks for detail.

CRITICAL RULES — treat these as hard constraints:
1. For questions about real messages, conversations, or events: ONLY quote or reference \
content that appears VERBATIM in the Memory section below. Do NOT paraphrase or reconstruct.
2. If Memory does not contain the answer, say: "I don't have that in my memory."
3. NEVER invent messages, dates, names, relationships, or events. Not even plausible ones.
4. When showing messages, always include From:, To:, and Date: from the Memory entry.
5. For general knowledge questions (not about Brian or real people), answer normally.
6. For infrastructure checks, only use the explicit built-in ops commands on authorized targets.
"""


def build_system_prompt(user_text: str, username: str = "brian") -> str:
    # Static prefix — identical on every Brian request, enabling OpenAI prompt caching
    if username.lower() == "brian":
        identity_line = "You are talking to Brian unless someone explicitly introduces themselves as someone else."
    else:
        identity_line = f"You are talking to {username}."

    profile = get_profile_summary()
    profile_section = f"\n## Who Brian Is\n{profile}\n" if profile else ""

    system = _SYSTEM_STATIC_HEADER + identity_line + "\n" + profile_section

    # Dynamic suffix — query-specific retrieved facts (changes per request, not cached)
    facts = get_facts(user_text, k=15, user_scope=username)
    if facts:
        joined = "\n---\n".join(facts)
        system += f"\n## Relevant Memory for this query\n---\n{joined}\n---\n"

    # Semantic memories from memory_store (Phase 1)
    if _MEMORY_AVAILABLE and CONFIG.get("memory_enabled", True):
        try:
            msg, ok = _search_memory(user_text, limit=6)
            if ok and not msg.startswith("No memories found"):
                system += f"\n## Semantic Memories\n{msg}\n"
        except Exception:
            pass

    # Active goals (Phase 1)
    if _MEMORY_AVAILABLE and CONFIG.get("goals_enabled", True):
        try:
            msg, ok = _list_goals(status="active")
            if ok and "No goals" not in msg:
                system += f"\n## Brian's Active Goals\n{msg}\n"
        except Exception:
            pass

    return system


def _normalize_envelope_value(value: str | None, default: str, max_len: int = 120) -> str:
    text = (value or "").strip()
    if not text:
        return default
    sanitized = re.sub(r"[^a-zA-Z0-9._:/@-]+", "_", text)
    return sanitized[:max_len] or default


def _build_chat_envelope(data: dict, user_id: int, username: str) -> dict:
    channel = _normalize_envelope_value(data.get("channel"), "web", max_len=40)
    thread_default = f"{channel}:{username or user_id}"
    thread_id = _normalize_envelope_value(data.get("thread_id"), thread_default, max_len=120)
    session_default = f"{channel}:{thread_id}"
    session_id = _normalize_envelope_value(data.get("session_id"), session_default, max_len=160)
    request_message_id = _normalize_envelope_value(
        data.get("message_id"),
        f"msg-{uuid.uuid4().hex}",
        max_len=160,
    )
    response_message_id = f"msg-{uuid.uuid4().hex}"
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "channel": channel,
        "thread_id": thread_id,
        "session_id": session_id,
        "request_message_id": request_message_id,
        "response_message_id": response_message_id,
        "metadata": metadata,
    }


def _load_user_history(user_id: int, session_id: str | None = None) -> list:
    db = get_db()
    if session_id:
        rows = db.execute(
            "SELECT role, content FROM history WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT 40",
            (user_id, session_id),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT role, content FROM history WHERE user_id=? ORDER BY id DESC LIMIT 40",
            (user_id,),
        ).fetchall()
    db.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def _save_history_turns(
    user_id: int,
    user_msg: str,
    assistant_msg: str,
    *,
    session_id: str | None = None,
    channel: str | None = None,
    thread_id: str | None = None,
    user_message_id: str | None = None,
    assistant_message_id: str | None = None,
):
    db = get_db()
    ts = _utc_now_iso()
    db.execute(
        """
        INSERT INTO history (user_id, role, content, ts, session_id, channel, thread_id, message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, "user", user_msg, ts, session_id, channel, thread_id, user_message_id),
    )
    db.execute(
        """
        INSERT INTO history (user_id, role, content, ts, session_id, channel, thread_id, message_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, "assistant", assistant_msg, ts, session_id, channel, thread_id, assistant_message_id),
    )
    db.commit()
    db.close()


def generate_tts_elevenlabs(text: str) -> str:
    from elevenlabs import ElevenLabs
    client = ElevenLabs(api_key=CONFIG["elevenlabs_api_key"])
    voice_id = CONFIG.get("elevenlabs_voice_id", "pNInz6obpgDQGcFmaJgB")
    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_turbo_v2_5",
        output_format="mp3_44100_128",
    )
    audio_buffer = io.BytesIO()
    for chunk in audio_generator:
        audio_buffer.write(chunk)
    audio_buffer.seek(0)
    return base64.b64encode(audio_buffer.read()).decode("utf-8")


def generate_tts_gtts(text: str) -> str:
    tts = gTTS(text=text, lang="en")
    audio_buffer = io.BytesIO()
    tts.write_to_fp(audio_buffer)
    audio_buffer.seek(0)
    return base64.b64encode(audio_buffer.read()).decode("utf-8")


def generate_tts_audio(text: str) -> str:
    api_key = CONFIG.get("elevenlabs_api_key", "")
    if api_key:
        return generate_tts_elevenlabs(text)
    return generate_tts_gtts(text)


# ── Auth endpoints ──────────────────────────────────────────────────────────

@app.route("/api/system/public/health")
def api_system_public_health():
    return jsonify({
        "ok": True,
        "service": "aion",
        "time": _utc_now_iso(),
    })

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400
    user = verify_login(username, password)
    if not user:
        return jsonify({"error": "Invalid username or password"}), 401
    token = create_token(user["id"])
    resp = make_response(jsonify({
        "ok": True,
        "username": user["username"],
        "role": user["role"],
        "requires_password_change": bool(user.get("must_change_password")),
    }))
    resp.set_cookie(
        "aion_token",
        token,
        max_age=86400 * 30,
        samesite=CONFIG.get("cookie_samesite", "Lax"),
        httponly=True,
        secure=_should_use_secure_cookie(),
    )
    return resp


@app.route("/api/change-password", methods=["POST"])
@login_required
def api_change_password():
    data = request.get_json() or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    err = change_password(g.user["id"], current_password, new_password)
    if err:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    token = request.cookies.get("aion_token")
    if token:
        delete_token(token)
    resp = make_response(jsonify({"ok": True}))
    resp.delete_cookie("aion_token")
    return resp


@app.route("/api/whoami")
@login_required
def api_whoami():
    return jsonify({
        "username": g.user["username"],
        "role": g.user["role"],
        "requires_password_change": bool(g.user.get("must_change_password")),
    })


@app.route("/api/sso", methods=["POST"])
def api_sso():
    """Exchange a Drayhub SSO token for a Aion session cookie."""
    data = request.get_json() or {}
    sso_token = data.get("token", "").strip()
    if not sso_token:
        return jsonify({"error": "Missing token"}), 400

    drayhub_api = CONFIG.get("drayhub_api", "http://127.0.0.1:8888")
    try:
        body = json.dumps({"token": sso_token, "service": "aion"}).encode()
        req = urllib.request.Request(
            f"{drayhub_api}/api/public/auth/sso-validate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode())
    except Exception:
        return jsonify({"error": "SSO validation failed"}), 502

    if not result.get("valid"):
        return jsonify({"error": "Invalid SSO token"}), 401

    username = result.get("username", "").strip().lower()
    roles = result.get("roles", [])
    if not username:
        return jsonify({"error": "No username in SSO response"}), 401

    # Map drayhub roles to aion role
    roles_lower = [r.lower() for r in roles]
    if any(r in ("role_admin", "role_superuser") for r in roles_lower):
        role = "admin"
    elif "vast" in roles_lower:
        role = "vast"
    else:
        role = "user"

    # Find or create Aion user
    import secrets as _secrets
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    db.close()

    if row:
        user_id = row["id"]
    else:
        dummy_pass = _secrets.token_hex(32)
        user_id = create_user(username, dummy_pass, role=role, must_change_password=False)

    token = create_token(user_id)
    db = get_db()
    user = dict(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    db.close()

    resp = make_response(jsonify({
        "ok": True,
        "username": user["username"],
        "role": user["role"],
    }))
    resp.set_cookie(
        "aion_token",
        token,
        max_age=86400 * 30,
        samesite=CONFIG.get("cookie_samesite", "Lax"),
        httponly=True,
        secure=_should_use_secure_cookie(),
    )
    return resp


@app.route("/api/admin/users")
@admin_required
def api_admin_list_users():
    db = get_db()
    rows = db.execute("SELECT id, username, role, must_change_password, created FROM users ORDER BY id").fetchall()
    db.close()
    return jsonify({"users": [dict(r) for r in rows]})


@app.route("/api/admin/users", methods=["POST"])
@admin_required
def api_admin_create_user():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    must_change_password = data.get("must_change_password", True)
    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400
    if role not in ("user", "admin", "vast"):
        return jsonify({"error": "Invalid role"}), 400
    try:
        user_id = create_user(username, password, role, must_change_password=bool(must_change_password))
        return jsonify({"ok": True, "id": user_id, "username": username, "role": role, "must_change_password": bool(must_change_password)})
    except Exception as e:
        return jsonify({"error": str(e)}), 409


@app.route("/api/admin/users/<int:user_id>/role", methods=["PATCH"])
@admin_required
def api_admin_update_role(user_id):
    data = request.get_json() or {}
    role = data.get("role", "").strip()
    if role not in ("user", "admin", "vast"):
        return jsonify({"error": "Invalid role. Must be user, admin, or vast."}), 400
    db = get_db()
    row = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "User not found"}), 404
    db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    db.commit()
    db.close()
    return jsonify({"ok": True, "id": user_id, "role": role})


@app.route("/api/admin/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def api_admin_reset_password(user_id):
    data = request.get_json() or {}
    new_password = data.get("password", "")
    if len(new_password) < 10:
        return jsonify({"error": "Password must be at least 10 characters."}), 400
    import bcrypt as _bcrypt
    pw_hash = _bcrypt.hashpw(new_password.encode(), _bcrypt.gensalt()).decode()
    db = get_db()
    row = db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "User not found"}), 404
    db.execute("UPDATE users SET pw_hash = ?, must_change_password = 1 WHERE id = ?", (pw_hash, user_id))
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/admin/network/config")
@admin_required
def api_admin_network_config():
    return jsonify({
        "network_ops_enabled": bool(CONFIG.get("network_ops_enabled", True)),
        "authorized_network_targets": list(CONFIG.get("authorized_network_targets") or []),
        "available_tools": available_tool_status(),
    })


@app.route("/api/admin/network/config", methods=["POST"])
@admin_required
def api_admin_network_config_update():
    data = request.get_json() or {}
    targets = data.get("authorized_network_targets")
    if targets is None:
        return jsonify({"error": "Missing authorized_network_targets"}), 400
    if not isinstance(targets, list):
        return jsonify({"error": "authorized_network_targets must be a list"}), 400
    cleaned = []
    for value in targets:
        if not isinstance(value, str):
            return jsonify({"error": "All targets must be strings"}), 400
        item = value.strip()
        if item:
            cleaned.append(item)
    CONFIG["authorized_network_targets"] = cleaned
    if "network_ops_enabled" in data:
        CONFIG["network_ops_enabled"] = bool(data.get("network_ops_enabled"))
    return jsonify({
        "ok": True,
        "authorized_network_targets": list(CONFIG["authorized_network_targets"]),
        "network_ops_enabled": bool(CONFIG.get("network_ops_enabled", True)),
        "available_tools": available_tool_status(),
    })


@app.route("/api/admin/network/run", methods=["POST"])
@admin_required
def api_admin_network_run():
    data = request.get_json() or {}
    command = (data.get("command") or "").strip()
    if not command:
        return jsonify({"error": "Missing command"}), 400
    result = handle_ops_command(command, request.remote_addr or "")
    if result is None:
        return jsonify({"error": "Unsupported command"}), 400
    return jsonify({"ok": True, "result": result})


@app.route("/api/admin/profile/rebuild", methods=["POST"])
@admin_required
def api_admin_profile_rebuild():
    try:
        invalidate_profile_cache()
        summary = build_profile_summary(save=True)
        if not summary:
            return jsonify({"error": "No source facts found"}), 400
        return jsonify({"ok": True, "chars": len(summary), "preview": summary[:300] + "..."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/events")
@admin_required
def api_admin_events():
    raw_limit = request.args.get("limit", "50")
    try:
        limit = int(raw_limit)
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    session_id = (request.args.get("session_id") or "").strip() or None
    user_id = request.args.get("user_id")
    if user_id not in (None, ""):
        try:
            user_id = int(user_id)
        except ValueError:
            return jsonify({"error": "user_id must be an integer"}), 400
    else:
        user_id = None
    return jsonify({"events": list_events(user_id=user_id, session_id=session_id, limit=limit)})


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
@admin_required
def api_admin_delete_user(user_id):
    if user_id == g.user["id"]:
        return jsonify({"error": "Cannot delete yourself"}), 400
    delete_user(user_id)
    return jsonify({"ok": True})


# ── Main routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"].strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    user_id = g.user["id"]
    username = g.user["username"]
    envelope = _build_chat_envelope(data, user_id, username)

    try:
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()

        log_event(
            user_id=user_id,
            session_id=envelope["session_id"],
            channel=envelope["channel"],
            thread_id=envelope["thread_id"],
            message_id=envelope["request_message_id"],
            event_type="user_message_received",
            source="chat_api",
            content=user_message,
            payload={"metadata": envelope["metadata"]},
        )

        # Explicit remember shortcut — no LLM needed
        if user_message.lower().startswith("remember:"):
            fact_text = user_message[len("remember:"):].strip()
            if fact_text:
                add_fact(None, fact_text, user_scope=username)
                response = f"Got it. I'll remember: {fact_text}"
                log_event(
                    user_id=user_id,
                    session_id=envelope["session_id"],
                    channel=envelope["channel"],
                    thread_id=envelope["thread_id"],
                    message_id=envelope["request_message_id"],
                    event_type="memory_written",
                    source="remember_shortcut",
                    content=fact_text,
                    payload={"destination": "user_memory"},
                )

        # Network commands bypass LLM
        if not user_message.lower().startswith("remember:"):
            tool_execution = dispatch_tool_message(user_message, client_ip)
        else:
            tool_execution = None

        if "response" not in locals() and tool_execution:
            log_event(
                user_id=user_id,
                session_id=envelope["session_id"],
                channel=envelope["channel"],
                thread_id=envelope["thread_id"],
                message_id=envelope["request_message_id"],
                event_type="tool_invoked",
                source="tool_registry",
                tool_name=tool_execution.tool_id,
                content=user_message,
                payload={"args": tool_execution.args},
            )
            response = tool_execution.output
            log_event(
                user_id=user_id,
                session_id=envelope["session_id"],
                channel=envelope["channel"],
                thread_id=envelope["thread_id"],
                message_id=envelope["response_message_id"],
                event_type="tool_result",
                source="tool_registry",
                tool_name=tool_execution.tool_id,
                content=response,
                payload={"args": tool_execution.args},
            )
        elif "response" not in locals():
            history = _load_user_history(user_id, session_id=envelope["session_id"])
            system_prompt = build_system_prompt(user_message, username)
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(history)
            messages.append({"role": "user", "content": user_message})

            response = ask_llm_chat(messages)
            response = response.strip() or "(no response)"

            if CONFIG.get("auto_extract_facts", True):
                extract_and_save(user_message, response, username, user_scope=username)

        _save_history_turns(
            user_id,
            user_message,
            response,
            session_id=envelope["session_id"],
            channel=envelope["channel"],
            thread_id=envelope["thread_id"],
            user_message_id=envelope["request_message_id"],
            assistant_message_id=envelope["response_message_id"],
        )
        log_chat(client_ip, user_message, response)
        log_event(
            user_id=user_id,
            session_id=envelope["session_id"],
            channel=envelope["channel"],
            thread_id=envelope["thread_id"],
            message_id=envelope["response_message_id"],
            event_type="assistant_message_sent",
            source="chat_api",
            content=response,
            payload={"request_message_id": envelope["request_message_id"]},
        )

        result = {
            "response": response,
            "session": {
                "channel": envelope["channel"],
                "thread_id": envelope["thread_id"],
                "session_id": envelope["session_id"],
                "message_id": envelope["response_message_id"],
                "reply_to": envelope["request_message_id"],
            },
        }

        tts_enabled = data.get("tts", True)
        if tts_enabled and response != "(no response)":
            try:
                result["audio"] = generate_tts_audio(response)
            except Exception:
                pass

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/logs")
def logs():
    key = request.args.get("key", "")
    if key != CONFIG.get("admin_key", ""):
        return "Unauthorized", 401
    return render_template("logs.html")


@app.route("/api/logs")
def api_logs():
    key = request.args.get("key", "")
    if key != CONFIG.get("admin_key", ""):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(list(chat_logs))


@app.route("/api/memory/browse")
def memory_browse():
    if CONFIG.get("memory_browser_requires_auth", True):
        auth_error = _authenticate_request()
        if auth_error:
            return auth_error

    global _mem_browse_cache
    if _mem_browse_cache:
        return jsonify({'categories': _mem_browse_cache})

    threads = {}
    thread_text = defaultdict(list)

    try:
        with open(_JENN_MSGS_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    tid = obj.get('thread_id', '')
                    if not tid:
                        continue
                    ts_s = obj.get('ts_start') or 0
                    ts_e = obj.get('ts_end') or 0

                    if tid not in threads:
                        threads[tid] = {
                            'thread_id': tid,
                            'display': obj.get('thread') or tid,
                            'ts_start': ts_s,
                            'ts_end': ts_e,
                            'msg_count': 0,
                        }
                    else:
                        t = threads[tid]
                        if ts_s and ts_s < t['ts_start']:
                            t['ts_start'] = ts_s
                        if ts_e and ts_e > t['ts_end']:
                            t['ts_end'] = ts_e

                    is_chunk = obj.get('output', '').startswith('Thread: ')
                    if is_chunk:
                        if len(thread_text[tid]) < 4:
                            thread_text[tid].append(obj.get('output', ''))
                    else:
                        threads[tid]['msg_count'] += 1
                except Exception:
                    continue
    except FileNotFoundError:
        return jsonify({'categories': {}})

    categorized = defaultdict(list)
    for tid, info in threads.items():
        sample = ' '.join(thread_text.get(tid, [])).lower()
        cats = [c for c, kws in _MEMORY_CATEGORIES.items() if any(kw in sample for kw in kws)]
        for cat in (cats or ['General']):
            categorized[cat].append(info)

    result = {cat: sorted(lst, key=lambda x: x['ts_start']) for cat, lst in categorized.items()}
    _mem_browse_cache = result
    return jsonify({'categories': result})


@app.route("/api/memory/thread/<thread_id>")
def memory_thread_detail(thread_id):
    if CONFIG.get("memory_browser_requires_auth", True):
        auth_error = _authenticate_request()
        if auth_error:
            return auth_error

    if not re.match(r'^\w+$', thread_id):
        return jsonify({'error': 'Invalid thread_id'}), 400

    messages = []
    try:
        with open(_JENN_MSGS_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get('thread_id') != thread_id:
                        continue
                    if obj.get('output', '').startswith('Thread: '):
                        continue

                    output = obj.get('output', '')
                    nl = output.find('\n')
                    if nl < 0:
                        continue
                    header = output[:nl]
                    rest = output[nl + 1:].strip()
                    if rest.startswith('"'):
                        rest = rest[1:]
                    if rest.endswith('"'):
                        rest = rest[:-1]

                    m = re.match(r'\[([^\]]+)\] From: (.+?) → To: (.+?)(?:\s+\[(.+?)\])?$', header)
                    if not m:
                        continue

                    messages.append({
                        'ts': obj.get('ts_start') or 0,
                        'timestamp': m.group(1),
                        'sender': m.group(2).strip(),
                        'recipient': m.group(3).strip(),
                        'note': m.group(4) or '',
                        'content': rest,
                        'post_death': bool(obj.get('post_death')),
                    })
                except Exception:
                    continue
    except FileNotFoundError:
        return jsonify({'error': 'Data not found'}), 404

    if not messages:
        return jsonify({'error': 'Thread not found'}), 404

    messages.sort(key=lambda x: x['ts'])
    return jsonify({'thread_id': thread_id, 'messages': messages})


# ── Vast.ai admin routes ────────────────────────────────────────────────────

@app.route("/admin")
def admin_panel():
    token = request.cookies.get("aion_token")
    if not token:
        return redirect("/")
    user = get_user_by_token(token)
    if not user or user["role"] != "admin":
        return "Forbidden", 403
    return render_template("admin.html")


@app.route("/api/admin/vast/offers")
@vast_required
def api_vast_offers():
    try:
        max_dph = request.args.get("max_dph")
        min_gpu_ram = request.args.get("min_gpu_ram")
        gpu_name = request.args.get("gpu_name")
        offers = vast.search_offers(
            max_dph=float(max_dph) if max_dph else None,
            min_gpu_ram_gb=float(min_gpu_ram) if min_gpu_ram else None,
            gpu_name=gpu_name or None,
        )
        return jsonify({"offers": offers})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/vast/instances")
@vast_required
def api_vast_instances():
    try:
        instances = vast.get_instances()
        return jsonify({"instances": instances})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/vast/instances/<int:instance_id>")
@vast_required
def api_vast_instance(instance_id):
    try:
        instance = vast.get_instance(instance_id)
        return jsonify({"instance": instance})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/vast/deploy", methods=["POST"])
@vast_required
def api_vast_deploy():
    data = request.get_json() or {}
    offer_id = data.get("offer_id")
    disk_gb = int(data.get("disk_gb", 40))
    if not offer_id:
        return jsonify({"error": "Missing offer_id"}), 400
    try:
        result = vast.deploy_on_offer(int(offer_id), disk_gb=disk_gb)
        return jsonify({"ok": True, "result": result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/vast/instances/<int:instance_id>/stop", methods=["POST"])
@vast_required
def api_vast_stop(instance_id):
    try:
        result = vast.stop_instance(instance_id)
        return jsonify({"ok": True, "result": result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/vast/instances/<int:instance_id>/start", methods=["POST"])
@vast_required
def api_vast_start(instance_id):
    try:
        result = vast.start_instance(instance_id)
        return jsonify({"ok": True, "result": result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/vast/instances/<int:instance_id>/restart", methods=["POST"])
@vast_required
def api_vast_restart(instance_id):
    try:
        result = vast.restart_instance(instance_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/vast/instances/<int:instance_id>", methods=["DELETE"])
@vast_required
def api_vast_destroy(instance_id):
    try:
        result = vast.destroy_instance(instance_id)
        return jsonify({"ok": True, "result": result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/vast/instances/<int:instance_id>/redeploy", methods=["POST"])
@vast_required
def api_vast_redeploy(instance_id):
    data = request.get_json() or {}
    ssh_host = data.get("ssh_host")
    ssh_port = data.get("ssh_port")
    if not ssh_host or not ssh_port:
        return jsonify({"error": "Missing ssh_host or ssh_port"}), 400
    try:
        result = vast.redeploy_code(ssh_host, int(ssh_port))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Starting Aion web server...")
    print("LAN access: http://localhost:5000 or http://<your-local-ip>:5000")
    print("For WAN access, run: cloudflared tunnel --url http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
