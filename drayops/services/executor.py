import os
import subprocess
from pathlib import Path

import vast


class ActionExecutor:
    def execute(self, target: dict, action: str, payload: dict) -> dict:
        actions = target.get("actions", {})
        if action not in actions:
            raise ValueError(f"Action '{action}' is not configured for target '{target['name']}'")
        action_def = actions.get(action) or {}

        target_type = target.get("target_type")
        if target_type == "local":
            return self._run_local_action(target, action, action_def, payload)
        if target_type == "vast":
            return self._run_vast_action(target, action, action_def, payload)
        raise ValueError(f"Unsupported target_type: {target_type}")

    def search_vast_offers(self, max_dph=None, min_gpu_ram=None, gpu_name=None) -> list[dict]:
        max_dph_val = float(max_dph) if max_dph not in (None, "") else None
        min_gpu_val = float(min_gpu_ram) if min_gpu_ram not in (None, "") else None
        return vast.search_offers(max_dph=max_dph_val, min_gpu_ram_gb=min_gpu_val, gpu_name=gpu_name or None)

    def deploy_vast_instance(self, preset_id: str, offer_id: int, payload: dict) -> dict:
        disk_gb = int(payload.get("disk_gb", 40))
        result = vast.deploy_on_offer(offer_id, disk_gb=disk_gb)
        instance = result.get("instance") or result
        if isinstance(result.get("new_contract"), int):
            instance_id = result["new_contract"]
        elif isinstance(instance, dict):
            instance_id = instance.get("id") or instance.get("new_contract") or result.get("new_contract")
        else:
            instance_id = None
        ssh_details = None
        if instance_id:
            try:
                ssh_details = vast.get_ssh_details(int(instance_id))
            except Exception:
                ssh_details = None
        return {
            "status": "completed",
            "summary": f"Requested Vast deployment for preset {preset_id} on offer {offer_id}",
            "provider_result": result,
            "instance_id": instance_id,
            "config_updates": {
                "instance_id": str(instance_id or ""),
                "ssh_host": (ssh_details or {}).get("ssh_host", ""),
                "ssh_port": str((ssh_details or {}).get("ssh_port", "") or ""),
            },
        }

    def _run_local_action(self, target: dict, action: str, action_def: dict, payload: dict) -> dict:
        command = action_def.get("command")
        if not command:
            raise ValueError(f"Local action '{action}' is missing a command")
        cwd = action_def.get("cwd") or target["config"].get("project_path")
        template_values = {**target.get("config", {}), **payload}
        command = self._render_command_template(command, template_values)
        run_in_wsl = self._as_bool(action_def.get("run_in_wsl"), default=None)
        if run_in_wsl is None:
            run_in_wsl = self._as_bool(target.get("config", {}).get("run_in_wsl"), default=False)
        wsl_distro = action_def.get("wsl_distro") or target.get("config", {}).get("wsl_distro")
        resolved_command = command
        shell = True

        if run_in_wsl:
            resolved_command = self._wrap_wsl_command(command, cwd, wsl_distro)
            shell = False
            cwd = None

        completed = subprocess.run(
            resolved_command,
            cwd=str(Path(cwd)) if cwd else None,
            capture_output=True,
            text=True,
            shell=shell,
            timeout=action_def.get("timeout", 600),
        )
        status = "completed" if completed.returncode == 0 else "failed"
        return {
            "status": status,
            "summary": f"{action} {'succeeded' if status == 'completed' else 'failed'} for {target['name']}",
            "returncode": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-12000:],
            "command": command,
            "resolved_command": resolved_command,
            "cwd": cwd,
            "run_in_wsl": run_in_wsl,
            "wsl_distro": wsl_distro,
        }

    def _run_vast_action(self, target: dict, action: str, action_def: dict, payload: dict) -> dict:
        config = target.get("config", {})
        instance_id = self._require_int(config.get("instance_id"), "instance_id")
        if action == "start":
            provider_result = vast.start_instance(instance_id)
        elif action == "stop":
            provider_result = vast.stop_instance(instance_id)
        elif action == "restart":
            provider_result = vast.restart_instance(instance_id)
        elif action == "sync":
            ssh_details = vast.get_ssh_details(instance_id)
            provider_result = ssh_details
            config_updates = {
                "instance_id": str(ssh_details["instance_id"]),
                "ssh_host": ssh_details["ssh_host"],
                "ssh_port": str(ssh_details["ssh_port"]),
            }
            return {
                "status": "completed",
                "summary": f"Synchronized live Vast connection info for {target['name']}",
                "instance_id": instance_id,
                "resolved_inputs": {"instance_id": instance_id},
                "provider_result": provider_result,
                "config_updates": config_updates,
            }
        elif action == "connect":
            ssh_details = vast.get_ssh_details(instance_id)
            ssh_command = vast.build_ssh_command(ssh_details["ssh_host"], ssh_details["ssh_port"])
            launch_result = self._launch_ssh_terminal(ssh_command)
            return {
                "status": "completed" if launch_result.get("launched") else "failed",
                "summary": f"Prepared SSH connection for {target['name']}",
                "instance_id": instance_id,
                "resolved_inputs": {"instance_id": instance_id},
                "provider_result": ssh_details,
                "ssh_command": ssh_command,
                "terminal_launch": launch_result,
                "config_updates": {
                    "instance_id": str(ssh_details["instance_id"]),
                    "ssh_host": ssh_details["ssh_host"],
                    "ssh_port": str(ssh_details["ssh_port"]),
                },
            }
        elif action == "destroy":
            provider_result = vast.destroy_instance(instance_id)
        elif action == "redeploy":
            ssh_host = payload.get("ssh_host") or config.get("ssh_host")
            ssh_port = self._require_int(payload.get("ssh_port") or config.get("ssh_port"), "ssh_port")
            if not ssh_host:
                raise ValueError("ssh_host is required for redeploy")
            provider_result = vast.redeploy_code(ssh_host, ssh_port)
        else:
            raise ValueError(f"Unsupported vast action: {action}")
        status = "completed" if provider_result else "failed"
        return {
            "status": status,
            "summary": f"{action} requested for {target['name']}",
            "instance_id": instance_id,
            "resolved_inputs": {
                "instance_id": instance_id,
                "ssh_host": payload.get("ssh_host") or config.get("ssh_host"),
                "ssh_port": payload.get("ssh_port") or config.get("ssh_port"),
            },
            "provider_result": provider_result,
        }

    def _launch_ssh_terminal(self, ssh_command: str) -> dict:
        try:
            if os.name == "nt":
                subprocess.Popen(["powershell", "-NoExit", "-Command", ssh_command])
                return {"launched": True, "mode": "powershell"}

            if os.environ.get("WSL_DISTRO_NAME"):
                distro = os.environ["WSL_DISTRO_NAME"]
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "wsl.exe", "-d", distro, "bash", "-lc", f"{ssh_command}; exec bash"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {"launched": True, "mode": "wsl-terminal", "distro": distro}
        except Exception as exc:
            return {"launched": False, "error": str(exc)}
        return {"launched": False, "error": "No terminal launcher configured", "ssh_command": ssh_command}

    def _require_int(self, raw_value, field_name: str) -> int:
        if raw_value in (None, ""):
            raise ValueError(f"{field_name} is required")
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer") from exc

    def _wrap_wsl_command(self, command: str, cwd: str | None, wsl_distro: str | None):
        prefix = ""
        if cwd:
            prefix = f"cd {self._windows_to_wsl_path(cwd)} && "
        if os.name != "nt":
            return ["bash", "-lc", prefix + command]

        wrapped = ["wsl"]
        if wsl_distro:
            wrapped.extend(["-d", wsl_distro])
        wrapped.extend(["bash", "-lc", prefix + command])
        return wrapped

    def _windows_to_wsl_path(self, raw_path: str) -> str:
        normalized = raw_path.replace("\\", "/")
        if len(normalized) >= 2 and normalized[1] == ":":
            drive = normalized[0].lower()
            tail = normalized[2:]
            if tail.startswith("/"):
                return f"/mnt/{drive}{tail}"
            return f"/mnt/{drive}/{tail}"
        return normalized

    def _as_bool(self, raw_value, default=False):
        if raw_value is None:
            return default
        if isinstance(raw_value, bool):
            return raw_value
        value = str(raw_value).strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off", ""}:
            return False
        return default

    def _render_command_template(self, command: str, values: dict) -> str:
        rendered = command
        for key, value in values.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return rendered
