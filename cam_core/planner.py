import os, re
import itertools
from typing import Dict, Any, List, Tuple
from cam_core.jsonc_loader import normalize_legacy
from cam_core.conditions import eval_condition
from cam_core.debug import debug_print
from cam_core.cam_file import CAMFile
from cam_core.CAMFeature import CAMFeature
from cam_core.Tool import Tool
from cam_core.FeatureBlock import FeatureBlock

def _param_lookup(parameters: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for p in parameters:
        name = p.get("name")
        if not name:
            continue
        out[name] = p
    return out


def _render_pattern(name: str, params: Dict[str, Any], pmap: Dict[str, Dict[str, Any]]) -> Tuple[List[Tuple[str, str]], Dict[str, str]]:
    tokens = re.findall(r"<([A-Za-z_]\w*)(?::(lower|upper))?>", name)

    token_values = {}
    token_wildcards = {}
    for t, case in tokens:
        v = params.get(t, "")
        if isinstance(v, bool):
            v = "True" if v else "False"
        v = str(v)
        if case == "lower":
            v = v.lower()
        elif case == "upper":
            v = v.upper()
        token_values[t] = v
        token_wildcards[t] = pmap.get(t, {}).get("wildcard")

    def _render(wc_set: set) -> str:
        # Substitute each placeholder positionally from the original template so that
        # two tokens sharing the same runtime value don't corrupt each other's position.
        result = name
        for t, case in tokens:
            placeholder = f"<{t}" + (f":{case}>" if case else ">")
            replacement = token_wildcards[t] if (t in wc_set and token_wildcards.get(t)) else token_values[t]
            result = result.replace(placeholder, replacement)
        return result

    exact = _render(set())
    attempts = [(exact, "exact")]

    # generate wildcard substitutions for all combinations
    token_names = [t for t, _ in tokens]
    for r in range(1, len(token_names) + 1):
        for combo in itertools.combinations(token_names, r):
            labels = [t for t in combo if token_wildcards.get(t)]
            if labels:
                attempts.append((_render(set(combo)), f"wildcard({','.join(labels)})"))

    wc_to_value = {wc: token_values[t] for t, wc in token_wildcards.items() if wc}
    return attempts, wc_to_value


def _match_files(files: List[CAMFile], attempt: str) -> List[CAMFile]:
    esc = re.escape(attempt)
    rx = re.compile(rf"^{esc}(?:[-.].*)?$", re.IGNORECASE)
    return [f for f in files if rx.match(f.name)]


def _token_diff(file_name: str, candidate: str) -> Tuple[int, List[Tuple[int, int]]]:
    """Compare candidate's '-'-separated tokens against file_name's leading
    tokens (case-insensitive). Returns (differing_token_count, char_spans)
    where char_spans locates each differing/missing token within file_name,
    so a divergence in one token doesn't drag in an otherwise-matching tail."""
    cand_tokens = candidate.split("-")
    file_tokens = file_name.split("-")

    diff_count = 0
    spans = []
    pos = 0
    for i, ctok in enumerate(cand_tokens):
        if i >= len(file_tokens):
            diff_count += 1
            continue
        ftok = file_tokens[i]
        if ftok.lower() != ctok.lower():
            diff_count += 1
            spans.append((pos, pos + len(ftok)))
        pos += len(ftok) + 1  # +1 for the '-' separator
    return diff_count, spans


def _resolved_sort_key(fname: str, wc_to_value: Dict[str, str]) -> str:
    """Substitute wildcard placeholder text in fname with its resolved value,
    so a wildcard-matched file sorts into the same position it would occupy
    if the wildcard were fully resolved, alongside non-wildcard matches."""
    resolved = fname
    for wc, val in wc_to_value.items():
        resolved = resolved.replace(wc, val)
    return resolved


def _scan_features():
    verbose = False
    """
    Group subdirectory files by feature tag.
    Only considers files that are NOT at the base root (i.e., in subfolders).
    """
    if (verbose):
        debug_print("=====================scanning for Features==========================")
    for fb in scan_files.fblocks:
        if verbose:
            debug_print("Block: ", fb.get_name())
        if (fb.get_name() == "Base"):
            # base / root directory. No features here to add
            continue

        last_feature = ""
        last_feature_name = ""
        unsortedfiles = fb.get_CAM_files()
        sortedfiles = sorted(unsortedfiles, key=lambda f: f.get_feature_name())
        if verbose:
            v("unsorted: " + str(unsortedfiles))
            debug_print("sorted: " + str(sortedfiles))
        for cf in sortedfiles:
            if verbose:
                print("     File: ", cf.name, " ==> ", cf.get_feature_name())
            file_feature_name = cf.get_feature_name()
            if file_feature_name != last_feature_name:
                if (verbose):
                    debug_print("new Feature: ", cf.get_feature_name())
                newFeature = CAMFeature(cf.get_feature_name())
                scan_files.cfeatures.append(newFeature)
                last_feature = newFeature
                last_feature_name = cf.get_feature_name()

                # add the new feature to the feature block
                fb.add_CAM_feature(newFeature)

            last_feature.add_CAM_file(cf)
            if verbose:
                debug_print("   adding to: ", cf.get_feature_name(), " file: ", cf.name)

    if verbose:
        debug_print("================Done scanning for Features==========================")

    return


def scan_files(base_dir: str, include_ext: Tuple[str,...]=(".nc",), shared_dir: str=None) ->Tuple[List[CAMFile], List[FeatureBlock], List[CAMFeature], List[Tool]]:
    scan_files.cfiles: [CAMFile] = []
    scan_files.cfeatures: [CAMFeature] = []
    scan_files.fblocks: [FeatureBlock] = []
    scan_files.tools: [Tool] = []

    scan_files.current_featureblock = FeatureBlock("Base", "Base")
    scan_files.fblocks.append(scan_files.current_featureblock)

    _scan_files_int(base_dir, include_ext)

    if shared_dir:
        base_block = next(fb for fb in scan_files.fblocks if fb.name == "Base")
        scan_files.current_featureblock = base_block
        _scan_files_int(shared_dir, include_ext, block_prefix="Shared")

    _scan_features()

    #*********************************************************************************
    # note that this sorting gives different ordering of CAM objects in output files:
    # we are now alphebetizing by feature name. In the original script, final ordering
    # was based on Feature Block (i.e., by directory -- which was sorted alphabetically),
    # then by feature name within each block (i.e., by the file names in alphabetic order)
    #*********************************************************************************
    new_fblocks = sorted(scan_files.fblocks, key=lambda fbl: fbl.name)
    scan_files.fblocks = new_fblocks
    new_cfeatures = sorted(scan_files.cfeatures, key=lambda cft: cft.name)
    scan_files.cfeatures = new_cfeatures

    return scan_files.cfiles, scan_files.fblocks, scan_files.cfeatures, scan_files.tools


def _scan_files_int(base_dir: str, include_ext: Tuple[str,...]=(".nc",), block_prefix: str=""):
    verbose = False
    skip_files = {"fixture_config.txt", "desktop.ini", "#*", ".*", ".DS_Store"}

    entries = sorted(os.scandir(base_dir), key=lambda x: getattr(x, 'name'))

    # scan ALL to create CAMFile objects, but skip dirs
    for entry in entries:
        fname = base_dir + "/" + entry.name
        # process all non-directory entries first
        if not entry.is_dir() and entry.name not in skip_files:
            newfile = CAMFile(entry.name, base_dir, scan_files.current_featureblock.name == "Base")
            scan_files.cfiles.append(newfile)
            scan_files.current_featureblock.add_CAM_file(newfile)
            tool = newfile.get_tool()
            if not tool is None:
                got_one = False
                for t in scan_files.tools:
                    if t.get_tool_num() == tool.get_tool_num():
                        got_one = True
                        if t.get_desc() == tool.get_desc():
                            # same #, same description. add new file to old tool
                            t.add_file(newfile)
                        else:
                            # t # match, but descp fail. ERROR!
                            t.set_error("file " + entry.name + " reused tool #" + str(t.get_tool_num()) + " new descr: "+tool.get_desc())
                            t.add_file(newfile)
                        break
                if not got_one:
                    # add new tool to our array of tools
                    scan_files.tools.append(tool)

    # now scan all directories and call ourselves recursively
    for entry in entries:
        fname = base_dir + "/" + entry.name
        if entry.is_dir():
            if verbose:
                debug_print("DIR:" + entry.name)
            block_name = (block_prefix + "/" + entry.name) if block_prefix else entry.name
            scan_files.current_featureblock = FeatureBlock(block_name, entry.name)
            scan_files.fblocks.append(scan_files.current_featureblock)
            _scan_files_int(fname, include_ext, block_name)

    return

def normalize_step(stepin: str)->str:
    return stepin.format("")


def plan(cfg: Dict[str, Any],
        runtime_params: Dict[str, Any],
        files: List[CAMFile],
        base_dir: str,
        feature_blocks: list[FeatureBlock],
        features_enabled: list[CAMFeature],
        verbose: bool=False):
    if verbose:
        debug_print("==========================================PLANNER==============================")

    cfg = normalize_legacy(cfg or {})
    outputs = cfg.get("outputs", [])
    base_entries = cfg.get("base_selection", {}).get("input_file_base_names", [])
    if verbose:
        debug_print("base: ", base_entries)
    parameters = cfg.get("parameters", [])
    pmap = _param_lookup(parameters)

    if verbose:
        debug_print("================ PLANNER: DIRECTORY LISTING ================")
        for f in files:
            print(" -", f)

    # clear the search string matches in all files
    for m in files:
        m.set_matching_search_string("")
        m.set_match_diff_spans([])

    # id(file) -> (fewest differing tokens seen so far, char spans of those tokens)
    best_diff: Dict[int, Tuple[int, List[Tuple[int, int]]]] = {}

    selected_by_step: Dict[str, List[CAMFile]] = {}
    sorted_selected_by_step: Dict[str, List[CAMFile]] = {}
    featbool: Dict[CAMFile, List[bool]] = {}
    firstbool: Dict[CAMFile, List[bool]] = {}
    endbool: Dict[CAMFile, List[bool]] = {}
    req_missing = []

    params = {}
    for p in parameters:
        name = p.get("name")
        if not name: continue
        params[name] = runtime_params.get(name, p.get("default"))
    for k, v in runtime_params.items():
        params.setdefault(k, v)

    for entry in base_entries:
        patt = entry.get("name") if isinstance(entry, dict) else str(entry)
        required = str(entry.get("required", "False")).lower() in ("true","yes","1") if isinstance(entry, dict) else False
        cond = (entry.get("condition") if isinstance(entry, dict) else None) or ""
        ok = eval_condition(cond, params)
        if verbose:
            debug_print(f"[cond] {patt}: {cond or 'None'} => {ok}")
        if not ok:
            continue
        # Wildcard substitutions are treated as base files: every attempt level
        # (exact and each wildcard combination) is searched and matches are
        # unioned, rather than stopping once the exact match is found. Matches
        # are then ordered as if every wildcard had been resolved to its real
        # value, so wildcard files fall in sequence with non-wildcard files
        # instead of being grouped by which attempt level found them.
        attempts, wc_to_value = _render_pattern(patt, params, pmap)
        matches = []
        seen = set()
        for concrete, lvl in attempts:
            if verbose:
                debug_print(f"[debug] pattern concrete='{concrete}'")
            for m in _match_files(files, concrete):
                if id(m) not in seen:
                    seen.add(id(m))
                    matches.append(m)
            for m in files:
                diff_count, spans = _token_diff(m.name, concrete)
                prev = best_diff.get(id(m))
                if prev is None or diff_count < prev[0]:
                    best_diff[id(m)] = (diff_count, spans)
        matches.sort(key=lambda m: _resolved_sort_key(m.name, wc_to_value))
        if verbose:
            debug_print(f"[base] {patt}: matches={len(matches)}")
        if required and not matches:
            req_missing.append(patt)
        for m in matches:
            step = m.get_step()
            if verbose:
                debug_print(os.path.basename(m.filename) + "==>" + str(step))
            selected_by_step.setdefault(step, []).append(m)
            m.set_matching_search_string(patt)
            #print("match: " + patt + str(m.name))

    # For files that never got a full match against any in-play base pattern,
    # record which token(s) diverge from the closest attempt (fewest differing
    # tokens wins), so the GUI can highlight just those (Files panel "Rule
    # Match" column) instead of the whole tail past the first difference.
    for m in files:
        if not m.get_matching_search_string() and id(m) in best_diff:
            m.set_match_diff_spans(best_diff[id(m)][1])

    if not base_entries:
        if verbose:
            debug_print("checking for base step file")

        # output files from the base directory
        for ft in feature_blocks:
            if ft.name == "Base":
                for f in ft.get_CAM_files():
                    fstep = f.get_step()

                    if fstep == "FRONT":
                        fstep = cfg.get("FRONT-STEP") or "00"
                    if fstep == "BACK":
                        fstep = cfg.get("BACK-STEP") or "00"
                    selected_by_step.setdefault(fstep, []).append(f)

    unsortedfeatures = features_enabled
    sortedfeatures = sorted(unsortedfeatures, key=lambda f: f.name)
    for v in sortedfeatures:
        if verbose:
            debug_print("feature enabled: " + str(v))
        unsortedfiles = v.get_CAM_files()
        sortedfiles = sorted(unsortedfiles, key=lambda f: f.name)
        if verbose:
            debug_print("unsorted: " + str(unsortedfiles))
            debug_print("sorted: " + str(sortedfiles))

        for f in sortedfiles:
            raw_step = str(f.get_step())
            if raw_step == "FRONT":
                raw_step = cfg.get("FRONT-STEP") or "00"
            if raw_step == "BACK":
                raw_step = cfg.get("BACK-STEP") or "00"
            fstep = str(f'{raw_step:0>2}')
            selected_by_step.setdefault(fstep, []).append(f)

    if req_missing:
        debug_print("[warn] required base patterns missing:" + ", ".join(req_missing))

    # Handedness filter: applied universally after all file selection.
    # Lefty=True  → keep files with -lefty or neither; drop -righty
    # Lefty=False → keep files with -righty or neither; drop -lefty
    _lefty = bool(params.get("Lefty", False))
    for _step in list(selected_by_step):
        selected_by_step[_step] = [
            f for f in selected_by_step[_step]
            if not (re.search(r'-lefty(?:[-.]|$)', f.name, re.IGNORECASE) and not _lefty)
            and not (re.search(r'-righty(?:[-.]|$)', f.name, re.IGNORECASE) and _lefty)
        ]

    featbool = {}
    firstbool = {}
    endbool = {}

    #OK, sort the output files for each step
    for out in outputs:
        step2 = str(out.get("step",""))
        if step2 in selected_by_step:
            for f in selected_by_step.get(step2, []):
                featbool.setdefault(f, []).append(not f._is_root)
                if re.search("-first", f.name) or re.search("-start", f.name):
                    firstbool.setdefault(f, []).append(True)
                else:
                    firstbool.setdefault(f, []).append(False)
                if re.search("-end", f.name):
                    endbool.setdefault(f, []).append(True)
                else:
                    endbool.setdefault(f, []).append(False)

    for out2 in outputs:
        step = out2.get("step", "")
        if step in selected_by_step:
            #***** FEAT ****** FIRST ******* !END
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                #print("step:"+step+" file:"+f.name+" feat?"+str(fet)+" fst?"+str(fst)+" end?"+str(eb))
                if fet and fst and not eb:
                    # output it
                    sorted_selected_by_step.setdefault(step, []).append(f)

            # ***** BASE ****** FIRST ******* !END
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if not fet and fst and not eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

            #***** FEAT ****** !FIRST ******* !END (Normal feature files)
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if fet and not fst and not eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

            #***** BASE ****** !FIRST ******* !END (Normal base files)
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if not fet and not fst and not eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

            #***** FEAT ****** !FIRST ******* END (-end feature files)
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if fet and not fst and eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

            #***** BASE ****** !FIRST ******* END (-end base files)
            for f in selected_by_step.get(step, []):
                fet = (featbool.get(f) or [False])[0]
                fst = (firstbool.get(f) or [False])[0]
                eb = (endbool.get(f) or [False])[0]
                if not fet and not fst and eb:
                    #output it
                    sorted_selected_by_step.setdefault(step, []).append(f)
                    continue

    debug_print("================ PLANNER OUTPUT SELECTION ================")
    resolved_outputs = outputs
    for out in resolved_outputs:
        step = str(out.get("step",""))
        name = out.get("name","")
        files = selected_by_step.get(step, [])
        debug_print(f"     {name} step={step} count={len(files)}")
        for f in files:
            fet = featbool.get(f)[0]
            fst = firstbool.get(f)[0]
            eb = endbool.get(f)[0]
            #debug_print(f"         - FT{fet} FST{fst} END{eb} {f.name}")
            debug_print(f"         - {f.name}")
    debug_print("================ PLANNER SORTED OUTPUT  =====================")
    for out in resolved_outputs:
        step = str(out.get("step",""))
        name = out.get("name","")
        files = sorted_selected_by_step.get(step, [])
        debug_print(f"     {name}] step={step} count={len(files)}")
        for f in files:
            fet = featbool.get(f)[0]
            fst = firstbool.get(f)[0]
            eb = endbool.get(f)[0]
            #debug_print(f"         - FT{fet} FST{fst} END{eb} {f.name}")
            debug_print(f"         - {f.name}")
    debug_print("=========================================================")

    return resolved_outputs, sorted_selected_by_step
