"""Vast.ai API client — search offers, deploy, manage, destroy, redeploy code."""
import os
import subprocess

import requests

from config import CONFIG

VAST_API_BASE = "https://console.vast.ai/api/v0"

# Auto-deploy shell script. MODEL_NAME is substituted before use.
_ONSTART_TEMPLATE = r"""#!/bin/bash
exec >> /var/log/jarvis-setup.log 2>&1
echo "[$(date)] === Jarvis Auto-Deploy Started ==="
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq && apt-get install -y -qq curl python3-pip rsync git zstd

# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve >> /var/log/ollama.log 2>&1 &

# Wait for Ollama to be ready
for i in $(seq 1 24); do
    ollama list >/dev/null 2>&1 && break
    echo "Waiting for Ollama ($i)..." && sleep 5
done

# Clone Jarvis
mkdir -p /workspace
git clone https://github.com/draygen/jarvis.git /workspace/jarvis
cd /workspace/jarvis
mkdir -p data

# Python dependencies
pip3 install -q flask flask-cors scikit-learn gtts elevenlabs requests gunicorn beautifulsoup4 bcrypt

# Pull LLM model in background (takes a while)
nohup ollama pull MODEL_NAME >> /var/log/ollama.log 2>&1 &

# Start Jarvis on port 5000
nohup gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 web:app >> /var/log/jarvis.log 2>&1 &

echo "[$(date)] === Jarvis running on :5000 ==="
"""

_JARVIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _headers():
    api_key = CONFIG.get("vast_api_key", "")
    if not api_key:
        raise ValueError("vast_api_key not set in config.py")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _extract_instance(payload: dict) -> dict:
    if "instance" in payload and isinstance(payload["instance"], dict):
        return payload["instance"]
    instances = payload.get("instances")
    if isinstance(instances, dict):
        return instances
    if isinstance(instances, list) and instances:
        return instances[0]
    return payload


