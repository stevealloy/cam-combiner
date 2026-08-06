"""Local, per-tree cache of CAMFile content-derived metadata (tool, MOP
name, coordinate/feed/speed envelope), keyed by each file's own path/size/
mtime -- lets scan_files() skip re-opening and re-regexing a file's content
on a Load when nothing about that specific file has changed since the last
scan. See docs/scan-cache-design.md.

Deliberately local-only, never written into the scanned tree itself:
ParamBuilder's own history documents a real hang from writing frequently-
rewritten small files onto a Google-Drive-synced path, and this cache has
no reason to live there anyway -- it's a pure performance cache, not shared
state, and losing it costs a slower Load, never a wrong one.

Keyed per-file rather than per-chunk/FeatureBlock: a plain (path, size,
mtime_ns) check is both simpler and finer-grained than tracking a rolled-up
digest per directory, and it falls out naturally that a restructured
directory tree (files moved to new subdirectories, folders renamed) just
looks like "new files here, old cache entries for paths that no longer
exist" -- no special-casing needed for structural changes, they're just a
higher miss rate for that Load.
"""
import hashlib
import json
import os
import tempfile


def _cache_root() -> str:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "CC2", "scan_cache")


def cache_path_for(base_dir: str, shared_dir: str = None) -> str:
    key = os.path.abspath(base_dir).lower()
    if shared_dir:
        key += "|" + os.path.abspath(shared_dir).lower()
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(_cache_root(), f"{digest}.json")


def load_cache(base_dir: str, shared_dir: str = None) -> dict:
    """Never raises -- a missing/corrupt cache just means everything is
    treated as a miss (identical to today's always-parse behavior)."""
    path = cache_path_for(base_dir, shared_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
            return {"files": {}}
        return data
    except Exception:
        return {"files": {}}


def save_cache(base_dir: str, cache: dict, shared_dir: str = None) -> None:
    """Atomic replace (temp file + os.replace) so a crash mid-write can
    never leave a corrupt cache file behind. Best-effort: a failure to save
    only costs the next Load its speedup, never correctness."""
    path = cache_path_for(base_dir, shared_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except Exception:
        pass


def file_cache_key(full_path: str) -> str:
    return os.path.normpath(full_path).replace("\\", "/").lower()


def lookup(cache: dict, full_path: str, size: int, mtime_ns: int):
    """Return the cached content-fields dict for this exact (path, size,
    mtime_ns), or None on any miss -- new file, changed file, or no cache."""
    entry = cache.get("files", {}).get(file_cache_key(full_path))
    if not entry or entry.get("size") != size or entry.get("mtime_ns") != mtime_ns:
        return None
    return entry.get("fields")


def record(new_cache: dict, full_path: str, size: int, mtime_ns: int, fields: dict) -> None:
    """Add this file's fresh-parse result to the cache being built for this
    scan. Building a fresh dict per scan_files() call (rather than mutating
    the loaded one in place) means a file that no longer exists on disk is
    simply never re-added -- stale entries drop out on their own."""
    new_cache.setdefault("files", {})[file_cache_key(full_path)] = {
        "size": size,
        "mtime_ns": mtime_ns,
        "fields": fields,
    }
