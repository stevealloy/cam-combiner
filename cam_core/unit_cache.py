"""
Persistent, local cache of the per-unit "individual files" (IndFiles/)
tree that write_output_files() (cam_combiner_gui.py) builds on every
Generate Output run. That loop renders every scanned CAMFile -- now
thousands once a corpus includes ROOT-PASSTHROUGH-DIRS-generated content
-- for every unit position, then zips the result, on every single click.
Almost all of that work is identical run to run: a ParamBuilder-generated
file's content never changes, and neither do the fixture-level mirror/
duplication constants (CLINE/CLINE_DELTA/DIRECTION/MAXUNITS) most of the
time.

Deliberately eager/complete, not lazily populated on demand: every
individual file needs to be available to a CNC operator regardless of
which particular combined-output selection prompted a given run, so this
cache always covers the full current corpus x full unit range -- what it
saves is redoing that work when nothing relevant has changed, not
narrowing what gets produced.

Local-only (%LOCALAPPDATA%\\CC2\\unit_cache\\), same reasoning as
scan_cache.py: never written into the scanned -in tree, and it's a pure
performance artifact -- safe to delete and rebuild at any time, never a
correctness risk.
"""
import hashlib
import json
import os
import shutil
import tempfile


def _cache_root() -> str:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "CC2", "unit_cache")


def cache_dir_for(base_dir: str, shared_dir: str = None) -> str:
    key = os.path.abspath(base_dir).lower()
    if shared_dir:
        key += "|" + os.path.abspath(shared_dir).lower()
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(_cache_root(), digest)


def _manifest_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, "manifest.json")


def load_manifest(cache_dir: str) -> dict:
    """Never raises -- a missing/corrupt manifest just means everything is
    treated as stale (identical to a cold, from-scratch build)."""
    try:
        with open(_manifest_path(cache_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_manifest(cache_dir: str, manifest: dict) -> None:
    """Atomic replace (temp file + os.replace), same pattern as
    scan_cache.py. Best-effort: a failure to save only costs the next run
    its speedup, never correctness."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            os.replace(tmp_path, _manifest_path(cache_dir))
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except Exception:
        pass


def fixture_signature(cfg: dict) -> dict:
    """The fixture-level constants every cached render depends on. A
    change to any of these invalidates the ENTIRE cache at once, no
    partial patching -- e.g. a new CLINE_DELTA changes every mirrored
    file's offset simultaneously, so nothing is worth salvaging."""
    return {
        "CLINE": cfg.get("CLINE"),
        "CLINE_DELTA": cfg.get("CLINE_DELTA"),
        "DIRECTION": cfg.get("DIRECTION"),
        "MAXUNITS": cfg.get("MAXUNITS"),
    }


def ensure_current(cache_dir: str, current_sig: dict) -> dict:
    """Load this cache dir's manifest, wiping the directory first if the
    fixture signature has changed since it was built. Returns the
    (possibly fresh) manifest, ready to read/update for this run."""
    manifest = load_manifest(cache_dir)
    if manifest.get("fixture_signature") != current_sig:
        if os.path.isdir(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)
        manifest = {"fixture_signature": current_sig, "entries": {}}
    manifest.setdefault("entries", {})
    return manifest


def _rel_key(rel_path: str) -> str:
    return rel_path.replace("\\", "/").lower()


def is_current(manifest: dict, cache_dir: str, rel_path: str, size: int, mtime_ns: int, mirror: bool) -> bool:
    """True if a previously-rendered file at rel_path (under cache_dir) is
    still valid for this exact (source size, source mtime, mirror state)
    -- i.e. it can be reused as-is, with no re-render needed."""
    entry = manifest.get("entries", {}).get(_rel_key(rel_path))
    if not entry:
        return False
    if (entry.get("size") != size or entry.get("mtime_ns") != mtime_ns
            or entry.get("mirror") != bool(mirror)):
        return False
    return os.path.isfile(os.path.join(cache_dir, rel_path))


def record(manifest: dict, rel_path: str, size: int, mtime_ns: int, mirror: bool) -> None:
    manifest.setdefault("entries", {})[_rel_key(rel_path)] = {
        "size": size, "mtime_ns": mtime_ns, "mirror": bool(mirror),
    }


def forget(manifest: dict, rel_path: str) -> None:
    manifest.get("entries", {}).pop(_rel_key(rel_path), None)


def prune_stale(cache_dir: str, manifest: dict, unit_label: str, subdir: str, expected_filenames: set) -> bool:
    """Remove any file physically present in <cache_dir>/<unit_label>/<subdir>/
    that isn't in expected_filenames -- e.g. a source file that was deleted
    or renamed since the cache was last built. Returns True if anything was
    actually removed (the caller should treat that unit as dirty)."""
    dir_path = os.path.join(cache_dir, unit_label, subdir)
    if not os.path.isdir(dir_path):
        return False
    removed = False
    for fname in os.listdir(dir_path):
        if fname in expected_filenames:
            continue
        try:
            os.remove(os.path.join(dir_path, fname))
        except OSError:
            continue
        forget(manifest, f"{unit_label}/{subdir}/{fname}")
        removed = True
    return removed