def _update_instance_state(instance_id: int, state: str) -> dict:
    body = {"state": state}
    resp = requests.put(
        f"{VAST_API_BASE}/instances/{instance_id}/",
        headers=_headers(),
        json=body,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def search_offers(max_dph=None, min_gpu_ram_gb=None, gpu_name=None, limit=25):
    """Search available GPU offers sorted by price ascending."""
    body = {
        "limit": limit,
        "type": "ondemand",
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "order": [["dph_total", "asc"]],
    }
    if max_dph is not None:
        body["dph_total"] = {"lte": float(max_dph)}
    if min_gpu_ram_gb is not None:
        body["gpu_ram"] = {"gte": float(min_gpu_ram_gb) * 1024}
    if gpu_name and gpu_name.strip():
        body["gpu_name"] = {"eq": gpu_name.strip()}

    resp = requests.post(f"{VAST_API_BASE}/bundles/", headers=_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json().get("offers", [])


def get_instances():
    """List all instances on the account."""
    resp = requests.get(f"{VAST_API_BASE}/instances/", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json().get("instances", [])


def get_instance(instance_id: int) -> dict:
    """Get details for a single instance."""
    resp = requests.get(f"{VAST_API_BASE}/instances/{instance_id}/", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return _extract_instance(resp.json())


def get_ssh_details(instance_id: int) -> dict:
    """Return normalized SSH connection details for an instance."""
    instance = get_instance(instance_id)
    host = (
        instance.get("ssh_host")
        or instance.get("host")
        or instance.get("public_ipaddr")
        or instance.get("public_ip")
    )
    port = (
        instance.get("ssh_port")
        or instance.get("port")
        or instance.get("direct_ssh_port")
        or _extract_ssh_port(instance.get("ports"))
    )
    public_ip = instance.get("public_ipaddr") or instance.get("public_ip")
    actual_status = instance.get("actual_status") or instance.get("cur_state") or instance.get("status")
    if not host or not port:
        raise ValueError(f"Could not determine SSH endpoint for instance {instance_id}")
    return {
        "instance_id": instance.get("id", instance_id),
        "ssh_host": str(host),
        "ssh_port": int(port),
        "public_ip": public_ip,
        "status": actual_status,
        "label": instance.get("label"),
        "raw_instance": instance,
    }


def deploy_on_offer(offer_id: int, disk_gb: int = 40) -> dict:
    """Rent an offer and start the Jarvis auto-deploy script."""
    model = CONFIG.get("model", "qwen2.5:7b")
    script = _ONSTART_TEMPLATE.replace("MODEL_NAME", model)
    body = {
        "image": "ubuntu:22.04",
        "disk": disk_gb,
        "runtype": "ssh_direct",
        "label": "jarvis",
        "env": {"-p 5000:5000": "1"},
        "onstart": script,
    }
    resp = requests.put(f"{VAST_API_BASE}/asks/{offer_id}/", headers=_headers(), json=body, timeout=30)
    if not resp.ok:
        raise ValueError(f"Vast deploy failed for offer {offer_id}: {resp.status_code} {resp.text}")
    return resp.json()


def destroy_instance(instance_id: int) -> dict:
    """Permanently destroy an instance."""
    resp = requests.delete(f"{VAST_API_BASE}/instances/{instance_id}/", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def stop_instance(instance_id: int) -> dict:
    """Stop an instance to pause compute billing."""
    return _update_instance_state(instance_id, "stopped")


def start_instance(instance_id: int) -> dict:
    """Start a stopped instance."""
    return _update_instance_state(instance_id, "running")


def restart_instance(instance_id: int) -> dict:
    """Restart an instance via stop/start sequence."""
    stop_result = stop_instance(instance_id)
    start_result = start_instance(instance_id)
    return {"ok": True, "stop": stop_result, "start": start_result}


def build_ssh_command(ssh_host: str, ssh_port: int) -> str:
    key_path = os.path.expanduser(CONFIG.get("vast_ssh_key", "~/.ssh/id_ed25519"))
    return f"ssh -o StrictHostKeyChecking=no -p {ssh_port} -i {key_path} root@{ssh_host}"


def redeploy_code(ssh_host: str, ssh_port: int) -> dict:
    """Rsync local code to instance and restart gunicorn."""
    key_path = os.path.expanduser(CONFIG.get("vast_ssh_key", "~/.ssh/id_ed25519"))
    ssh_opts = f"ssh -o StrictHostKeyChecking=no -p {ssh_port} -i {key_path}"

    rsync_cmd = [
        "rsync", "-az", "-e", ssh_opts,
        "--exclude=.git/",
        "--exclude=data/", "--exclude=.venv*", "--exclude=__pycache__",
        "--exclude=*.pyc", "--exclude=hf_cache/",
        "--exclude=bin/", "--exclude=lib/", "--exclude=lib64",
        "--exclude=pyvenv.cfg", "--exclude=*.mp3",
        "--exclude=cloudflared*", "--exclude=ui/node_modules/",
        "--exclude=ui/dist/", "--exclude=*.pdf", "--exclude=*.md",
        "--exclude=WinSecSweep.ps1", "--exclude=*.bat",
        f"{_JARVIS_DIR}/",
        f"root@{ssh_host}:/workspace/jarvis/",
    ]
    r = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        return {"ok": False, "error": f"rsync failed: {r.stderr}"}

    restart_cmd = (
        "pkill gunicorn >/dev/null 2>&1 || true; "
        "sleep 1; "
        "cd /workspace/jarvis && "
        "setsid -f gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 web:app "
        ">> /var/log/jarvis.log 2>&1 < /dev/null; "
        "echo restarted"
    )
    ssh_cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-p", str(ssh_port), "-i", key_path,
        f"root@{ssh_host}", restart_cmd,
    ]
    r2 = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=120)
    return {"ok": r2.returncode == 0, "error": r2.stderr if r2.returncode != 0 else None}


def _extract_ssh_port(ports) -> int | None:
    if isinstance(ports, dict):
        for key, value in ports.items():
            if "22" not in str(key):
                continue
            if isinstance(value, list) and value and isinstance(value[0], dict):
                host_port = value[0].get("HostPort") or value[0].get("host_port")
                if host_port:
                    return int(host_port)
            if isinstance(value, list) and value:
                return int(value[0])
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    if isinstance(ports, list):
        for item in ports:
            if not isinstance(item, dict):
                continue
            if str(item.get("container_port")) != "22":
                continue
            host_port = item.get("host_port") or item.get("public_port")
            if host_port:
                return int(host_port)
    return None
