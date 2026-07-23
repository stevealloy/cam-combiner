import re
from typing import Dict, List, Tuple

from cam_core.cam_file import CAMFile

# Parametric-looking segments to strip from a file's family tag (get_family_tag(), itself
# already stripped of step-prefix/NODUP/NOMIRROR/front-back/end-start/run-number) so files
# that vary only by scale/radius/depth-code/fret-count/wildcard placeholder still land in
# the same family group. Deliberately generic (no brand/customer names hardcoded) since
# this runs across every model directory, not just one:
#   - s24, s24PT75, r12, r9PT5, nw43       (1-3 letter prefix + digits, optional PT-code)
#   - idPT09, ftPT30, sdNone               (id/ft/sd + PT-code or "None")
#   - PT092, PT375                         (bare PT-code)
#   - NFrets24, Frets24                    (fret count)
#   - AnyScale, AnyCustomer, AnyNutDepth    (the fixture_config.txt wildcard convention)
_PARAM_SEGMENT_RE = re.compile(
    r"^(?:"
    r"[a-z]{1,3}\d+(?:PT\d+)?"
    r"|(?:id|ft|sd)(?:PT\d+|None)"
    r"|PT\d+"
    r"|N?Frets?\d+"
    r"|Any[A-Za-z]+"
    r")$",
    re.IGNORECASE,
)


def _family_key(f: CAMFile) -> str:
    segs = [s for s in f.get_family_tag().split("-") if s and not _PARAM_SEGMENT_RE.fullmatch(s)]
    return "-".join(segs)


_SEGMENT_SUFFIX_RE = re.compile(r"^[a-z](?:-\d+)?$")


def check_stale_headers(cam_files: List[CAMFile]) -> List[str]:
    """Flag files whose ( MOP: ... ) header no longer matches their own filename --
    almost always a sign the file was copied/renamed and the header was never refreshed.

    A multi-op file (see check_multi_op_files) is expected to have its MOP: name equal
    to <filename stem><a single trailing letter, e.g. 'a'> -- that's the normal way its
    first concatenated segment gets named, not a stale header, so it's excluded here.
    """
    warnings = []
    for f in cam_files:
        mop = f.get_mop_name()
        if mop is None:
            continue
        stem = f.name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if mop == stem:
            continue
        if len(f.get_op_markers()) > 1 and mop.startswith(stem) and _SEGMENT_SUFFIX_RE.match(mop[len(stem):]):
            continue
        warnings.append(f'{f.name}: MOP header says "{mop}", filename is "{stem}"')
    return warnings


def check_multi_op_files(cam_files: List[CAMFile]) -> List[str]:
    """Flag files that contain more than one concatenated operation sharing a single
    TOOL declaration (detected via multiple bare '( <name>)' operation-boundary comments).
    Not necessarily a problem -- this is a deliberate way to combine passes into one file
    -- but worth surfacing since editing/verifying such a file means checking every
    segment, and it explains why its MOP: header won't literally match the filename."""
    warnings = []
    for f in cam_files:
        markers = f.get_op_markers()
        if len(markers) > 1:
            warnings.append(f"{f.name}: {len(markers)} concatenated operations in one file -- {markers}")
    return warnings


def check_below_zero(cam_files: List[CAMFile]) -> List[str]:
    """Flag files that cut below the Z0 reference plane -- almost never intentional."""
    warnings = []
    for f in cam_files:
        z = f.get_min_z()
        if z is not None and z < 0:
            warnings.append(f"{f.name}: cuts below Z0 (min Z = {z:.4f})")
    return warnings


def check_missing_tool(cam_files: List[CAMFile]) -> List[str]:
    """Flag files with real toolpath geometry but no TOOL declaration -- the machine
    would run whatever tool happened to already be loaded, silently."""
    warnings = []
    for f in cam_files:
        if f.get_tool() is None and f.has_coordinates():
            warnings.append(f"{f.name}: has toolpath geometry but no TOOL declaration")
    return warnings


