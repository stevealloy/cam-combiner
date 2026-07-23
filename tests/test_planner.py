"""
Unit tests for cam_core/planner.py.
Uses CAMFile.from_lines() so no real .nc files are needed.
"""
import pytest
from cam_core.cam_file import CAMFile
from cam_core.planner import plan
from cam_core.jsonc_loader import normalize_legacy


TOOL_LINE = "(  TOOL 3 - Test Bit - DESC: 0.125 DIA )\n"


def _file(name: str, lines: list = None, is_root: bool = True) -> CAMFile:
    if lines is None:
        lines = [TOOL_LINE, "G90\n", "G0 X1.0000 Y2.0000\n", "X0Y0\n"]
    return CAMFile.from_lines(name, lines, is_root)


def _cfg(*output_names: str, base_entries: list = None) -> dict:
    return normalize_legacy({
        "MODEL": "test",
        "CLINE": 0,
        "CLINE_DELTA": 4,
        "MAXUNITS": 1,
        "DIRECTION": "VERTICAL",
        "OUTPUT-FILE-NAMES": list(output_names),
        "INPUT-FILE-NAME-BASES": base_entries or [],
    })


# ---------------------------------------------------------------------------
# CAMFile.from_lines
# ---------------------------------------------------------------------------

class TestFromLines:
    def test_name_is_preserved(self):
        f = _file("01-prep-s21-01.nc")
        assert f.name == "01-prep-s21-01.nc"

    def test_step_parsed_from_name(self):
        f = _file("03-frets-r7PT25-s21-01.nc")
        assert f.get_step() == "03"

    def test_step_letter_prefix_not_limited_to_a_through_g(self):
        # Matches jsonc_loader.normalize_legacy()'s OUTPUT-FILE-NAMES step regex,
        # which already accepts any letter (e.g. ThroughNeck-in's W00/W01/W02 series).
        f = _file("W01-WingPrep-01.nc")
        assert f.get_step() == "W01"

    def test_front_step(self):
        # FRONT detection only fires when no leading NN- step prefix is present
        f = _file("radius-front.nc")
        assert f.get_step() == "FRONT"

    def test_back_step(self):
        f = _file("cleanup-back.nc")
        assert f.get_step() == "BACK"

    def test_is_root_true(self):
        f = _file("01-prep.nc", is_root=True)
        assert f._is_root is True
        assert f.get_feature_name() == ""

    def test_is_root_false_gives_feature_name(self):
        f = _file("01-prep-neck-01.nc", is_root=False)
        assert f._is_root is False
        assert f.get_feature_name() != ""

    def test_tool_parsed_from_lines(self):
        f = _file("01-prep.nc", [TOOL_LINE, "G90\n"])
        assert f.get_toolnum() != 0

    def test_home_line_normalized(self):
        f = _file("01-prep.nc", ["G0 X0Y0\n", "G0 X1 Y2\n"])
        assert "HOME\n" in f._lines


# ---------------------------------------------------------------------------
# plan() — file selection
# ---------------------------------------------------------------------------

