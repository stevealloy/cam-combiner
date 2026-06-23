"""
Integration tests using real Testing/ fixture data.

Fixed tests run against Testing/Fingerboards-in specifically.
Multi-dir tests (TestMultiDir) are parametrized over every *-in directory
found in Testing/ (default) or under --base-dir if supplied on the CLI:

    python -m pytest tests/test_integration.py -v
    python -m pytest tests/test_integration.py -v --base-dir "G:/path/to/jobs"
"""
import io
import os
import pytest
from pathlib import Path

from cam_core.planner import scan_files, plan
from cam_core.jsonc_loader import load_config_file, normalize_legacy
from cam_core.writer import write_output_file

FIXTURES = Path(__file__).parent.parent / "Testing"
FB_IN    = FIXTURES / "Fingerboards-in"
FB_CFG   = FB_IN / "fixture_config.txt"
FB_OUT   = FIXTURES / "Fingerboards-out"
SHARED   = FIXTURES / "SharedGCode"

pytestmark = pytest.mark.skipif(
    not FB_IN.exists(),
    reason="Testing/Fingerboards-in fixture not present"
)


@pytest.fixture(scope="module")
def fb_cfg():
    return normalize_legacy(load_config_file(str(FB_CFG)))


@pytest.fixture(scope="module")
def fb_default_params(fb_cfg):
    params = {"Lefty": False, "unit_1_only": False}
    for p in fb_cfg.get("parameters", []):
        name = p.get("name")
        if name:
            params[name] = p.get("default")
    return params


@pytest.fixture(scope="module")
def fb_scan():
    return scan_files(str(FB_IN))


@pytest.fixture(scope="module")
def fb_scan_with_shared():
    if not SHARED.exists():
        pytest.skip("Testing/SharedGCode not present")
    return scan_files(str(FB_IN), shared_dir=str(SHARED))


# ---------------------------------------------------------------------------
# scan_files
# ---------------------------------------------------------------------------

class TestScanFiles:
    def test_returns_files(self, fb_scan):
        files, _, _, _ = fb_scan
        assert len(files) > 0

    def test_base_block_present(self, fb_scan):
        _, blocks, _, _ = fb_scan
        names = [b.name for b in blocks]
        assert "Base" in names

    def test_options_block_present(self, fb_scan):
        _, blocks, _, _ = fb_scan
        names = [b.name for b in blocks]
        assert "Options" in names

    def test_tools_detected(self, fb_scan):
        _, _, _, tools = fb_scan
        assert len(tools) > 0

    def test_features_detected(self, fb_scan):
        _, _, features, _ = fb_scan
        assert len(features) > 0

    def test_shared_dir_blocks_prefixed(self, fb_scan_with_shared):
        _, blocks, _, _ = fb_scan_with_shared
        names = [b.name for b in blocks]
        shared_blocks = [n for n in names if n.startswith("Shared/")]
        assert len(shared_blocks) > 0

    def test_shared_root_files_are_root(self, fb_scan_with_shared):
        files, _, _, _ = fb_scan_with_shared
        # Any file whose _dir is inside SharedGCode root (not a subdirectory)
        shared_root = str(SHARED)
        shared_root_files = [f for f in files if os.path.normpath(f._dir) == os.path.normpath(shared_root)]
        for f in shared_root_files:
            assert f._is_root, f"{f.name} from shared root should have _is_root=True"


# ---------------------------------------------------------------------------
# plan()
# ---------------------------------------------------------------------------

class TestPlan:
    def test_plan_returns_outputs(self, fb_cfg, fb_default_params, fb_scan):
        files, blocks, features, _ = fb_scan
        resolved, by_step = plan(fb_cfg, fb_default_params, files, str(FB_IN), blocks, [])
        assert len(resolved) > 0

    def test_step_01_has_files(self, fb_cfg, fb_default_params, fb_scan):
        files, blocks, features, _ = fb_scan
        _, by_step = plan(fb_cfg, fb_default_params, files, str(FB_IN), blocks, [])
        assert "01" in by_step
        assert len(by_step["01"]) > 0

    def test_step_02_has_files(self, fb_cfg, fb_default_params, fb_scan):
        files, blocks, features, _ = fb_scan
        _, by_step = plan(fb_cfg, fb_default_params, files, str(FB_IN), blocks, [])
        assert "02" in by_step
        assert len(by_step["02"]) > 0

    def test_all_selected_files_are_root(self, fb_cfg, fb_default_params, fb_scan):
        """With no features enabled, every selected file should be a root file."""
        files, blocks, _, _ = fb_scan
        _, by_step = plan(fb_cfg, fb_default_params, files, str(FB_IN), blocks, [])
        for step, step_files in by_step.items():
            for f in step_files:
                assert f._is_root, f"{f.name} step={step} should be a root file when no features enabled"


