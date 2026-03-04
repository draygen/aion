"""Vast.ai API client — search offers, deploy, destroy, redeploy code."""
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

apt-get update -qq && apt-get install -y -qq curl python3-pip rsync git

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
    """List all running/provisioning instances on the account."""
    resp = requests.get(f"{VAST_API_BASE}/instances/", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json().get("instances", [])


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
    resp.raise_for_status()
    return resp.json()


def destroy_instance(instance_id: int) -> dict:
    """Permanently destroy an instance."""
    resp = requests.delete(f"{VAST_API_BASE}/instances/{instance_id}/", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def redeploy_code(ssh_host: str, ssh_port: int) -> dict:
    """Rsync local code to instance and restart gunicorn."""
    key_path = os.path.expanduser(CONFIG.get("vast_ssh_key", "~/.ssh/id_ed25519"))
    ssh_opts = f"ssh -o StrictHostKeyChecking=no -p {ssh_port} -i {key_path}"

    rsync_cmd = [
        "rsync", "-az", "-e", ssh_opts,
        "--exclude=data/", "--exclude=.venv*", "--exclude=__pycache__",
        "--exclude=*.pyc", "--exclude=hf_cache/",
        "--exclude=bin/", "--exclude=lib/", "--exclude=lib64",
        "--exclude=pyvenv.cfg", "--exclude=*.mp3",
        "--exclude=cloudflared*", "--exclude=ui/node_modules/",
        f"{_JARVIS_DIR}/",
        f"root@{ssh_host}:/workspace/jarvis/",
    ]
    r = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {"ok": False, "error": f"rsync failed: {r.stderr}"}

    restart_cmd = (
        "pkill gunicorn || true; sleep 1; cd /workspace/jarvis && "
        "nohup gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 web:app "
        ">> /var/log/jarvis.log 2>&1 &"
    )
    ssh_cmd = [
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-p", str(ssh_port), "-i", key_path,
        f"root@{ssh_host}", restart_cmd,
    ]
    r2 = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
    return {"ok": r2.returncode == 0, "error": r2.stderr if r2.returncode != 0 else None}
