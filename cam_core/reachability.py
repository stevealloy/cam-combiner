import itertools
import re
from typing import Any, Dict, List, Tuple

from cam_core.cam_file import CAMFile
from cam_core.conditions import eval_condition
from cam_core.planner import _is_none_value, _param_lookup

# Above this many combinations for a single entry's condition-only parameters,
# exhaustive checking is skipped for that entry/file and conservatively treated
# as "might still reach this file" instead of risking a false "unreachable"
# verdict -- a missed truly-dead file is far less costly than wrongly flagging
# a file that's actually still reachable.
MAX_CONDITION_COMBOS = 5000


def _condition_param_names(cond: str, pmap: Dict[str, Dict[str, Any]]) -> List[str]:
    """Identifier tokens in a condition string that are also known parameter
    names (skips true/false/none literals and the &&/||/! operators)."""
    if not cond:
        return []
    names = re.findall(r"[A-Za-z_]\w*", cond)
    return [n for n in names if n in pmap and n.lower() not in ("true", "false", "none")]


def _build_shape_regex(patt: str, pmap: Dict[str, Dict[str, Any]]):
    """Build a regex matching any filename this pattern's template could render
    to under SOME combination of its tokens' enumerated values or wildcard text,
    with one capturing group per token (in appearance order) so the caller can
    recover which alternative(s) a real match actually used.

    Built from real alternation (not naive '-'-splitting), so it's unaffected by
    a parameter value containing its own literal '-' (e.g. "Heel-Adjust") -- the
    regex just matches whichever literal text was actually chosen, dash or not.
    """
    token_names = []
    out_parts = []
    pos = 0
    for m in re.finditer(r"<([A-Za-z_]\w*)(?::(lower|upper))?>", patt):
        out_parts.append(re.escape(patt[pos:m.start()]))
        name = m.group(1)
        case = m.group(2)
        pdef = pmap.get(name, {})
        alts = []
        for v in pdef.get("values", []):
            vs = str(v)
            if case == "lower":
                vs = vs.lower()
            elif case == "upper":
                vs = vs.upper()
            alts.append(re.escape(vs))
        wildcard = pdef.get("wildcard")
        if wildcard:
            alts.append(re.escape(str(wildcard)))
        if not alts:
            alts = [re.escape(name)]
        out_parts.append("(" + "|".join(alts) + ")")
        token_names.append(name)
        pos = m.end()
    out_parts.append(re.escape(patt[pos:]))
    body = "".join(out_parts)
    rx = re.compile(rf"^{body}(?:[-.].*)?$", re.IGNORECASE)
    return rx, token_names


def _token_value_options(name: str, captured: str, pmap: Dict[str, Dict[str, Any]], case) -> List[str]:
    """Given the literal text a token's regex group actually captured for one
    file, return the specific parameter value(s) it could represent (there can
    be more than one if two enumerated values happen to render identically),
    plus a sentinel entry if it was actually the wildcard placeholder text."""
    pdef = pmap.get(name, {})
    options = []
    for v in pdef.get("values", []):
        vs = str(v)
        if case == "lower":
            vs = vs.lower()
        elif case == "upper":
            vs = vs.upper()
        if vs.lower() == captured.lower():
            options.append(str(v))
    wildcard = pdef.get("wildcard")
    if wildcard and str(wildcard).lower() == captured.lower():
        # Wildcard means "matches regardless of this parameter's value" -- as
        # long as the value isn't itself the "None" sentinel (which would skip
        # the whole entry). Represent that with every non-None enumerated value
        # instead of just the captured wildcard text itself.
        options.extend(str(v) for v in pdef.get("values", []) if not _is_none_value(str(v)))
    return list(dict.fromkeys(options))


def find_unreachable_base_files(
    root_files: List[CAMFile],
    base_entries: List[Any],
    parameters: List[Dict[str, Any]],
) -> List[CAMFile]:
    """Of the given (already-scanned) root/base files, return the ones that can
    NEVER be selected by any INPUT-FILE-NAME-BASES entry, for ANY combination of
    parameter values -- i.e. truly dead files left behind in the base directory,
    as opposed to files that simply don't match under the CURRENT GUI selection.

    Callers should pre-filter to files not already matched under the current
    session (get_matching_search_string() == "") -- a currently-matched file is
    trivially reachable and doesn't need this (comparatively expensive) check.

    For each file/entry pair, a cheap regex first rules out entries whose
    pattern could never structurally render to this filename under ANY token
    choice; only the rare survivors need the full combination search (over the
    condition's own parameters, plus resolving which specific tokens the regex
    actually matched) to confirm the entry's condition can be satisfied without
    forcing any token to its "None sentinel" value (see planner._is_none_value).
    """
    pmap = _param_lookup(parameters)

    entries_meta = []
    for entry in base_entries:
        patt = entry.get("name") if isinstance(entry, dict) else str(entry)
        cond = (entry.get("condition") if isinstance(entry, dict) else None) or ""
        rx, token_names = _build_shape_regex(patt, pmap)
        token_cases = re.findall(r"<[A-Za-z_]\w*(?::(lower|upper))?>", patt)
        cond_only_params = [n for n in _condition_param_names(cond, pmap) if n not in token_names]

        cond_value_lists = []
        for name in cond_only_params:
            vals = [str(v) for v in pmap.get(name, {}).get("values", [])]
            if not vals:
                default = pmap.get(name, {}).get("default")
                vals = [str(default)] if default is not None else [""]
            cond_value_lists.append(vals)

        entries_meta.append({
            "cond": cond,
            "rx": rx,
            "token_names": token_names,
            "token_cases": token_cases,
            "cond_only_params": cond_only_params,
            "cond_value_lists": cond_value_lists,
        })

    unreachable = []
    for f in root_files:
        reachable = False
        for meta in entries_meta:
            m = meta["rx"].match(f.name)
            if not m:
                continue  # cheap structural rule-out: no token choice could ever render this

            token_names = meta["token_names"]
            per_token_options = []
            ok = True
            for i, name in enumerate(token_names):
                captured = m.group(i + 1)
                case = meta["token_cases"][i]
                opts = _token_value_options(name, captured, pmap, case)
                if not opts:
                    ok = False  # shouldn't happen (regex only offers real alternatives), but be safe
                    break
                per_token_options.append(opts)
            if not ok:
                continue

            cond_only_params = meta["cond_only_params"]
            combo_count = 1
            for opts in per_token_options:
                combo_count *= max(1, len(opts))
            for vals in meta["cond_value_lists"]:
                combo_count *= max(1, len(vals))

            if combo_count > MAX_CONDITION_COMBOS:
                reachable = True
                break

            all_names = token_names + cond_only_params
            all_value_lists = per_token_options + meta["cond_value_lists"]
            for combo in itertools.product(*all_value_lists) if all_value_lists else [()]:
                params = dict(zip(all_names, combo))
                if any(_is_none_value(params.get(t)) for t in token_names):
                    continue
                if not eval_condition(meta["cond"], params):
                    continue
                reachable = True
                break
            if reachable:
                break
        if not reachable:
            unreachable.append(f)

    return unreachable
