"""
Unit tests for cam_core/reachability.py.
Uses CAMFile.from_lines() so no real .nc files are needed.
"""
from cam_core.cam_file import CAMFile
from cam_core.reachability import find_unreachable_base_files


def _file(name: str) -> CAMFile:
    lines = ["( MOP:  placeholder )\n", "G90\n", "G0 X1.0000 Y2.0000\n", "X0Y0\n"]
    return CAMFile.from_lines(name, lines, is_root=True)


def _param(name, values, wildcard="", default=None):
    return {"name": name, "values": values, "wildcard": wildcard, "default": default or values[0]}


def test_value_not_in_enumeration_is_unreachable():
    # "ftPT40" isn't one of FinalThickness's enumerated values nor its wildcard --
    # no parameter selection could ever render this filename.
    f = _file("01-backprep-AnyScale-ftPT40-NOMIRROR.nc")
    entries = [{"name": "01-backprep-<Scale>-<FinalThickness>", "required": "True", "condition": "None"}]
    parameters = [
        _param("Scale", ["s21", "s24PT75"], wildcard="AnyScale"),
        _param("FinalThickness", ["ftPT35", "ftPT30", "ftPT21"], wildcard="AnyFinalThickness"),
    ]
    unreachable = find_unreachable_base_files([f], entries, parameters)
    assert f in unreachable


def test_exact_value_match_is_reachable():
    f = _file("01-backprep-s21-ftPT30-01.nc")
    entries = [{"name": "01-backprep-<Scale>-<FinalThickness>", "required": "True", "condition": "None"}]
    parameters = [
        _param("Scale", ["s21", "s24PT75"], wildcard="AnyScale"),
        _param("FinalThickness", ["ftPT35", "ftPT30", "ftPT21"], wildcard="AnyFinalThickness"),
    ]
    unreachable = find_unreachable_base_files([f], entries, parameters)
    assert f not in unreachable


def test_wildcard_match_is_reachable():
    f = _file("01-backprep-AnyScale-ftPT30-01.nc")
    entries = [{"name": "01-backprep-<Scale>-<FinalThickness>", "required": "True", "condition": "None"}]
    parameters = [
        _param("Scale", ["s21", "s24PT75"], wildcard="AnyScale"),
        _param("FinalThickness", ["ftPT35", "ftPT30", "ftPT21"], wildcard="AnyFinalThickness"),
    ]
    unreachable = find_unreachable_base_files([f], entries, parameters)
    assert f not in unreachable


def test_value_with_embedded_dash_is_handled_correctly():
    # A parameter value containing its own literal "-" (e.g. "Heel-Adjust") must
    # not break structural matching the way naive '-'-splitting would.
    f = _file("02-tr-Heel-Adjust-s21-01.nc")
    entries = [{"name": "02-tr-<TR>-<Scale>", "required": "False", "condition": "None"}]
    parameters = [
        _param("TR", ["Standard", "Heel-Adjust"], wildcard="AnyTR"),
        _param("Scale", ["s21", "s24PT75"], wildcard="AnyScale"),
    ]
    unreachable = find_unreachable_base_files([f], entries, parameters)
    assert f not in unreachable


def test_never_satisfiable_condition_makes_file_unreachable():
    # Two entries share a pattern name; the one condition that could ever match
    # this file's exact tokens is permanently False for every value of the
    # condition's own parameter, so no run could ever select it.
    f = _file("03-radius-r12-s21-final.nc")
    entries = [
        {"name": "03-radius-<Radius>-<Scale>-final", "required": "True", "condition": "NeverTrue"},
    ]
    parameters = [
        _param("Radius", ["r12"], wildcard="AnyRadius"),
        _param("Scale", ["s21"], wildcard="AnyScale"),
        _param("NeverTrue", ["False"], wildcard="", default="False"),
    ]
    unreachable = find_unreachable_base_files([f], entries, parameters)
    assert f in unreachable


def test_condition_satisfiable_makes_file_reachable():
    f = _file("03-radius-r12-s21-final.nc")
    entries = [
        {"name": "03-radius-<Radius>-<Scale>-final", "required": "True", "condition": "SometimesTrue"},
    ]
    parameters = [
        _param("Radius", ["r12"], wildcard="AnyRadius"),
        _param("Scale", ["s21"], wildcard="AnyScale"),
        _param("SometimesTrue", ["True", "False"], wildcard="", default="False"),
    ]
    unreachable = find_unreachable_base_files([f], entries, parameters)
    assert f not in unreachable


def test_none_sentinel_only_reachable_combo_is_still_unreachable():
    # This file's own Radius segment literally IS the "rNone" sentinel -- the
    # only way to structurally match it is choosing Radius="rNone", but that
    # value triggers planner's "satisfied with 0 files" skip, so it can never
    # actually be selected in a real run.
    f = _file("02-radius-rNone-AnyScale-final.nc")
    entries = [{"name": "02-radius-<Radius>-<Scale>-final", "required": "True", "condition": "None"}]
    parameters = [
        _param("Radius", ["r12", "rNone"], wildcard="AnyRadius"),
        _param("Scale", ["s21"], wildcard="AnyScale"),
    ]
    unreachable = find_unreachable_base_files([f], entries, parameters)
    assert f in unreachable


def test_checks_all_entries_not_just_the_first():
    f = _file("04-frets-r12-s21-01.nc")
    entries = [
        {"name": "03-radius-<Radius>-<Scale>-final", "required": "True", "condition": "None"},
        {"name": "04-frets-<Radius>-<Scale>", "required": "True", "condition": "None"},
    ]
    parameters = [
        _param("Radius", ["r12"], wildcard="AnyRadius"),
        _param("Scale", ["s21"], wildcard="AnyScale"),
    ]
    unreachable = find_unreachable_base_files([f], entries, parameters)
    assert f not in unreachable


def test_multiple_files_mixed_reachability():
    dead = _file("01-backprep-AnyScale-ftPT99-01.nc")
    alive = _file("01-backprep-s21-ftPT30-01.nc")
    entries = [{"name": "01-backprep-<Scale>-<FinalThickness>", "required": "True", "condition": "None"}]
    parameters = [
        _param("Scale", ["s21"], wildcard="AnyScale"),
        _param("FinalThickness", ["ftPT30"], wildcard="AnyFinalThickness"),
    ]
    unreachable = find_unreachable_base_files([dead, alive], entries, parameters)
    assert dead in unreachable
    assert alive not in unreachable
