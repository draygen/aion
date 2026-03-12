"""Allowlisted network ops tools for Aion."""
from __future__ import annotations

import ipaddress
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from config import CONFIG

_HOST_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*[a-zA-Z0-9]$")
_DEFAULT_FFUF_WORDLIST = "/workspace/aion/data/admin_wordlists/ffuf_quick.txt"
_TOOL_REGISTRY = None


@dataclass
class ToolInvocation:
    tool_id: str
    label: str
    args: dict


@dataclass
class ToolExecution:
    tool_id: str
    label: str
    args: dict
    output: str


@dataclass
class RegisteredTool:
    tool_id: str
    label: str
    description: str
    matcher: Callable[[str], Optional[dict]]
    executor: Callable[[dict, dict], str]
    installed: Callable[[], bool]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: list[RegisteredTool] = []

    def register(self, tool: RegisteredTool) -> None:
        self._tools.append(tool)

    def list_tools(self) -> list[dict]:
        return [
            {
                "id": tool.tool_id,
                "label": tool.label,
                "description": tool.description,
                "installed": bool(tool.installed()),
            }
            for tool in self._tools
        ]

    def match(self, message: str) -> ToolInvocation | None:
        text = (message or "").strip()
        for tool in self._tools:
            args = tool.matcher(text)
            if args is not None:
                return ToolInvocation(tool_id=tool.tool_id, label=tool.label, args=args)
        return None

    def dispatch(self, message: str, context: dict | None = None) -> ToolExecution | None:
        invocation = self.match(message)
        if not invocation:
            return None
        context = context or {}
        tool = self._tool_by_id(invocation.tool_id)
        output = tool.executor(invocation.args, context)
        return ToolExecution(
            tool_id=invocation.tool_id,
            label=invocation.label,
            args=invocation.args,
            output=output,
        )

    def _tool_by_id(self, tool_id: str) -> RegisteredTool:
        for tool in self._tools:
            if tool.tool_id == tool_id:
                return tool
        raise KeyError(tool_id)


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


def _format_tool_output(label: str, target: str, output: str, suffix: str = "") -> str:
    heading = f"{label} for {target}"
    if suffix:
        heading += f" {suffix}"
    return f"{heading}:\n```\n{output}\n```"


def _exact_phrase_match(*phrases: str) -> Callable[[str], Optional[dict]]:
    normalized = {phrase.lower() for phrase in phrases}

    def matcher(text: str) -> Optional[dict]:
        if text.strip().lower() in normalized:
            return {}
        return None

    return matcher


def _regex_match(pattern: str, arg_names: tuple[str, ...]) -> Callable[[str], Optional[dict]]:
    compiled = re.compile(pattern, re.IGNORECASE)

    def matcher(text: str) -> Optional[dict]:
        match = compiled.match((text or "").strip())
        if not match:
            return None
        groups = match.groups()
        return {name: groups[index] for index, name in enumerate(arg_names)}

    return matcher


