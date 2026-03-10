import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class RegistryService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.targets_path = data_dir / "targets.json"
        self.jobs_path = data_dir / "jobs.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.targets_path.exists():
            self.targets_path.write_text("[]\n", encoding="utf-8")
        if not self.jobs_path.exists():
            self.jobs_path.write_text("[]\n", encoding="utf-8")

    def _read_json(self, path: Path) -> list[dict]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: list[dict]) -> None:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def list_targets(self) -> list[dict]:
        return self._read_json(self.targets_path)

    def get_target(self, target_id: str) -> dict | None:
        for target in self.list_targets():
            if target["id"] == target_id:
                return target
        return None

    def create_target(self, preset: dict, overrides: dict) -> dict:
        targets = self.list_targets()
        now = datetime.now(timezone.utc).isoformat()
        target = {
            "id": uuid.uuid4().hex[:12],
            "name": overrides.get("name") or preset["name"],
            "preset_id": preset["id"],
            "target_type": preset["target_type"],
            "project": preset["project"],
            "description": preset.get("description", ""),
            "config": {**preset.get("defaults", {}), **overrides},
            "config_fields": preset.get("config_fields", []),
            "action_fields": preset.get("action_fields", {}),
            "actions": preset.get("actions", {}),
            "created_at": now,
            "updated_at": now,
        }
        targets.append(target)
        self._write_json(self.targets_path, targets)
        return target

    def update_target(self, target_id: str, updates: dict) -> dict | None:
        targets = self.list_targets()
        for index, target in enumerate(targets):
            if target["id"] != target_id:
                continue

            now = datetime.now(timezone.utc).isoformat()
            if "name" in updates and updates["name"]:
                target["name"] = updates["name"]
            if "description" in updates:
                target["description"] = updates["description"] or ""

            config_updates = updates.get("config") or {}
            if config_updates:
                target["config"] = {**target.get("config", {}), **config_updates}

            target["updated_at"] = now
            targets[index] = target
            self._write_json(self.targets_path, targets)
            return target
        return None

    def replace_target_actions(self, target_id: str, actions: dict, action_fields: dict | None = None) -> dict | None:
        targets = self.list_targets()
        for index, target in enumerate(targets):
            if target["id"] != target_id:
                continue
            target["actions"] = actions
            if action_fields is not None:
                target["action_fields"] = action_fields
            target["updated_at"] = datetime.now(timezone.utc).isoformat()
            targets[index] = target
            self._write_json(self.targets_path, targets)
            return target
        return None

    def delete_target(self, target_id: str) -> bool:
        targets = self.list_targets()
        remaining = [target for target in targets if target["id"] != target_id]
        if len(remaining) == len(targets):
            return False
        self._write_json(self.targets_path, remaining)
        return True

    def list_jobs(self) -> list[dict]:
        jobs = self._read_json(self.jobs_path)
        return list(reversed(jobs))

    def record_job(self, target_id: str | None, action: str, result: dict) -> dict:
        jobs = self._read_json(self.jobs_path)
        job = {
            "id": uuid.uuid4().hex[:12],
            "target_id": target_id,
            "action": action,
            "status": result.get("status", "unknown"),
            "summary": result.get("summary", ""),
            "details": result,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        jobs.append(job)
        self._write_json(self.jobs_path, jobs)
        return job
