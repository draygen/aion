"""Flask web server for Jarvis chat interface."""
import base64
import io
from collections import deque
from datetime import datetime

from flask import Flask, render_template, request, jsonify

from brain import get_facts
from config import CONFIG
from llm import ask_llm

app = Flask(__name__)

# Store recent chat logs (max 100 entries)
chat_logs = deque(maxlen=100)


def log_chat(ip: str, user_msg: str, assistant_msg: str):
    """Log a chat interaction."""
    chat_logs.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ip": ip,
        "user": user_msg,
        "assistant": assistant_msg,
    })


def build_web_prompt(user_text: str) -> str:
    """Build prompt for web visitors (not necessarily Brian)."""
    facts = get_facts(user_text, k=12)
    ctx_header = (
        "You are JARVIS, an AI assistant created by Brian (aka draygen).\n"
        "You're now publicly accessible, so you may be talking to Brian OR a visitor.\n"
        "If someone introduces themselves, remember their name for the conversation.\n"
        "If unsure who you're talking to, just be friendly - don't assume it's Brian.\n"
        "Style: informal, witty, direct, sometimes sarcastic but always friendly.\n"
        "Answer concisely (1-4 sentences).\n"
        "You can chat about anything. For questions about Brian, use the context if relevant.\n\n"
    )
    if facts:
        joined = "\n- ".join(facts)
        context_block = f"Context about Brian (use if relevant):\n- {joined}\n\n"
    else:
        context_block = ""

    return f"{ctx_header}{context_block}User: {user_text}\nAssistant:"


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

    try:
        prompt = build_web_prompt(user_message)
        response = ask_llm(prompt)
        response = response.strip() or "(no response)"

        # Log the interaction
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        log_chat(client_ip, user_message, response)

        result = {"response": response}

        # Generate TTS audio unless disabled
        tts_enabled = data.get("tts", True)
        if tts_enabled and response != "(no response)":
            try:
                result["audio"] = generate_tts_audio(response)
            except Exception:
                pass  # TTS failure shouldn't break the response

        return jsonify(result)
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


if __name__ == "__main__":
    print("Starting Jarvis web server...")
    print("LAN access: http://localhost:5000 or http://<your-local-ip>:5000")
    print("For WAN access, run: cloudflared tunnel --url http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