class TestPlanSelection:
    def test_exact_match_selects_file(self):
        f = _file("01-backprep-s21-ftPT30-01.nc")
        cfg = _cfg("01-out.nc", base_entries=[
            {"name": "01-backprep-s21-ftPT30", "required": "True", "condition": "None"}
        ])
        _, by_step = plan(cfg, {}, [f], "", [], [])
        assert f in by_step.get("01", [])

    def test_wildcard_match_selects_file(self):
        f = _file("01-backprep-AnyScale-ftPT30-01.nc")
        cfg = _cfg("01-out.nc", base_entries=[
            {"name": "01-backprep-<Scale>-ftPT30", "required": "True", "condition": "None"}
        ])
        params = {"Scale": "s21"}
        cfg["parameters"] = [{"name": "Scale", "wildcard": "AnyScale", "values": ["s21"], "default": "s21"}]
        _, by_step = plan(cfg, params, [f], "", [], [])
        assert f in by_step.get("01", [])

    def test_exact_and_wildcard_files_both_selected(self):
        # A file matching the literal parameter value and a separate file matching
        # the wildcard placeholder both exist. Wildcards are treated as base files,
        # so both should be selected rather than the exact match suppressing the
        # wildcard file.
        exact = _file("01-backprep-s21-ftPT30-01.nc")
        wild = _file("01-backprep-AnyScale-ftPT30-01.nc")
        cfg = _cfg("01-out.nc", base_entries=[
            {"name": "01-backprep-<Scale>-ftPT30", "required": "True", "condition": "None"}
        ])
        params = {"Scale": "s21"}
        cfg["parameters"] = [{"name": "Scale", "wildcard": "AnyScale", "values": ["s21"], "default": "s21"}]
        _, by_step = plan(cfg, params, [exact, wild], "", [], [])
        assert exact in by_step.get("01", [])
        assert wild in by_step.get("01", [])

    def test_wildcard_files_ordered_as_if_resolved(self):
        # The wildcard file's un-templated suffix ("AaronV") sorts alphabetically
        # before the exact file's suffix ("Gibson") once the wildcard token is
        # resolved to its real value. Output order should follow that resolved
        # sequence rather than grouping the exact match first just because it
        # was found on an earlier attempt level.
        exact = _file("05-profile-s25PT5-nw43-Gibson-NFrets22-01.nc")
        wild = _file("05-profile-AnyScale-nw43-AaronV-NFrets24-01.nc")
        cfg = _cfg("05-out.nc", base_entries=[
            {"name": "05-profile-<Scale>", "required": "True", "condition": "None"}
        ])
        params = {"Scale": "s25PT5"}
        cfg["parameters"] = [{"name": "Scale", "wildcard": "AnyScale", "values": ["s25PT5"], "default": "s25PT5"}]
        _, by_step = plan(cfg, params, [exact, wild], "", [], [])
        assert by_step.get("05", []) == [wild, exact]

    def test_unmatched_file_not_selected(self):
        f = _file("01-something-else-01.nc")
        cfg = _cfg("01-out.nc", base_entries=[
            {"name": "01-backprep-s21", "required": "False", "condition": "None"}
        ])
        _, by_step = plan(cfg, {}, [f], "", [], [])
        assert f not in by_step.get("01", [])

    def test_condition_false_skips_entry(self):
        f = _file("03-radius-r7PT25-s21-final-01.nc")
        cfg = _cfg("03-out.nc", base_entries=[
            {"name": "03-radius-r7PT25-s21-final", "required": "False", "condition": "PauseAfterInlay"}
        ])
        cfg["parameters"] = [{"name": "PauseAfterInlay", "values": ["True", "False"], "default": "False"}]
        _, by_step = plan(cfg, {"PauseAfterInlay": False}, [f], "", [], [])
        assert f not in by_step.get("03", [])

    def test_condition_true_includes_entry(self):
        f = _file("03-radius-r7PT25-s21-final-01.nc")
        cfg = _cfg("03-out.nc", base_entries=[
            {"name": "03-radius-r7PT25-s21-final", "required": "False", "condition": "PauseAfterInlay"}
        ])
        cfg["parameters"] = [{"name": "PauseAfterInlay", "values": ["True", "False"], "default": "True"}]
        _, by_step = plan(cfg, {"PauseAfterInlay": True}, [f], "", [], [])
        assert f in by_step.get("03", [])

    def test_multiple_steps_routed_correctly(self):
        f01 = _file("01-prep-01.nc")
        f03 = _file("03-frets-01.nc")
        cfg = _cfg("01-out.nc", "03-out.nc", base_entries=[
            {"name": "01-prep", "required": "False", "condition": "None"},
            {"name": "03-frets", "required": "False", "condition": "None"},
        ])
        _, by_step = plan(cfg, {}, [f01, f03], "", [], [])
        assert f01 in by_step.get("01", [])
        assert f03 in by_step.get("03", [])
        assert f01 not in by_step.get("03", [])

    def test_is_root_flag_used_for_feat_ordering(self):
        root_f = _file("01-prep-01.nc", is_root=True)
        feat_f = _file("01-prep-neck-01.nc", is_root=False)
        cfg = _cfg("01-out.nc", base_entries=[
            {"name": "01-prep", "required": "False", "condition": "None"},
        ])
        _, by_step = plan(cfg, {}, [root_f, feat_f], "", [], [])
        step_files = by_step.get("01", [])
        assert root_f in step_files
