import json
from pathlib import Path


class PresetService:
    def __init__(self, presets_dir: Path):
        self.presets_dir = presets_dir

    def list_presets(self) -> list[dict]:
        presets = []
        for path in sorted(self.presets_dir.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                preset = json.load(fh)
            presets.append(preset)
        return presets

    def get_preset(self, preset_id: str) -> dict | None:
        for preset in self.list_presets():
            if preset["id"] == preset_id:
                return preset
        return None
