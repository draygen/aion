"""Allowlisted network ops tools for Jarvis."""
from __future__ import annotations

import ipaddress
import re
import shutil
import subprocess
from typing import Iterable
from urllib.parse import urlparse

from config import CONFIG

_HOST_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*[a-zA-Z0-9]$")
_DEFAULT_FFUF_WORDLIST = "/workspace/jarvis/data/admin_wordlists/ffuf_quick.txt"


def _normalize_target(target: str) -> str:
    return (target or "").strip().lower().rstrip(".")


def _extract_target(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"//{value}", scheme="http")
    host = parsed.hostname or value
    return _normalize_target(host)


def _unsupported_command_help() -> str:
    return (
        "Unsupported command. Try one of: "
        "ping <host>, dig <host> [A|AAAA|MX|TXT|CNAME|NS|SOA], "
        "nslookup <host>, whois <host>, traceroute <host>, "
        "scan <host>, web scan <host>, ping sweep <cidr>, "
        "httpx <url>, whatweb <url>, nikto <url>, testssl <host>, "
        "zap <url>, ffuf <url-or-host>."
    )


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
    raw = _normalize_target(target)
    if "/" in raw:
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            return False
        for pattern in _authorized_patterns():
            try:
                allowed = ipaddress.ip_network(pattern, strict=False)
            except ValueError:
                continue
            if network.subnet_of(allowed) or network == allowed:
                return True
        return False

    normalized = _extract_target(target)
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


def _tool_installed(name: str) -> bool:
    return shutil.which(name) is not None


def _first_installed(*names: str) -> str | None:
    for name in names:
        if _tool_installed(name):
            return name
    return None


def _normalize_web_target(target: str) -> str:
    value = (target or "").strip()
    if not value:
        return ""
    if "://" in value:
        return value
    if "/" in value:
        return f"http://{value}"
    return f"http://{value}"


def _ensure_authorized(target: str) -> str | None:
    if not is_authorized_target(target):
        return "Target is not authorized. Add it to CONFIG['authorized_network_targets'] first."
    return None


def run_nslookup(target: str) -> str:
    target = _extract_target(target)
    err = _ensure_authorized(target)
    if err:
        return err
    return _run_tool(["nslookup", target], timeout=10)


def run_whois(target: str) -> str:
    target = _extract_target(target)
    err = _ensure_authorized(target)
    if err:
        return err
    return _run_tool(["whois", target], timeout=15)


def run_dig(target: str, record_type: str = "A") -> str:
    target = _extract_target(target)
    err = _ensure_authorized(target)
    if err:
        return err
    record_type = (record_type or "A").upper()
    if record_type not in {"A", "AAAA", "MX", "TXT", "CNAME", "NS", "SOA"}:
        return "Unsupported DNS record type."
    return _run_tool(["dig", target, record_type, "+short"], timeout=10)


def run_ping(target: str, count: int = 4) -> str:
    target = _extract_target(target)
    err = _ensure_authorized(target)
    if err:
        return err
    count = max(1, min(int(count), 4))
    return _run_tool(["ping", "-c", str(count), target], timeout=10)


def run_traceroute(target: str) -> str:
    target = _extract_target(target)
    err = _ensure_authorized(target)
    if err:
        return err
    return _run_tool(["traceroute", "-m", "12", target], timeout=30)


def run_nmap_ping_sweep(target: str) -> str:
    target = _extract_target(target) if "/" not in target else _normalize_target(target)
    err = _ensure_authorized(target)
    if err:
        return err
    return _run_tool(["nmap", "-sn", target], timeout=30)


def run_nmap_service_scan(target: str) -> str:
    target = _extract_target(target)
    err = _ensure_authorized(target)
    if err:
        return err
    return _run_tool(["nmap", "-Pn", "-sV", "--top-ports", "20", target], timeout=45)


def run_httpx(target: str) -> str:
    host = _extract_target(target)
    err = _ensure_authorized(host)
    if err:
        return err
    command = _first_installed("httpx")
    if not command:
        return "httpx is not installed on this host."
    return _run_tool([command, "-u", _normalize_web_target(target), "-follow-host-redirects", "-status-code", "-title", "-tech-detect"], timeout=30)


def run_whatweb(target: str) -> str:
    host = _extract_target(target)
    err = _ensure_authorized(host)
    if err:
        return err
    if not _tool_installed("whatweb"):
        return "whatweb is not installed on this host."
    return _run_tool(["whatweb", _normalize_web_target(target)], timeout=45)


def run_nikto(target: str) -> str:
    host = _extract_target(target)
    err = _ensure_authorized(host)
    if err:
        return err
    if not _tool_installed("nikto"):
        return "nikto is not installed on this host."
    return _run_tool(["nikto", "-ask", "no", "-host", _normalize_web_target(target)], timeout=90)


def run_testssl(target: str) -> str:
    host = _extract_target(target)
    err = _ensure_authorized(host)
    if err:
        return err
    command = _first_installed("testssl.sh", "/usr/local/bin/testssl.sh")
    if not command:
        return "testssl.sh is not installed on this host."
    return _run_tool([command, "--warnings", "batch", "--fast", host], timeout=120)


