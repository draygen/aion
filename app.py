import sys
from typing import Optional

from config import CONFIG
from commands import process_input, parse_command, help_text
from brain import get_fact, get_facts, recall, load_facts, add_fact
from llm import ask_llm

# Keep the last retrieved snippets for /why
_last_snippets = []


def build_prompt(user_text: str) -> str:
    """Build a conversational prompt with multiple retrieved facts.
    Store snippets for /why.
    """
    global _last_snippets
    facts = get_facts(user_text, k=12)
    _last_snippets = facts or []
    ctx_header = (
        "You are JARVIS, Brian's personal AI assistant. Address him as Brian (draygen).\n"
        "Style: informal, opinionated, extremely direct, sometimes sarcastic/humorous.\n"
        "Answer concisely (1-4 sentences).\n"
        "Use ONLY the context snippets if they are relevant. If the answer is not in context, say: I don't know.\n\n"
    )
    if facts:
        joined = "\n- ".join(facts)
        context_block = f"Context (up to 12 snippets):\n- {joined}\n\n"
    else:
        context_block = ""

    return f"{ctx_header}{context_block}User: {user_text}\nAssistant:"


def handle_set(args: str) -> str:
    """Handle /set key=value updates for runtime CONFIG."""
    if not args or "=" not in args:
        return "Usage: /set key=value (e.g., /set model=mistral)"
    key, value = [p.strip() for p in args.split("=", 1)]
    if not key:
        return "Invalid key."
    CONFIG[key] = value
    return f"Set {key} = {value}"


def main() -> int:
    print("Jarvis is online. Type /help for commands. Type 'exit' to quit.")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0

        # Command handling
        cmd = parse_command(user_input)
        if cmd:
            name, args = cmd
            if name == "exit":
                print("Jarvis: Goodbye.")
                return 0
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
                text = (args or '').strip()
                if not text:
                    print("Usage: /note some fact about Brian")
                else:
                    print(add_fact(None, text))
                continue
            elif name == "teach":
                payload = (args or '')
                if "=>" not in payload:
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

        # Normal conversation path
        if not user_input:
            continue
        normalized = process_input(user_input)
        prompt = build_prompt(normalized)

        try:
            answer = ask_llm(prompt)
        except Exception as e:
            print(f"Jarvis (error): {e}")
            continue

        # Basic cleanup
        answer = answer.strip()
        if not answer:
            answer = "(no response)"
        print(f"Jarvis: {answer}")


if __name__ == "__main__":
    sys.exit(main())

