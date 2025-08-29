# commands.py

from typing import Optional, Tuple

EXIT_COMMANDS = {"exit", "quit", ":q", "/exit", "/quit"}
HELP_COMMANDS = {"help", "/help", "?"}
RECALL_COMMANDS = {"recall", "/recall"}
RELOAD_COMMANDS = {"reload", "/reload"}
WHY_COMMANDS = {"why", "/why"}


def process_input(user_input: str) -> str:
    """Normalize user input for downstream processing."""
    return user_input.strip()


def parse_command(user_input: str) -> Optional[Tuple[str, str]]:
    """Return (command, args) if the input is a recognized command, else None."""
    text = user_input.strip()
    lowered = text.lower()
    if lowered in EXIT_COMMANDS:
        return ("exit", "")
    if lowered in HELP_COMMANDS:
        return ("help", "")
    if lowered.startswith("/set "):
        return ("set", text[5:].strip())
    if lowered in RECALL_COMMANDS:
        return ("recall", "")
    if lowered in RELOAD_COMMANDS:
        return ("reload", "")
    if lowered in WHY_COMMANDS:
        return ("why", "")
    if lowered.startswith("/note "):
        return ("note", text[6:].strip())
    if lowered.startswith("/teach "):
        return ("teach", text[7:].strip())
    return None


def help_text() -> str:
    return (
        "Commands:\n"
        "  /help         Show this help\n"
        "  /recall       Show a few loaded facts (debug)\n"
        "  /reload       Reload facts from data files\n"
        "  /why          Show the retrieved snippets used for the last answer\n"
        "  /note TEXT    Save a standalone fact/note to memory now\n"
        "  /teach Q => A Teach a Q→A pair to memory now\n"
        "  /set k=v      Set a runtime option (e.g., /set model=mistral)\n"
        "  exit|quit     Exit the app\n"
    )
