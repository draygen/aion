import json
import sys
import urllib.request


BASE_URL = "http://183.89.209.74:56635"


def request_json(path: str, token: str, payload: dict | None = None) -> str:
    data = None
    headers = {"Cookie": f"aion_token={token}"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()


if __name__ == "__main__":
    token = sys.argv[1]
    action = sys.argv[2]
    if action == "get-config":
        print(request_json("/api/admin/network/config", token))
    elif action == "set-config":
        payload = {
            "authorized_network_targets": ["localhost", "127.0.0.1", "183.89.209.74"],
            "network_ops_enabled": True,
        }
        print(request_json("/api/admin/network/config", token, payload))
    elif action == "run-command":
        payload = {"command": "ping 127.0.0.1"}
        print(request_json("/api/admin/network/run", token, payload))
    elif action == "run-public":
        payload = {"command": "ping 183.89.209.74"}
        print(request_json("/api/admin/network/run", token, payload))
    else:
        raise SystemExit(f"unknown action: {action}")