# ---------------------------------------------------------------------------
# write_output_file (end-to-end through real CAMFiles)
# ---------------------------------------------------------------------------

class TestWriteIntegration:
    def test_write_produces_begin_end_for_each_file(self, fb_cfg, fb_default_params, fb_scan):
        files, blocks, _, _ = fb_scan
        _, by_step = plan(fb_cfg, fb_default_params, files, str(FB_IN), blocks, [])

        cline       = fb_cfg["CLINE"]
        cline_delta = float(fb_cfg["CLINE_DELTA"])
        direction   = fb_cfg["DIRECTION"]
        max_units   = fb_cfg["MAXUNITS"]

        for f in files:
            f.create_unit_code(max_units, cline_delta, direction)

        step_files = by_step.get("01", [])
        assert step_files, "Need at least one step-01 file to test writing"

        buf = io.StringIO()
        for f in step_files:
            write_output_file(f, f.name, buf, 1, max_units, False, f.get_toolnum(), False,
                              cline, cline_delta, direction)

        out = buf.getvalue()
        assert out.count("( BEGIN FILE") == len(step_files)
        assert out.count("( END FILE") == len(step_files)


# ---------------------------------------------------------------------------
# Multi-directory tests
#
# `in_dir` is parametrized by conftest.py over every *-in directory found
# under --base-dir (default: Testing/).  Each test runs once per directory.
# ---------------------------------------------------------------------------

def _load_dir(in_dir: Path):
    """Return (cfg, default_params, scan_result) for an *-in directory."""
    cfg = normalize_legacy(load_config_file(str(in_dir / "fixture_config.txt")))
    params = {"Lefty": False, "unit_1_only": False}
    for p in cfg.get("parameters", []):
        name = p.get("name")
        if name:
            params[name] = p.get("default")

    shared = in_dir.parent / "SharedGCode"
    scan = scan_files(str(in_dir), shared_dir=str(shared) if shared.is_dir() else None)
    return cfg, params, scan


class TestMultiDir:
    """Runs once per *-in directory; in_dir is injected by conftest parametrize."""

    def test_config_loads(self, in_dir):
        cfg = normalize_legacy(load_config_file(str(in_dir / "fixture_config.txt")))
        assert cfg.get("MODEL"), f"{in_dir.name}: config missing MODEL"
        assert "CLINE" in cfg, f"{in_dir.name}: config missing CLINE"

    def test_scan_returns_files(self, in_dir):
        cfg, params, (files, blocks, features, tools) = _load_dir(in_dir)
        assert len(files) > 0, f"{in_dir.name}: scan returned no files"

    def test_base_block_present(self, in_dir):
        cfg, params, (files, blocks, features, tools) = _load_dir(in_dir)
        names = [b.name for b in blocks]
        assert "Base" in names, f"{in_dir.name}: no Base block"

    def test_tools_detected(self, in_dir):
        cfg, params, (files, blocks, features, tools) = _load_dir(in_dir)
        assert len(tools) > 0, f"{in_dir.name}: no tools detected"

    def test_plan_runs_without_error(self, in_dir):
        cfg, params, (files, blocks, features, tools) = _load_dir(in_dir)
        resolved, by_step = plan(cfg, params, files, str(in_dir), blocks, [])
        assert len(resolved) > 0, f"{in_dir.name}: plan returned no outputs"

    def test_plan_selects_at_least_one_file(self, in_dir):
        cfg, params, (files, blocks, features, tools) = _load_dir(in_dir)
        _, by_step = plan(cfg, params, files, str(in_dir), blocks, [])
        total = sum(len(v) for v in by_step.values())
        assert total > 0, f"{in_dir.name}: plan selected no files at all"

    def test_write_pipeline_runs(self, in_dir):
        cfg, params, (files, blocks, features, tools) = _load_dir(in_dir)
        _, by_step = plan(cfg, params, files, str(in_dir), blocks, [])

        cline       = cfg["CLINE"]
        cline_delta = float(cfg["CLINE_DELTA"])
        direction   = cfg["DIRECTION"]
        max_units   = cfg["MAXUNITS"]

        for f in files:
            f.create_unit_code(max_units, cline_delta, direction)

        buf = io.StringIO()
        for step_files in by_step.values():
            for f in step_files:
                write_output_file(f, f.name, buf, 1, max_units, False,
                                  f.get_toolnum(), False, cline, cline_delta, direction)

        out = buf.getvalue()
        total_files = sum(len(v) for v in by_step.values())
        assert out.count("( BEGIN FILE") == total_files, \
            f"{in_dir.name}: BEGIN count mismatch"
        assert out.count("( END FILE") == total_files, \
            f"{in_dir.name}: END count mismatch"
