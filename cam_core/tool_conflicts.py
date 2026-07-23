from typing import Callable, Dict, Set
from cam_core.cam_file import CAMFile


def find_active_tool_conflicts(cam_files: list, is_enabled: Callable[[CAMFile], bool]) -> Dict[int, Set[str]]:
    """
    Return {tool_num: {description, ...}} for every tool number where more than one
    distinct tool description is actually selected for output ("enabled") in this run.

    Reusing a tool slot across files that are never enabled together in the same run
    is fine and common -- e.g. several alternate options (multiple roundover profiles,
    only one of which is ever active) sharing a slot, since the machine never sees the
    unused description. It only becomes a real conflict when two different descriptions
    for the same tool number are both live in the same run, since that would require
    reloading/changing the physical tool mid-project instead of loading each tool once.
    """
    used_descs_by_tnum: Dict[int, Set[str]] = {}
    for cfile in cam_files:
        tool = cfile.get_tool()
        if tool is None or not is_enabled(cfile):
            continue
        used_descs_by_tnum.setdefault(tool.get_tool_num(), set()).add(tool.get_desc())

    return {tnum: descs for tnum, descs in used_descs_by_tnum.items() if len(descs) > 1}


def format_tool_conflicts(conflicts: Dict[int, Set[str]]) -> str:
    lines = []
    for tnum, descs in sorted(conflicts.items()):
        lines.append(f"  T{tnum:02d}: " + "  vs.  ".join(f'"{d}"' for d in sorted(descs)))
    return "\n".join(lines)
