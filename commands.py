# commands.py

from typing import Optional, Tuple

EXIT_COMMANDS = {"exit", "quit", ":q", "/exit", "/quit"}
HELP_COMMANDS = {"help", "/help", "?"}
RECALL_COMMANDS = {"recall", "/recall"}
RELOAD_COMMANDS = {"reload", "/reload"}
WHY_COMMANDS = {"why", "/why"}
MEM_COMMANDS = {"/mem", "/memory"}
MEM_SEARCH_COMMANDS = {"/mem-search", "/memory-search"}
MEM_RECENT_COMMANDS = {"/mem-recent", "/memory-recent"}
MEM_DELETE_COMMANDS = {"/mem-delete", "/memory-delete"}
GOAL_COMMANDS = {"/goals", "/goal-list"}
GOAL_ADD_COMMANDS = {"/goal-add", "/goal-new"}
GOAL_DONE_COMMANDS = {"/goal-done", "/goal-complete"}


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
    if lowered in MEM_COMMANDS:
        return ("mem", "")
    if lowered.startswith("/mem ") or lowered.startswith("/memory "):
        # /mem <text> — save a memory
        parts = text.split(" ", 1)
        return ("mem-save", parts[1].strip() if len(parts) > 1 else "")
    if lowered in MEM_SEARCH_COMMANDS:
        return ("mem-search", "")
    if lowered.startswith("/mem-search ") or lowered.startswith("/memory-search "):
        parts = text.split(" ", 1)
        return ("mem-search", parts[1].strip() if len(parts) > 1 else "")
    if lowered in MEM_RECENT_COMMANDS:
        return ("mem-recent", "")
    if lowered.startswith("/mem-delete ") or lowered.startswith("/memory-delete "):
        parts = text.split(" ", 1)
        return ("mem-delete", parts[1].strip() if len(parts) > 1 else "")
    if lowered in GOAL_COMMANDS:
        return ("goals", "")
    if lowered.startswith("/goal-add ") or lowered.startswith("/goal-new "):
        parts = text.split(" ", 1)
        return ("goal-add", parts[1].strip() if len(parts) > 1 else "")
    if lowered.startswith("/goal-done ") or lowered.startswith("/goal-complete "):
        parts = text.split(" ", 1)
        return ("goal-done", parts[1].strip() if len(parts) > 1 else "")
    return None


def help_text() -> str:
    return (
        "Commands:\n"
        "  /help               Show this help\n"
        "  /recall             Show a few loaded facts (debug)\n"
        "  /reload             Reload facts from data files\n"
        "  /why                Show retrieved snippets for last answer\n"
        "  /note TEXT          Save a fact/note\n"
        "  /teach Q => A       Teach a Q→A pair\n"
        "  /set k=v            Set a runtime option\n"
        "  /mem TEXT           Save a memory\n"
        "  /mem-search QUERY   Search memories\n"
        "  /mem-recent         Show 10 most recent memories\n"
        "  /mem-delete ID      Delete a memory by ID\n"
        "  /goals              List active goals\n"
        "  /goal-add TEXT      Add a new goal\n"
        "  /goal-done ID       Mark a goal complete\n"
        "  exit|quit           Exit the app\n"
    )
