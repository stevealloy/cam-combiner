import json
from typing import Any

SESSION_FILENAME = "cam_session.json"
_VERSION = 1


def save_session(output_dir: str, state: dict, enabled_feature_names: list) -> str:
    data = {
        "version": _VERSION,
        "base":        state.get("base"),
        "shared_dir":  state.get("shared_dir"),
        "cfg_path":    state.get("cfg_path"),
        "output_base": state.get("output_base"),
        "params":      {k: v for k, v in state.get("params", {}).items()},
        "enabled_features": list(enabled_feature_names),
    }
    path = output_dir.rstrip("/\\") + "/" + SESSION_FILENAME
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def load_session(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
