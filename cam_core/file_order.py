from typing import Dict, List

from cam_core.cam_file import CAMFile


def apply_order_override(by_step: Dict[str, List[CAMFile]], order: Dict[str, List[str]]) -> Dict[str, List[CAMFile]]:
    """Reorder each step's files per a user-saved override (a list of filenames,
    most-recently-arranged order first). Files no longer present in by_step are
    silently dropped from the override; files present but not yet in the
    override are appended, in their existing relative order, after every
    overridden file -- so a parameter change that adds/removes files degrades
    gracefully instead of losing the override entirely.
    """
    if not order:
        return by_step
    result = {}
    for step, files in by_step.items():
        rank = {name: i for i, name in enumerate(order.get(step) or [])}
        if not rank:
            result[step] = files
            continue
        ranked = sorted((f for f in files if f.name in rank), key=lambda f: rank[f.name])
        unranked = [f for f in files if f.name not in rank]
        result[step] = ranked + unranked
    return result
