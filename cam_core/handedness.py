import re
from typing import Dict, List

from cam_core.cam_file import CAMFile

_LEFTY_RE = re.compile(r'-lefty(?=[-.]|$)', re.IGNORECASE)
_RIGHTY_RE = re.compile(r'-righty(?=[-.]|$)', re.IGNORECASE)


def _pair_base(name: str) -> str:
    """Filename with any -lefty/-righty marker stripped, so a matched pair shares this key."""
    return _RIGHTY_RE.sub('', _LEFTY_RE.sub('', name))


def find_handedness_orphans(selected_by_step: Dict[str, List[CAMFile]], lefty: bool) -> List[CAMFile]:
    """
    Return the files that will silently vanish from this run's output: files carrying the
    handedness suffix this run does NOT want (so the existing handedness filter drops them)
    with no counterpart, in the same step, carrying the suffix this run DOES want.

    A file with only the wanted suffix, or with no suffix at all, is never an orphan --
    only a lefty/righty pair missing one side is a problem, and only when the missing side
    is the one this particular run actually needs.
    """
    wanted_re, unwanted_re = (_LEFTY_RE, _RIGHTY_RE) if lefty else (_RIGHTY_RE, _LEFTY_RE)

    orphans = []
    for files in selected_by_step.values():
        wanted_bases = {_pair_base(f.name) for f in files if wanted_re.search(f.name)}
        for f in files:
            if unwanted_re.search(f.name) and _pair_base(f.name) not in wanted_bases:
                orphans.append(f)
    return orphans


def format_handedness_orphans(orphans: List[CAMFile], lefty: bool) -> str:
    wanted_label = "-lefty" if lefty else "-righty"
    unwanted_label = "-righty" if lefty else "-lefty"
    lines = [f"  {f.name}" for f in sorted(orphans, key=lambda f: f.name)]
    return (
        f"file(s) with {unwanted_label} have no matching {wanted_label} counterpart, "
        f"but this run needs {wanted_label} (Lefty={lefty}):\n" + "\n".join(lines)
    )
