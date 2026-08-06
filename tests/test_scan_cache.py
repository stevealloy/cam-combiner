"""
Unit tests for cam_core/scan_cache.py and its integration into
cam_core/planner.py::scan_files() -- the Tier A "skip re-parsing an
unchanged file's content" cache. See docs/scan-cache-design.md.
"""
import json
import os
import time

from cam_core import scan_cache
from cam_core.planner import scan_files

TOOL_LINE = "(  TOOL 3 - Test Bit - DESC: 0.125 DIA )\n"


def _write_nc(path, name, lines=None):
    path.mkdir(parents=True, exist_ok=True)
    body = lines if lines is not None else [TOOL_LINE, "G90\n", "G0 X1.0000 Y2.0000\n"]
    (path / name).write_text("".join(body), encoding="utf-8")


class TestCachePathAndIO:
    def test_path_is_deterministic(self, tmp_path):
        p1 = scan_cache.cache_path_for(str(tmp_path))
        p2 = scan_cache.cache_path_for(str(tmp_path))
        assert p1 == p2

    def test_path_differs_by_shared_dir(self, tmp_path):
        p1 = scan_cache.cache_path_for(str(tmp_path))
        p2 = scan_cache.cache_path_for(str(tmp_path), shared_dir=str(tmp_path / "shared"))
        assert p1 != p2

    def test_load_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        cache = scan_cache.load_cache(str(tmp_path / "nonexistent-base"))
        assert cache == {"files": {}}

    def test_load_corrupt_returns_empty_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = str(tmp_path / "base")
        path = scan_cache.cache_path_for(base)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ not valid json")
        cache = scan_cache.load_cache(base)
        assert cache == {"files": {}}

    def test_save_then_load_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = str(tmp_path / "base")
        cache = {"files": {"x/y.nc": {"size": 1, "mtime_ns": 2, "fields": {"a": 1}}}}
        scan_cache.save_cache(base, cache)
        loaded = scan_cache.load_cache(base)
        assert loaded == cache

    def test_save_is_atomic_no_leftover_tmp_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = str(tmp_path / "base")
        scan_cache.save_cache(base, {"files": {}})
        cache_dir = os.path.dirname(scan_cache.cache_path_for(base))
        leftovers = [f for f in os.listdir(cache_dir) if f.endswith(".tmp")]
        assert leftovers == []


class TestLookupAndRecord:
    def test_lookup_miss_on_empty_cache(self):
        assert scan_cache.lookup({"files": {}}, "C:/a/b.nc", 10, 20) is None

    def test_record_then_lookup_hit(self):
        new_cache = {}
        scan_cache.record(new_cache, "C:/a/b.nc", 10, 20, {"tool_num": 3})
        assert scan_cache.lookup(new_cache, "C:/a/b.nc", 10, 20) == {"tool_num": 3}

    def test_lookup_miss_on_size_mismatch(self):
        new_cache = {}
        scan_cache.record(new_cache, "C:/a/b.nc", 10, 20, {"tool_num": 3})
        assert scan_cache.lookup(new_cache, "C:/a/b.nc", 99, 20) is None

    def test_lookup_miss_on_mtime_mismatch(self):
        new_cache = {}
        scan_cache.record(new_cache, "C:/a/b.nc", 10, 20, {"tool_num": 3})
        assert scan_cache.lookup(new_cache, "C:/a/b.nc", 10, 99) is None

    def test_lookup_key_is_case_insensitive_and_slash_normalized(self):
        new_cache = {}
        scan_cache.record(new_cache, r"C:\A\B.NC", 10, 20, {"tool_num": 3})
        assert scan_cache.lookup(new_cache, "c:/a/b.nc", 10, 20) == {"tool_num": 3}


