"""
Unit tests for cam_core/unit_cache.py -- the persistent per-unit render
cache used by cam_combiner_gui.py's write_output_files() to avoid
rebuilding/rezipping the IndFiles/ tree on every Generate Output click
when nothing relevant has changed. See docs/scan-cache-design.md.
"""
import os

from cam_core import unit_cache


class TestCachePathAndIO:
    def test_path_is_deterministic(self, tmp_path):
        p1 = unit_cache.cache_dir_for(str(tmp_path))
        p2 = unit_cache.cache_dir_for(str(tmp_path))
        assert p1 == p2

    def test_path_differs_by_shared_dir(self, tmp_path):
        p1 = unit_cache.cache_dir_for(str(tmp_path))
        p2 = unit_cache.cache_dir_for(str(tmp_path), shared_dir=str(tmp_path / "shared"))
        assert p1 != p2

    def test_load_missing_returns_empty(self, tmp_path):
        assert unit_cache.load_manifest(str(tmp_path / "nonexistent")) == {}

    def test_load_corrupt_returns_empty_not_raise(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "manifest.json").write_text("{ not valid json", encoding="utf-8")
        assert unit_cache.load_manifest(str(cache_dir)) == {}

    def test_save_then_load_round_trips(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        manifest = {"fixture_signature": {"CLINE": 1}, "entries": {"1/indfiles/a.nc": {"size": 1}}}
        unit_cache.save_manifest(cache_dir, manifest)
        assert unit_cache.load_manifest(cache_dir) == manifest

    def test_save_is_atomic_no_leftover_tmp_file(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        unit_cache.save_manifest(cache_dir, {"entries": {}})
        leftovers = [f for f in os.listdir(cache_dir) if f.endswith(".tmp")]
        assert leftovers == []


class TestFixtureSignatureInvalidation:
    def test_first_call_creates_fresh_manifest(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        sig = {"CLINE": 1, "CLINE_DELTA": 4, "DIRECTION": "VERTICAL", "MAXUNITS": 5}
        manifest = unit_cache.ensure_current(cache_dir, sig)
        assert manifest["fixture_signature"] == sig
        assert manifest["entries"] == {}

    def test_unchanged_signature_keeps_entries(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        sig = {"CLINE": 1, "CLINE_DELTA": 4, "DIRECTION": "VERTICAL", "MAXUNITS": 5}
        manifest = unit_cache.ensure_current(cache_dir, sig)
        unit_cache.record(manifest, "1/IndFiles/a.nc", 10, 20, False)
        unit_cache.save_manifest(cache_dir, manifest)

        manifest2 = unit_cache.ensure_current(cache_dir, sig)
        assert unit_cache.is_current(manifest2, cache_dir, "1/IndFiles/a.nc", 10, 20, False) is False  # file not actually on disk
        assert "1/indfiles/a.nc" in manifest2["entries"]

    def test_changed_signature_wipes_cache_dir_and_entries(self, tmp_path):
        cache_dir = str(tmp_path / "cache")
        sig1 = {"CLINE": 1, "CLINE_DELTA": 4, "DIRECTION": "VERTICAL", "MAXUNITS": 5}
        manifest = unit_cache.ensure_current(cache_dir, sig1)
        unit_cache.record(manifest, "1/IndFiles/a.nc", 10, 20, False)
        unit_cache.save_manifest(cache_dir, manifest)
        # Leave a real file behind too, to confirm the directory itself is wiped.
        os.makedirs(os.path.join(cache_dir, "1", "IndFiles"), exist_ok=True)
        with open(os.path.join(cache_dir, "1", "IndFiles", "a.nc"), "w") as f:
            f.write("stuff")

        sig2 = {"CLINE": 1, "CLINE_DELTA": 5, "DIRECTION": "VERTICAL", "MAXUNITS": 5}  # CLINE_DELTA changed
        manifest2 = unit_cache.ensure_current(cache_dir, sig2)
        assert manifest2["entries"] == {}
        assert not os.path.isfile(os.path.join(cache_dir, "1", "IndFiles", "a.nc"))


class TestIsCurrentAndRecord:
    def test_miss_on_empty_manifest(self, tmp_path):
        manifest = {"entries": {}}
        assert unit_cache.is_current(manifest, str(tmp_path), "1/IndFiles/a.nc", 10, 20, False) is False

    def test_hit_when_matching_and_file_present(self, tmp_path):
        manifest = {"entries": {}}
        rel = "1/IndFiles/a.nc"
        full = tmp_path / rel
        full.parent.mkdir(parents=True)
        full.write_text("content")
        unit_cache.record(manifest, rel, 10, 20, False)
        assert unit_cache.is_current(manifest, str(tmp_path), rel, 10, 20, False) is True

    def test_miss_when_file_missing_despite_matching_entry(self, tmp_path):
        manifest = {"entries": {}}
        rel = "1/IndFiles/a.nc"
        unit_cache.record(manifest, rel, 10, 20, False)
        # Never actually created on disk.
        assert unit_cache.is_current(manifest, str(tmp_path), rel, 10, 20, False) is False

    def test_miss_on_size_change(self, tmp_path):
        manifest = {"entries": {}}
        rel = "1/IndFiles/a.nc"
        full = tmp_path / rel
        full.parent.mkdir(parents=True)
        full.write_text("content")
        unit_cache.record(manifest, rel, 10, 20, False)
        assert unit_cache.is_current(manifest, str(tmp_path), rel, 999, 20, False) is False

    def test_miss_on_mtime_change(self, tmp_path):
        manifest = {"entries": {}}
        rel = "1/IndFiles/a.nc"
        full = tmp_path / rel
        full.parent.mkdir(parents=True)
        full.write_text("content")
        unit_cache.record(manifest, rel, 10, 20, False)
        assert unit_cache.is_current(manifest, str(tmp_path), rel, 10, 999, False) is False

    def test_miss_on_mirror_change(self, tmp_path):
        """A file's rendered content differs by mirror state -- a cached
        lefty=False render must not be reused for a lefty=True request."""
        manifest = {"entries": {}}
        rel = "1/IndFiles/a.nc"
        full = tmp_path / rel
        full.parent.mkdir(parents=True)
        full.write_text("content")
        unit_cache.record(manifest, rel, 10, 20, False)
        assert unit_cache.is_current(manifest, str(tmp_path), rel, 10, 20, True) is False

    def test_forget_removes_entry(self, tmp_path):
        manifest = {"entries": {}}
        rel = "1/IndFiles/a.nc"
        unit_cache.record(manifest, rel, 10, 20, False)
        unit_cache.forget(manifest, rel)
        assert manifest["entries"] == {}

    def test_rel_key_is_case_and_slash_insensitive(self, tmp_path):
        manifest = {"entries": {}}
        full = tmp_path / "1" / "IndFiles" / "a.nc"
        full.parent.mkdir(parents=True)
        full.write_text("content")
        unit_cache.record(manifest, r"1\IndFiles\a.nc", 10, 20, False)
        assert unit_cache.is_current(manifest, str(tmp_path), "1/INDFILES/A.NC".lower(), 10, 20, False) is True


class TestPruneStale:
    def test_removes_files_not_in_expected_set(self, tmp_path):
        cache_dir = str(tmp_path)
        indfiles = tmp_path / "1" / "IndFiles"
        indfiles.mkdir(parents=True)
        (indfiles / "keep.nc").write_text("a")
        (indfiles / "stale.nc").write_text("b")
        manifest = {"entries": {}}
        unit_cache.record(manifest, "1/IndFiles/stale.nc", 1, 2, False)

        removed = unit_cache.prune_stale(cache_dir, manifest, "1", "IndFiles", {"keep.nc"})

        assert removed is True
        assert (indfiles / "keep.nc").exists()
        assert not (indfiles / "stale.nc").exists()
        assert "1/indfiles/stale.nc" not in manifest["entries"]

    def test_no_op_when_nothing_stale(self, tmp_path):
        cache_dir = str(tmp_path)
        indfiles = tmp_path / "1" / "IndFiles"
        indfiles.mkdir(parents=True)
        (indfiles / "keep.nc").write_text("a")
        manifest = {"entries": {}}

        removed = unit_cache.prune_stale(cache_dir, manifest, "1", "IndFiles", {"keep.nc"})

        assert removed is False
        assert (indfiles / "keep.nc").exists()

    def test_missing_dir_is_a_no_op(self, tmp_path):
        removed = unit_cache.prune_stale(str(tmp_path), {"entries": {}}, "1", "IndFiles", {"a.nc"})
        assert removed is False


class TestFixtureSignature:
    def test_extracts_only_the_relevant_keys(self):
        cfg = {"CLINE": 1, "CLINE_DELTA": 4, "DIRECTION": "VERTICAL", "MAXUNITS": 5,
               "MODEL": "irrelevant", "DESCRIPTION": "also irrelevant"}
        sig = unit_cache.fixture_signature(cfg)
        assert sig == {"CLINE": 1, "CLINE_DELTA": 4, "DIRECTION": "VERTICAL", "MAXUNITS": 5}
