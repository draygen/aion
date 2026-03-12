import sys
import os
import time
import logging
from typing import Optional
from gtts import gTTS

from config import CONFIG
from commands import process_input, parse_command, help_text
from brain import get_fact, get_facts, recall, load_facts, add_fact
from llm import ask_llm

# Memory / Goals (Phase 1 — optional, graceful fallback if not installed)
try:
    from memory_store import _save_memory, _search_memory, _get_recent_memories, _delete_memory
    from goals_store import _create_goal, _list_goals, _update_goal
    _MEMORY_AVAILABLE = True
except ImportError:
    _MEMORY_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Default hides DEBUG
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger("aion")

# Respect CONFIG["DEBUG"]
if CONFIG.get("DEBUG"):
    logger.setLevel(logging.DEBUG)

# Keep the last retrieved snippets for /why
_last_snippets = []


def speak(text):
    logger.debug("speak() called with text: %s...", text[:50])
    try:
        logger.debug("Attempting to create gTTS object...")
        tts = gTTS(text=text, lang="en")
        audio_file = "temp_response.mp3"
        tts.save(audio_file)
        logger.debug("Audio file saved: %s. Attempting to play...", audio_file)

        if sys.platform == "darwin":  # macOS
            os.system(f"afplay {audio_file}")
        elif sys.platform == "win32":  # Windows
            os.system(f"start {audio_file}")
            time.sleep(2)
        else:  # Linux
            os.system(f"mpg123 {audio_file}")

        os.remove(audio_file)
        logger.debug("Audio playback attempted and file removed.")
    except Exception as e:
        print(f"Aion (TTS error): Could not generate or play speech: {e}")
        import traceback
        traceback.print_exc()


def build_prompt(user_text: str) -> str:
    """Build a conversational prompt with multiple retrieved facts.
    Store snippets for /why.
    """
    global _last_snippets
    facts = get_facts(user_text, k=12)
    _last_snippets = facts or []
    ctx_header = (
        "You are AION, Brian's personal AI assistant. Address him as Brian (draygen).\n"
        "Style: informal, opinionated, extremely direct, sometimes sarcastic/humorous.\n"
        "Answer concisely (1-4 sentences).\n"
        "Use ONLY the context snippets if they are relevant. If the answer is not in context, say: I don't know.\n\n"
    )
    if facts:
        joined = "\n- ".join(facts)
        context_block = f"Context (up to 12 snippets):\n- {joined}\n\n"
    else:
        context_block = ""

    # Inject semantic memories if available
    mem_block = ""
    if _MEMORY_AVAILABLE and CONFIG.get("memory_enabled", True):
        try:
            msg, ok = _search_memory(user_text, limit=5)
            if ok and not msg.startswith("No memories found"):
                mem_block = f"Remembered facts:\n{msg}\n\n"
        except Exception:
            pass

    return f"{ctx_header}{context_block}{mem_block}User: {user_text}\nAssistant:"


def handle_set(args: str) -> str:
    """Handle /set key=value updates for runtime CONFIG."""
    if not args or "=" not in args:
        return "Usage: /set key=value (e.g., /set model=mistral)"
    key, value = [p.strip() for p in args.split("=", 1)]
    if not key:
        return "Invalid key."
    CONFIG[key] = value
    if key.lower() == "debug":
        logger.setLevel(logging.DEBUG if value.lower() == "true" else logging.INFO)
    return f"Set {key} = {value}"


def main() -> int:
    print("Aion is online. Type /help for commands. Type 'exit' to quit.")

    # Ask about TTS at startup
    initial_tts_choice = input("Enable Text-to-Speech (y/n)? [y]: ").strip().lower()
    if initial_tts_choice == "n":
        CONFIG["TTS_ENABLED"] = False
        print("Text-to-Speech is OFF.")
    else:
        CONFIG["TTS_ENABLED"] = True
        print("Text-to-Speech is ON.")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        # Command handling
        cmd = parse_command(user_input)
        if cmd:
            name, args = cmd
            if name == "exit":
                print("Aion: Goodbye.")
                sys.exit(0)
            elif name == "help":
                print(help_text())
                continue
            elif name == "set":
                print(handle_set(args))
                continue
            elif name == "recall":
                print(recall())
                continue
            elif name == "reload":
                count = load_facts()
                print(f"Reloaded {count} facts from configured sources")
                continue
            elif name == "note":
                text = (args or "").strip()
                if not text:
                    print("Usage: /note some fact about Brian")
                else:
                    print(add_fact(None, text))
                continue
            elif name == "teach":
                payload = (args or "")
                if ">=" not in payload:
                    print("Usage: /teach question => answer")
                else:
                    q, a = [p.strip() for p in payload.split("=>", 1)]
                    if not a:
                        print("Provide both question and answer: /teach question => answer")
                    else:
                        print(add_fact(q or None, a))
                continue
            elif name == "why":
                if _last_snippets:
                    print("Retrieved snippets (most relevant first):\n- " + "\n- ".join(_last_snippets))
                else:
                    print("No snippets captured for the last query.")
                continue
            elif name in ("mem-save", "mem-search", "mem-recent", "mem-delete",
                          "goals", "goal-add", "goal-done"):
                if not _MEMORY_AVAILABLE:
                    print("Memory/goals modules not available.")
                    continue
                if name == "mem-save":
                    text = (args or "").strip()
                    if not text:
                        print("Usage: /mem <text>")
                    else:
                        msg, _ = _save_memory(text)
                        print(msg)
                elif name == "mem-search":
                    query = (args or "").strip()
                    if not query:
                        print("Usage: /mem-search <query>")
                    else:
                        msg, _ = _search_memory(query, limit=10)
                        print(msg)
                elif name == "mem-recent":
                    msg, _ = _get_recent_memories(count=10)
                    print(msg)
                elif name == "mem-delete":
                    mid = (args or "").strip()
                    if not mid:
                        print("Usage: /mem-delete <id>")
                    else:
                        try:
                            msg, _ = _delete_memory(int(mid))
                            print(msg)
                        except ValueError:
                            print("ID must be a number.")
                elif name == "goals":
                    msg, _ = _list_goals(status="active")
                    print(msg)
                elif name == "goal-add":
                    title = (args or "").strip()
                    if not title:
                        print("Usage: /goal-add <title>")
                    else:
                        msg, _ = _create_goal(title)
                        print(msg)
                elif name == "goal-done":
                    gid = (args or "").strip()
                    if not gid:
                        print("Usage: /goal-done <id>")
                    else:
                        try:
                            msg, _ = _update_goal(int(gid), status="completed")
                            print(msg)
                        except ValueError:
                            print("ID must be a number.")
                continue
            elif name == "tts":
                CONFIG["TTS_ENABLED"] = not CONFIG.get("TTS_ENABLED", True)
                status = "ON" if CONFIG["TTS_ENABLED"] else "OFF"
                print(f"Text-to-Speech is now {status}.")
                continue

        # Normal conversation
        if not user_input:
            continue
        normalized = process_input(user_input)
        prompt = build_prompt(normalized)

        try:
            answer = ask_llm(prompt)
        except Exception as e:
            print(f"Aion (error): An error occurred while communicating with the LLM: {e}")
            continue

        answer = answer.strip() or "(no response)"
        print(f"Aion: {answer}")
        logger.debug("Answer from LLM: %s...", answer[:50])

        if CONFIG.get("TTS_ENABLED", True) and answer != "(no response)":
            logger.debug("Calling speak() with valid answer...")
            speak(answer)
        else:
            logger.debug("TTS is OFF or answer empty/no response, skipping speak.")


if __name__ == "__main__":
    sys.exit(main())