class TestScanFilesCacheIntegration:
    """Exercises the real cache through scan_files() against a tmp_path tree
    -- fast, isolated equivalent of the manual timing check done against the
    real Fingerboards-in tree (~22s cold / ~0.4s warm for 4150 files)."""

    def test_second_scan_is_a_cache_hit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = tmp_path / "in"
        _write_nc(base, "01-prep-01.nc")

        files1, *_ = scan_files(str(base))
        f1 = files1[0]
        assert f1._content_loaded is True  # cold: fresh parse, content already in hand

        files2, *_ = scan_files(str(base))
        f2 = files2[0]
        assert f2._content_loaded is False  # warm: cache hit, content not loaded
        assert f2.get_tool().get_desc() == f1.get_tool().get_desc()
        assert f2.get_toolnum() == f1.get_toolnum()

    def test_cache_hit_survives_across_more_than_two_scans(self, tmp_path, monkeypatch):
        """Regression test: a hit must be re-recorded into the fresh
        new_cache each scan, or it silently evaporates after exactly one
        successful hit (new_cache previously only recorded misses)."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = tmp_path / "in"
        _write_nc(base, "01-prep-01.nc")

        scan_files(str(base))  # cold
        scan_files(str(base))  # warm: a hit, previously never re-recorded
        files, *_ = scan_files(str(base))  # would go cold again if the bug were present

        assert files[0]._content_loaded is False
        cache = scan_cache.load_cache(str(base))
        assert len(cache["files"]) == 1

    def test_changed_file_is_reparsed_not_reused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = tmp_path / "in"
        _write_nc(base, "01-prep-01.nc", [TOOL_LINE, "G0 X1.0000\n"])
        scan_files(str(base))  # populate cache

        # Ensure a distinct mtime even on coarse filesystem clocks.
        time.sleep(0.05)
        _write_nc(base, "01-prep-01.nc",
                   ["(  TOOL 7 - Different Bit - DESC: 0.250 DIA )\n", "G0 X9.0000\n"])

        files, *_ = scan_files(str(base))
        f = files[0]
        assert f._content_loaded is True  # changed -- must reparse, not trust stale cache
        assert f.get_tool().get_tool_num() == 7
        assert f.get_max_x() == 9.0

    def test_deleted_file_does_not_linger_in_saved_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = tmp_path / "in"
        _write_nc(base, "01-prep-01.nc")
        _write_nc(base, "02-prep-01.nc")
        scan_files(str(base))

        os.remove(base / "02-prep-01.nc")
        files, *_ = scan_files(str(base))
        assert {f.name for f in files} == {"01-prep-01.nc"}

        cache = scan_cache.load_cache(str(base))
        cached_names = {os.path.basename(k) for k in cache["files"]}
        assert cached_names == {"01-prep-01.nc"}

    def test_cache_hit_file_still_produces_correct_output_on_generate(self, tmp_path, monkeypatch):
        """The actual correctness-critical path: a cache-hit CAMFile (content
        not loaded at scan time) must still produce byte-identical output
        once create_unit_code()/get_output() actually need the real lines."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = tmp_path / "in"
        lines = [TOOL_LINE, "G90\n", "G0 X1.0000\n", "X0Y0\n"]
        _write_nc(base, "01-prep-01.nc", lines)

        fresh_files, *_ = scan_files(str(base))
        fresh = fresh_files[0]
        fresh.create_unit_code(1, 4.0, "VERTICAL")
        fresh_output = list(fresh.get_output(False, 0, 4.0, 1, 1, "VERTICAL", False))

        cached_files, *_ = scan_files(str(base))
        cached = cached_files[0]
        assert cached._content_loaded is False
        cached.create_unit_code(1, 4.0, "VERTICAL")
        cached_output = list(cached.get_output(False, 0, 4.0, 1, 1, "VERTICAL", False))

        assert cached_output == fresh_output

    def test_corrupt_cache_falls_back_to_full_scan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake_appdata"))
        base = tmp_path / "in"
        _write_nc(base, "01-prep-01.nc")
        scan_files(str(base))

        path = scan_cache.cache_path_for(str(base))
        with open(path, "w", encoding="utf-8") as f:
            f.write("not json at all")

        files, *_ = scan_files(str(base))
        assert len(files) == 1
        assert files[0]._content_loaded is True