def run_zap_baseline(target: str) -> str:
    host = _extract_target(target)
    err = _ensure_authorized(host)
    if err:
        return err
    command = _first_installed("zap-baseline.py", "/usr/share/zaproxy/zap-baseline.py")
    if not command:
        return "OWASP ZAP baseline script is not installed on this host."
    return _run_tool([command, "-t", _normalize_web_target(target), "-m", "1", "-T", "5", "-I"], timeout=240, max_chars=4000)


def run_ffuf(target: str) -> str:
    host = _extract_target(target)
    err = _ensure_authorized(host)
    if err:
        return err
    if not _tool_installed("ffuf"):
        return "ffuf is not installed on this host."
    url = _normalize_web_target(target).rstrip("/") + "/FUZZ"
    return _run_tool(
        [
            "ffuf",
            "-w",
            _DEFAULT_FFUF_WORDLIST,
            "-u",
            url,
            "-mc",
            "all",
            "-fc",
            "404",
            "-t",
            "20",
            "-c",
        ],
        timeout=120,
        max_chars=4000,
    )


def available_tool_status() -> list[dict]:
    return [
        {"id": "nslookup", "label": "NSLookup", "installed": _tool_installed("nslookup")},
        {"id": "whois", "label": "WHOIS", "installed": _tool_installed("whois")},
        {"id": "dig", "label": "DIG", "installed": _tool_installed("dig")},
        {"id": "ping", "label": "Ping", "installed": _tool_installed("ping")},
        {"id": "traceroute", "label": "Traceroute", "installed": _tool_installed("traceroute")},
        {"id": "nmap", "label": "Nmap", "installed": _tool_installed("nmap")},
        {"id": "httpx", "label": "httpx", "installed": _tool_installed("httpx")},
        {"id": "whatweb", "label": "WhatWeb", "installed": _tool_installed("whatweb")},
        {"id": "nikto", "label": "Nikto", "installed": _tool_installed("nikto")},
        {"id": "testssl", "label": "testssl.sh", "installed": bool(_first_installed("testssl.sh", "/usr/local/bin/testssl.sh"))},
        {"id": "zap", "label": "OWASP ZAP", "installed": bool(_first_installed("zap-baseline.py", "/usr/share/zaproxy/zap-baseline.py"))},
        {"id": "ffuf", "label": "ffuf", "installed": _tool_installed("ffuf")},
    ]


def handle_ops_command(message: str, client_ip: str) -> str | None:
    if not CONFIG.get("network_ops_enabled", True):
        return None

    text = (message or "").strip()
    lowered = text.lower()
    if any(p in lowered for p in ["my ip", "my public ip", "what is my ip", "whats my ip"]):
        return f"Your public IP address is: {client_ip}"

    m = re.match(r"^(?:nslookup|dns lookup|lookup)\s+([^\s]+)$", lowered)
    if m:
        target = _extract_target(m.group(1))
        return f"NSLookup for {target}:\n```\n{run_nslookup(target)}\n```"

    m = re.match(r"^whois\s+([^\s]+)$", lowered)
    if m:
        target = _extract_target(m.group(1))
        return f"WHOIS for {target}:\n```\n{run_whois(target)}\n```"

    m = re.match(r"^(?:dig|dns)\s+([^\s]+)(?:\s+([a-z]+))?$", lowered)
    if m:
        target, record_type = _extract_target(m.group(1)), (m.group(2) or "A")
        return f"DIG for {target} ({record_type.upper()}):\n```\n{run_dig(target, record_type)}\n```"

    m = re.match(r"^ping\s+([^\s]+)$", lowered)
    if m:
        target = _extract_target(m.group(1))
        return f"PING for {target}:\n```\n{run_ping(target)}\n```"

    m = re.match(r"^(?:traceroute|trace)\s+([^\s]+)$", lowered)
    if m:
        target = _extract_target(m.group(1))
        return f"Traceroute for {target}:\n```\n{run_traceroute(target)}\n```"

    m = re.match(r"^(?:(?:nmap|scan|web scan|http scan))\s+([^\s]+)$", lowered)
    if m:
        target = _extract_target(m.group(1))
        return (
            f"Nmap service scan for {target}:\n```\n{run_nmap_service_scan(target)}\n```"
        )

    m = re.match(r"^(?:ping sweep|discover hosts)\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"Nmap ping sweep for {target}:\n```\n{run_nmap_ping_sweep(target)}\n```"

    m = re.match(r"^httpx\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"httpx for {_extract_target(target)}:\n```\n{run_httpx(target)}\n```"

    m = re.match(r"^whatweb\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"WhatWeb for {_extract_target(target)}:\n```\n{run_whatweb(target)}\n```"

    m = re.match(r"^nikto\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"Nikto for {_extract_target(target)}:\n```\n{run_nikto(target)}\n```"

    m = re.match(r"^testssl\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"testssl.sh for {_extract_target(target)}:\n```\n{run_testssl(target)}\n```"

    m = re.match(r"^(?:zap|zap baseline)\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"OWASP ZAP baseline for {_extract_target(target)}:\n```\n{run_zap_baseline(target)}\n```"

    m = re.match(r"^ffuf\s+([^\s]+)$", lowered)
    if m:
        target = m.group(1)
        return f"ffuf for {_extract_target(target)}:\n```\n{run_ffuf(target)}\n```"

    return _unsupported_command_help()
