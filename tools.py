"""Allowlisted network ops tools for Jarvis."""
from __future__ import annotations

import ipaddress
import re
import shlex
import subprocess
from typing import Iterable

from config import CONFIG

_HOST_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*[a-zA-Z0-9]$")


def _normalize_target(target: str) -> str:
    return (target or "").strip().lower().rstrip(".")


def _authorized_patterns() -> list[str]:
    return [_normalize_target(v) for v in (CONFIG.get("authorized_network_targets") or []) if _normalize_target(v)]


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _is_private_or_loopback(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


def is_authorized_target(target: str) -> bool:
    normalized = _normalize_target(target)
    if not normalized or not _HOST_RE.match(normalized):
        return False
    if _is_ip_address(normalized):
        if _is_private_or_loopback(normalized) or normalized in _authorized_patterns():
            return True
        for pattern in _authorized_patterns():
            if "/" in pattern:
                try:
                    if ipaddress.ip_address(normalized) in ipaddress.ip_network(pattern, strict=False):
                        return True
                except ValueError:
                    continue
        return False
    if normalized in {"localhost"}:
        return True
    patterns = _authorized_patterns()
    for pattern in patterns:
        if pattern.startswith("*."):
            suffix = pattern[1:]
            if normalized.endswith(suffix):
                return True
        elif normalized == pattern:
            return True
    return False


def _run_tool(args: Iterable[str], timeout: int = 20, max_chars: int = 2500) -> str:
    try:
        result = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return "Required tool is not installed on this host."
    except Exception as e:
        return f"Error: {e}"

    output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
    output = output.strip() or "(no output)"
    if len(output) > max_chars:
        output = output[:max_chars] + "\n... (truncated)"
    return output


def run_nslookup(target: str) -> str:
    if not is_authorized_target(target):
        return "Target is not authorized. Add it to CONFIG['authorized_network_targets'] first."
    return _run_tool(["nslookup", target], timeout=10)


def run_whois(target: str) -> str:
    if not is_authorized_target(target):
        return "Target is not authorized. Add it to CONFIG['authorized_network_targets'] first."
    return _run_tool(["whois", target], timeout=15)


def run_dig(target: str, record_type: str = "A") -> str:
    if not is_authorized_target(target):
        return "Target is not authorized. Add it to CONFIG['authorized_network_targets'] first."
    record_type = (record_type or "A").upper()
    if record_type not in {"A", "AAAA", "MX", "TXT", "CNAME", "NS", "SOA"}:
        return "Unsupported DNS record type."
    return _run_tool(["dig", target, record_type, "+short"], timeout=10)


def run_ping(target: str, count: int = 4) -> str:
    if not is_authorized_target(target):
        return "Target is not authorized. Add it to CONFIG['authorized_network_targets'] first."
    count = max(1, min(int(count), 4))
    return _run_tool(["ping", "-c", str(count), target], timeout=10)


def run_traceroute(target: str) -> str:
    if not is_authorized_target(target):
        return "Target is not authorized. Add it to CONFIG['authorized_network_targets'] first."
    return _run_tool(["traceroute", "-m", "12", target], timeout=30)


def run_nmap_ping_sweep(target: str) -> str:
    if not is_authorized_target(target):
        return "Target is not authorized. Add it to CONFIG['authorized_network_targets'] first."
    return _run_tool(["nmap", "-sn", target], timeout=30)


def run_nmap_service_scan(target: str) -> str:
    if not is_authorized_target(target):
        return "Target is not authorized. Add it to CONFIG['authorized_network_targets'] first."
    return _run_tool(["nmap", "-Pn", "-sV", "--top-ports", "20", target], timeout=45)


def handle_ops_command(message: str, client_ip: str) -> str | None:
    if not CONFIG.get("network_ops_enabled", True):
        return None

    text = (message or "").strip()
    lowered = text.lower()
    if any(p in lowered for p in ["my ip", "my public ip", "what is my ip", "whats my ip"]):
        return f"Your public IP address is: {client_ip}"

    m = re.match(r"^(?:nslookup|dns lookup|lookup)\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"NSLookup for {target}:\n```\n{run_nslookup(target)}\n```"

    m = re.match(r"^whois\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"WHOIS for {target}:\n```\n{run_whois(target)}\n```"

    m = re.match(r"^(?:dig|dns)\s+([^\s]+)(?:\s+([a-z]+))?$", lowered)
    if m:
        target, record_type = m.group(1), (m.group(2) or "A")
        return f"DIG for {target} ({record_type.upper()}):\n```\n{run_dig(target, record_type)}\n```"

    m = re.match(r"^ping\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"PING for {target}:\n```\n{run_ping(target)}\n```"

    m = re.match(r"^(?:traceroute|trace)\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"Traceroute for {target}:\n```\n{run_traceroute(target)}\n```"

    m = re.match(r"^(?:nmap|scan)\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return (
            f"Nmap service scan for {target}:\n```\n{run_nmap_service_scan(target)}\n```"
        )

    m = re.match(r"^(?:ping sweep|discover hosts)\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"Nmap ping sweep for {target}:\n```\n{run_nmap_ping_sweep(target)}\n```"

    return None
