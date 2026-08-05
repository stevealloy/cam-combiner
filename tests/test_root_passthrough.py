"""
Unit tests for ROOT-PASSTHROUGH-DIRS (cam_core/planner.py::scan_files).

Builds small real directory trees under tmp_path (scan_files() walks real
disk via os.scandir, unlike CAMFile.from_lines()-based planner tests).
"""
from cam_core.planner import scan_files

TOOL_LINE = "(  TOOL 3 - Test Bit - DESC: 0.125 DIA )\n"
NC_BODY = [TOOL_LINE, "G90\n", "G0 X1.0000 Y2.0000\n", "X0Y0\n"]


def _write_nc(path, name):
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text("".join(NC_BODY), encoding="utf-8")


def _names(cam_files):
    return {f.name for f in cam_files}


class TestNoPassthroughConfigured:
    def test_default_behavior_unchanged(self, tmp_path):
        _write_nc(tmp_path / "PUPS", "pup-front-01.nc")
        files, fblocks, features, tools = scan_files(str(tmp_path))
        f = next(f for f in files if f.name == "pup-front-01.nc")
        assert f._is_root is False
        assert any(fb.name == "PUPS" for fb in fblocks)
        assert len(features) == 1


class TestRootPassthrough:
    def _build(self, tmp_path):
        _write_nc(tmp_path, "05-profile-s24-loose-01.nc")
        _write_nc(tmp_path / "PUPS", "pup-front-01.nc")
        _write_nc(tmp_path / "ScriptOutput" / "Profiles" / "s24",
                  "05-profile-s24-nested-01.nc")
        return tmp_path

    def test_nested_passthrough_files_are_root(self, tmp_path):
        base = self._build(tmp_path)
        files, fblocks, features, tools = scan_files(
            str(base), root_passthrough_dirs=["ScriptOutput"]
        )
        f = next(f for f in files if f.name == "05-profile-s24-nested-01.nc")
        assert f._is_root is True

    def test_passthrough_files_do_not_become_features(self, tmp_path):
        base = self._build(tmp_path)
        files, fblocks, features, tools = scan_files(
            str(base), root_passthrough_dirs=["ScriptOutput"]
        )
        # Only PUPS should have produced a CAMFeature -- the passthrough
        # subtree's files must land in "Base" and be skipped by
        # _scan_features() the same way loose root files already are.
        assert len(features) == 1
        assert features[0].name != ""
        assert "05-profile-s24-nested-01.nc" not in {
            cf.name for feat in features for cf in feat.get_CAM_files()
        }

    def test_no_featureblock_created_for_passthrough_subtree(self, tmp_path):
        base = self._build(tmp_path)
        files, fblocks, features, tools = scan_files(
            str(base), root_passthrough_dirs=["ScriptOutput"]
        )
        block_names = {fb.name for fb in fblocks}
        assert "PUPS" in block_names
        assert not any(name.startswith("ScriptOutput") for name in block_names)

    def test_normal_sibling_dir_still_grouped_as_feature(self, tmp_path):
        # Regression test: PUPS ("P") sorts and is therefore processed
        # before ScriptOutput ("S") in scan order. Make sure processing a
        # normal feature dir first doesn't leave scan_files.current_featureblock
        # pointed at the wrong block when the passthrough dir is handled next.
        base = self._build(tmp_path)
        files, fblocks, features, tools = scan_files(
            str(base), root_passthrough_dirs=["ScriptOutput"]
        )
        f = next(f for f in files if f.name == "pup-front-01.nc")
        assert f._is_root is False
        assert any(feat.name for feat in features)

    def test_loose_root_file_still_root(self, tmp_path):
        base = self._build(tmp_path)
        files, fblocks, features, tools = scan_files(
            str(base), root_passthrough_dirs=["ScriptOutput"]
        )
        f = next(f for f in files if f.name == "05-profile-s24-loose-01.nc")
        assert f._is_root is True

    def test_matching_is_case_insensitive(self, tmp_path):
        base = self._build(tmp_path)
        files, fblocks, features, tools = scan_files(
            str(base), root_passthrough_dirs=["scriptoutput"]
        )
        f = next(f for f in files if f.name == "05-profile-s24-nested-01.nc")
        assert f._is_root is True

    def test_passthrough_scoped_to_declared_subpath_only(self, tmp_path):
        # Declaring "ScriptOutput/Profiles" (not all of ScriptOutput) should
        # leave a sibling "ScriptOutput/Radius" dir as a normal feature dir.
        base = tmp_path
        _write_nc(base / "ScriptOutput" / "Profiles" / "s24", "05-profile-s24-01.nc")
        _write_nc(base / "ScriptOutput" / "Radius", "02-radius-r12-01.nc")
        files, fblocks, features, tools = scan_files(
            str(base), root_passthrough_dirs=["ScriptOutput/Profiles"]
        )
        profile_f = next(f for f in files if f.name == "05-profile-s24-01.nc")
        radius_f = next(f for f in files if f.name == "02-radius-r12-01.nc")
        assert profile_f._is_root is True
        assert radius_f._is_root is False
        block_names = {fb.name for fb in fblocks}
        assert any("Radius" in name for name in block_names)
        assert not any(name.startswith("ScriptOutput/Profiles") for name in block_names)
