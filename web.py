"""Flask web server for Jarvis chat interface."""
import base64
import io
import json
import re
import secrets
import subprocess
from collections import defaultdict, deque
from datetime import datetime

from flask import Flask, render_template, request, jsonify, make_response
from flask_cors import CORS
from gtts import gTTS

from brain import get_facts
from config import CONFIG
from llm import ask_llm_chat

app = Flask(__name__)
CORS(app, origins="*")  # Allow Electron (file://) and web clients

# Per-session conversation history: session_id -> deque of {role, content} dicts
# Keep last 20 turns per session to stay within context limits
_sessions: dict = {}
_SESSION_TURNS = 20

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


def log_chat(ip: str, user_msg: str, assistant_msg: str):
    """Log a chat interaction."""
    chat_logs.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ip": ip,
        "user": user_msg,
        "assistant": assistant_msg,
    })


def run_nslookup(target: str) -> str:
    """Run nslookup on a domain or IP."""
    # Sanitize input - only allow alphanumeric, dots, and hyphens
    if not re.match(r'^[\w\.\-]+$', target):
        return "Invalid target"
    try:
        result = subprocess.run(
            ["nslookup", target],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout or result.stderr
    except Exception as e:
        return f"Error: {e}"


def run_whois(target: str) -> str:
    """Run whois on a domain or IP."""
    if not re.match(r'^[\w\.\-]+$', target):
        return "Invalid target"
    try:
        result = subprocess.run(
            ["whois", target],
            capture_output=True, text=True, timeout=15
        )
        # Truncate long whois output
        output = result.stdout or result.stderr
        if len(output) > 1500:
            output = output[:1500] + "\n... (truncated)"
        return output
    except Exception as e:
        return f"Error: {e}"


def handle_network_command(message: str, client_ip: str) -> str | None:
    """Check for network commands and handle them directly."""
    msg_lower = message.lower().strip()

    # "my ip" or "what's my ip"
    if any(p in msg_lower for p in ["my ip", "my public ip", "what is my ip", "whats my ip"]):
        return f"Your public IP address is: {client_ip}"

    # nslookup command
    nslookup_match = re.match(r'(?:nslookup|dns lookup|lookup)\s+(\S+)', msg_lower)
    if nslookup_match:
        target = nslookup_match.group(1)
        result = run_nslookup(target)
        return f"NSLookup for {target}:\n```\n{result}\n```"

    # whois command
    whois_match = re.match(r'whois\s+(\S+)', msg_lower)
    if whois_match:
        target = whois_match.group(1)
        result = run_whois(target)
        return f"WHOIS for {target}:\n```\n{result}\n```"

    return None


def build_system_prompt(user_text: str) -> str:
    """Build the system prompt, injecting relevant facts as context."""
    facts = get_facts(user_text, k=15)
    system = (
        "You are JARVIS, an AI assistant created by Brian Wallace (aka draygen).\n"
        "You are talking to Brian unless someone explicitly introduces themselves as someone else.\n"
        "Brian's wife is Jennifer (Jenn) Frotten Wallace.\n"
        "Style: informal, witty, direct, occasionally sarcastic but always loyal to Brian.\n"
        "Keep answers concise unless Brian asks for detail.\n\n"
        "CRITICAL RULES — treat these as hard constraints:\n"
        "1. For questions about real messages, conversations, or events: ONLY quote or reference "
        "content that appears VERBATIM in the Memory section below. Do NOT paraphrase or reconstruct.\n"
        "2. If Memory does not contain the answer, say: \"I don't have that in my memory.\"\n"
        "3. NEVER invent messages, dates, names, relationships, or events. Not even plausible ones.\n"
        "4. When showing messages, always include From:, To:, and Date: from the Memory entry.\n"
        "5. For general knowledge questions (not about Brian or real people), answer normally.\n"
    )
    if facts:
        joined = "\n---\n".join(facts)
        system += f"\nMemory (ONLY reference content that appears here):\n---\n{joined}\n---\n"
    return system


def generate_tts_elevenlabs(text: str) -> str:
    """Generate TTS using ElevenLabs API."""
    from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=CONFIG["elevenlabs_api_key"])
    voice_id = CONFIG.get("elevenlabs_voice_id", "pNInz6obpgDQGcFmaJgB")

    audio_generator = client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_turbo_v2_5",  # Fast, high quality
        output_format="mp3_44100_128",
    )

    # Collect audio chunks
    audio_buffer = io.BytesIO()
    for chunk in audio_generator:
        audio_buffer.write(chunk)
    audio_buffer.seek(0)

    return base64.b64encode(audio_buffer.read()).decode("utf-8")


def generate_tts_gtts(text: str) -> str:
    """Generate TTS using Google TTS (fallback)."""
    tts = gTTS(text=text, lang="en")
    audio_buffer = io.BytesIO()
    tts.write_to_fp(audio_buffer)
    audio_buffer.seek(0)
    return base64.b64encode(audio_buffer.read()).decode("utf-8")


def generate_tts_audio(text: str) -> str:
    """Generate TTS audio. Uses ElevenLabs if configured, else gTTS."""
    api_key = CONFIG.get("elevenlabs_api_key", "")
    if api_key:
        return generate_tts_elevenlabs(text)
    return generate_tts_gtts(text)


@app.route("/")
def index():
    """Serve the chat UI."""
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """Handle chat messages and return LLM responses."""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    user_message = data["message"].strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Get or create session ID
    session_id = request.cookies.get("jarvis_session")
    if not session_id or session_id not in _sessions:
        session_id = secrets.token_hex(16)
        _sessions[session_id] = deque(maxlen=_SESSION_TURNS * 2)

    history = _sessions[session_id]

    try:
        # Get client IP
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()

        # Check for network commands first (bypass LLM)
        network_response = handle_network_command(user_message, client_ip)
        if network_response:
            response = network_response
        else:
            # Build messages: system prompt (with fresh facts) + conversation history + new user message
            system_prompt = build_system_prompt(user_message)
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(list(history))
            messages.append({"role": "user", "content": user_message})

            response = ask_llm_chat(messages)
            response = response.strip() or "(no response)"

            # Store turns in history
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": response})

        # Log the interaction
        log_chat(client_ip, user_message, response)

        result = {"response": response}

        # Generate TTS audio unless disabled
        tts_enabled = data.get("tts", True)
        if tts_enabled and response != "(no response)":
            try:
                result["audio"] = generate_tts_audio(response)
            except Exception:
                pass  # TTS failure shouldn't break the response

        resp = make_response(jsonify(result))
        resp.set_cookie("jarvis_session", session_id, max_age=86400, samesite="Lax")
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/logs")
def logs():
    """View chat logs (protected by admin key)."""
    key = request.args.get("key", "")
    if key != CONFIG.get("admin_key", ""):
        return "Unauthorized", 401
    return render_template("logs.html")


@app.route("/api/logs")
def api_logs():
    """Get chat logs as JSON (protected by admin key)."""
    key = request.args.get("key", "")
    if key != CONFIG.get("admin_key", ""):
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(list(chat_logs))


@app.route("/api/memory/browse")
def memory_browse():
    """Return Jenn's message threads organized by category."""
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
    """Return individual messages for a thread."""
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
                        continue  # skip window chunks

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


if __name__ == "__main__":
    print("Starting Jarvis web server...")
    print("LAN access: http://localhost:5000 or http://<your-local-ip>:5000")
    print("For WAN access, run: cloudflared tunnel --url http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