def _group_by_family_and_run(cam_files: List[CAMFile]) -> Dict[Tuple[str, str, str], List[CAMFile]]:
    """Group files by (family, step, run-suffix): family is the operation identity with
    scale/radius/depth-code/fret-count/wildcard tokens stripped out (see _family_key),
    step is the file's step prefix, and run-suffix is the '-01'/'-02'/... pass index.

    Step is part of the key so a legitimate multi-stage pipeline sharing one family name
    across steps (e.g. Fingerboards-in's frets family: T15 fretkerf-scoring at steps 03/04,
    then T38 aggregate-saw at step 06) is never compared against itself as if the two
    stages should use the same tool -- only files at the *same* step, same family, same
    run-suffix are expected to be interchangeable. Run-suffix is kept separate for the
    same reason within a single step (e.g. -01=T11 rough/-02=T5 finish).

    This is a coarser, higher-recall grouping than CAMFeature's get_feature_name() (which
    only strips a handful of structural markers and returns "" for root/base files) -- it's
    what lets a check reach the bulk of a directory's numbered base-step files (profile,
    frets, radius, backprep, nutslot, ...), not just files inside Options/-style feature
    subfolders.
    """
    groups: Dict[Tuple[str, str, str], List[CAMFile]] = {}
    for f in cam_files:
        family = _family_key(f)
        if not family:
            continue
        key = (family, f.get_step(), f.get_run_suffix())
        groups.setdefault(key, []).append(f)
    return {k: v for k, v in groups.items() if len(v) > 1}


def check_tool_consistency_within_feature(cam_files: List[CAMFile]) -> List[str]:
    """Within each (family, step, run-suffix) group, every file should use the same tool --
    it's the same operation just parameterized differently (scale, radius, fret count...)."""
    warnings = []
    for (family, step, run), files in _group_by_family_and_run(cam_files).items():
        by_tool = {}
        for f in files:
            t = f.get_tool()
            if t is None:
                continue
            by_tool.setdefault((t.get_tool_num(), t.get_desc()), []).append(f.name)
        if len(by_tool) > 1:
            detail = "; ".join(f"T{tnum} ({desc}): {names}" for (tnum, desc), names in by_tool.items())
            warnings.append(f"family '{family}' step '{step}' run '{run}': inconsistent tool across {len(files)} files -- {detail}")
    return warnings


def check_feed_speed_consistency_within_feature(cam_files: List[CAMFile]) -> List[str]:
    """Within each (family, step, run-suffix) group, feed rates and spindle speed should match."""
    warnings = []
    for (family, step, run), files in _group_by_family_and_run(cam_files).items():
        by_fs = {}
        for f in files:
            key = (f.get_feed_rates(), f.get_min_s(), f.get_max_s())
            by_fs.setdefault(key, []).append(f.name)
        if len(by_fs) > 1:
            detail = "; ".join(
                f"F={sorted(fr)} S=[{smin},{smax}]: {names}" for (fr, smin, smax), names in by_fs.items()
            )
            warnings.append(f"family '{family}' step '{step}' run '{run}': inconsistent feed/speed across {len(files)} files -- {detail}")
    return warnings


def check_clearance_plane_consistency_within_feature(cam_files: List[CAMFile]) -> List[str]:
    """Within each (family, step, run-suffix) group, the retract/clearance height (max Z)
    should match -- it's meant to be a fixed safe-travel height, not geometry-dependent."""
    warnings = []
    for (family, step, run), files in _group_by_family_and_run(cam_files).items():
        by_z = {}
        for f in files:
            z = f.get_max_z()
            if z is None:
                continue
            by_z.setdefault(z, []).append(f.name)
        if len(by_z) > 1:
            detail = "; ".join(f"maxZ={z}: {names}" for z, names in by_z.items())
            warnings.append(f"family '{family}' step '{step}' run '{run}': inconsistent clearance plane across {len(files)} files -- {detail}")
    return warnings


def run_all_checks(cam_files: List[CAMFile]) -> Dict[str, List[str]]:
    return {
        "stale_headers": check_stale_headers(cam_files),
        "multi_op_files": check_multi_op_files(cam_files),
        "below_zero": check_below_zero(cam_files),
        "missing_tool": check_missing_tool(cam_files),
        "tool_consistency": check_tool_consistency_within_feature(cam_files),
        "feed_speed_consistency": check_feed_speed_consistency_within_feature(cam_files),
        "clearance_consistency": check_clearance_plane_consistency_within_feature(cam_files),
    }


def format_check_results(results: Dict[str, List[str]]) -> str:
    labels = {
        "stale_headers": "Stale MOP headers (filename mismatch)",
        "multi_op_files": "Multiple concatenated operations in one file",
        "below_zero": "Cuts below Z0",
        "missing_tool": "Missing TOOL declaration",
        "tool_consistency": "Tool inconsistency within a family/run group",
        "feed_speed_consistency": "Feed/speed inconsistency within a family/run group",
        "clearance_consistency": "Clearance-plane inconsistency within a family/run group",
    }
    lines = []
    total = sum(len(v) for v in results.values())
    lines.append(f"[consistency check] {total} warning(s) found")
    for key, label in labels.items():
        items = results.get(key, [])
        if not items:
            continue
        lines.append(f"  -- {label} ({len(items)}) --")
        for item in items:
            lines.append(f"     {item}")
    return "\n".join(lines)