def _build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            tool_id="my_ip",
            label="Public IP",
            description="Report the requester IP seen by the server.",
            matcher=_exact_phrase_match("my ip", "my public ip", "what is my ip", "whats my ip"),
            executor=lambda args, context: f"Your public IP address is: {context.get('client_ip', 'unknown')}",
            installed=lambda: True,
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="nslookup",
            label="NSLookup",
            description="Run DNS lookup for an authorized host.",
            matcher=_regex_match(r"^(?:nslookup|dns lookup|lookup)\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("NSLookup", _extract_target(args["target"]), run_nslookup(args["target"])),
            installed=lambda: _tool_installed("nslookup"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="whois",
            label="WHOIS",
            description="Run WHOIS on an authorized host.",
            matcher=_regex_match(r"^whois\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("WHOIS", _extract_target(args["target"]), run_whois(args["target"])),
            installed=lambda: _tool_installed("whois"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="dig",
            label="DIG",
            description="Query DNS records for an authorized host.",
            matcher=_regex_match(r"^(?:dig|dns)\s+([^\s]+)(?:\s+([a-z]+))?$", ("target", "record_type")),
            executor=lambda args, context: _format_tool_output(
                "DIG",
                _extract_target(args["target"]),
                run_dig(args["target"], args.get("record_type") or "A"),
                f"({(args.get('record_type') or 'A').upper()})",
            ),
            installed=lambda: _tool_installed("dig"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="ping",
            label="Ping",
            description="Ping an authorized host.",
            matcher=_regex_match(r"^ping\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("PING", _extract_target(args["target"]), run_ping(args["target"])),
            installed=lambda: _tool_installed("ping"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="traceroute",
            label="Traceroute",
            description="Run traceroute to an authorized host.",
            matcher=_regex_match(r"^(?:traceroute|trace)\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("Traceroute", _extract_target(args["target"]), run_traceroute(args["target"])),
            installed=lambda: _tool_installed("traceroute"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="nmap_service_scan",
            label="Nmap",
            description="Run a top-ports service scan against an authorized host.",
            matcher=_regex_match(r"^(?:(?:nmap|scan|web scan|http scan))\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output(
                "Nmap service scan",
                _extract_target(args["target"]),
                run_nmap_service_scan(_extract_target(args["target"])),
            ),
            installed=lambda: _tool_installed("nmap"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="nmap_ping_sweep",
            label="Nmap Ping Sweep",
            description="Discover live hosts in an authorized CIDR.",
            matcher=_regex_match(r"^(?:ping sweep|discover hosts)\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("Nmap ping sweep", args["target"], run_nmap_ping_sweep(args["target"])),
            installed=lambda: _tool_installed("nmap"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="httpx",
            label="httpx",
            description="Probe an authorized URL with httpx.",
            matcher=_regex_match(r"^httpx\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("httpx", _extract_target(args["target"]), run_httpx(args["target"])),
            installed=lambda: bool(_first_installed("httpx")),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="whatweb",
            label="WhatWeb",
            description="Fingerprint an authorized URL with WhatWeb.",
            matcher=_regex_match(r"^whatweb\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("WhatWeb", _extract_target(args["target"]), run_whatweb(args["target"])),
            installed=lambda: _tool_installed("whatweb"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="nikto",
            label="Nikto",
            description="Run Nikto against an authorized URL.",
            matcher=_regex_match(r"^nikto\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("Nikto", _extract_target(args["target"]), run_nikto(args["target"])),
            installed=lambda: _tool_installed("nikto"),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="testssl",
            label="testssl.sh",
            description="Run TLS checks against an authorized host.",
            matcher=_regex_match(r"^testssl\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("testssl.sh", _extract_target(args["target"]), run_testssl(args["target"])),
            installed=lambda: bool(_first_installed("testssl.sh", "/usr/local/bin/testssl.sh")),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="zap_baseline",
            label="OWASP ZAP",
            description="Run the ZAP baseline scan against an authorized URL.",
            matcher=_regex_match(r"^(?:zap|zap baseline)\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("OWASP ZAP baseline", _extract_target(args["target"]), run_zap_baseline(args["target"])),
            installed=lambda: bool(_first_installed("zap-baseline.py", "/usr/share/zaproxy/zap-baseline.py")),
        )
    )
    registry.register(
        RegisteredTool(
            tool_id="ffuf",
            label="ffuf",
            description="Run ffuf against an authorized URL or host.",
            matcher=_regex_match(r"^ffuf\s+([^\s]+)$", ("target",)),
            executor=lambda args, context: _format_tool_output("ffuf", _extract_target(args["target"]), run_ffuf(args["target"])),
            installed=lambda: _tool_installed("ffuf"),
        )
    )
    return registry


def get_tool_registry() -> ToolRegistry:
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY is None:
        _TOOL_REGISTRY = _build_tool_registry()
    return _TOOL_REGISTRY


def available_tool_status() -> list[dict]:
    return get_tool_registry().list_tools()


def dispatch_tool_message(message: str, client_ip: str) -> ToolExecution | None:
    if not CONFIG.get("network_ops_enabled", True):
        return None
    return get_tool_registry().dispatch(message, {"client_ip": client_ip})


def handle_ops_command(message: str, client_ip: str, include_help: bool = True) -> str | None:
    execution = dispatch_tool_message(message, client_ip)
    if execution:
        return execution.output
    if include_help and CONFIG.get("network_ops_enabled", True):
        return _unsupported_command_help()
    return None
