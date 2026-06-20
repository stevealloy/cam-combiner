import json, re, os
from typing import Any, Dict, List
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

_COMMENT_RE = re.compile(r"""
    (//[^\n]*?$)       |   # line comments
    (/\*.*?\*/)            # block comments
""", re.MULTILINE | re.DOTALL | re.VERBOSE)

def _strip_trailing_commas(s: str) -> str:
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return s

def _jsonc_to_json(s: str) -> str:
    s = _COMMENT_RE.sub("", s)
    s = _strip_trailing_commas(s)
    return s

def _coerce_scalars(node):
    if isinstance(node, dict):
        return {k: _coerce_scalars(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_coerce_scalars(v) for v in node]
    if isinstance(node, str):
        t = node.strip()
        low = t.lower()
        if low in ("true","yes","y","on"):
            return True
        if low in ("false","no","n","off"):
            return False
        if low in ("none","null",""):
            return None
        try:
            if "." in t or "e" in low:
                return float(t)
            return int(t)
        except Exception:
            return node
    return node

def load_config_text(text: str, source_hint: str = "") -> Dict[str, Any]:
    try:
        j = json.loads(_jsonc_to_json(text) or "{}")
        return _coerce_scalars(j) or {}
    except Exception:
        if yaml is not None:
            try:
                y = yaml.safe_load(text) or {}
                return _coerce_scalars(y) or {}
            except Exception as e:
                raise
        raise

def load_config_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    if not f:
        return {}

    return load_config_text(txt, path)

def normalize_legacy(cfg: Dict[str, Any]) -> Dict[str, Any]:
    c = dict(cfg)
    if "INPUT-FILE-NAME-BASES" in c and "base_selection" not in c:
        c["base_selection"] = {"input_file_base_names": c["INPUT-FILE-NAME-BASES"]}
    if "OUTPUT-FILE-NAMES" in c and "outputs" not in c:
        outs = []
        for name in c["OUTPUT-FILE-NAMES"]:
            step = None
            m = re.match(r"^([A-Za-z]?\d{2})", name)
            if m:
                step = m.group(1)
            outs.append({"label": name.replace(".nc",""), "step": step or "", "name": name})
        c["outputs"] = outs
    if "PARAMETERS" in c and "parameters" not in c:
        c["parameters"] = c["PARAMETERS"]
    c.setdefault("parameters", [])
    c.setdefault("base_selection", {}).setdefault("input_file_base_names", [])
    c.setdefault("outputs", [])
    return c
