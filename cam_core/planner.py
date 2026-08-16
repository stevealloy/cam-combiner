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
from cam_core import scan_cache

def _is_none_value(v: Any) -> bool:
    """True if a resolved parameter value is that parameter's "no such feature"
    sentinel -- the literal "None", or a prefixed variant like "rNone"/"sdNone"/
    "NFretsNone" (the same convention consistency_checks.py's _PARAM_SEGMENT_RE
    already recognizes as a parametric "none" placeholder).

    A parameter declared with the bare literal "None" as one of its values
    (e.g. NutSlot, Inlay) arrives here as Python None, not the string "None"
    -- jsonc_loader.py's _coerce_scalars() converts any config string
    matching "none"/"null"/"" (case-insensitive) to a real null during
    load, before this function ever sees it. Must be checked explicitly, or
    a legitimate "this feature is turned off" selection renders as the
    literal text "None" (str(None)) in _render_pattern(), matches no real
    file, and gets reported as a missing *required* pattern instead of
    being recognized as intentionally skipped.

    "NoKerf" (KerfStyle's own "no kerf operation" sentinel) is a second,
    explicit exception -- it breaks the "...None" naming convention every
    other sentinel here follows, so it can't be caught by the suffix check
    above. Confirmed independently on the ParamBuilder side: its own
    fixture_data.py NONE_EQUIVALENT_VALUES dict already excludes exactly
    {"NutSlot": {"None"}, "KerfStyle": {"NoKerf"}, "NumFrets": {"NFretsNone"}}
    from its generated checkboxes for the same reason -- these three are
    each a parameter's "nothing selected" value, not a real generatable one."""
    if v is None:
        return True
    return isinstance(v, str) and (v == "None" or v.endswith("None") or v == "NoKerf")


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


def _normalize_passthrough_dirs(dirs) -> set:
    """Normalize ROOT-PASSTHROUGH-DIRS entries (relative paths, '/' or '\\'
    separators, any case) into a set of lowercase '/'-separated relative
    paths for matching against the relative path computed while walking."""
    return {d.strip("/\\").replace("\\", "/").lower() for d in (dirs or []) if d}


def scan_files(base_dir: str, include_ext: Tuple[str,...]=(".nc",), shared_dir: str=None,
               root_passthrough_dirs: List[str]=None) ->Tuple[List[CAMFile], List[FeatureBlock], List[CAMFeature], List[Tool]]:
    scan_files.cfiles: [CAMFile] = []
    scan_files.cfeatures: [CAMFeature] = []
    scan_files.fblocks: [FeatureBlock] = []
    scan_files.tools: [Tool] = []

    base_block = FeatureBlock("Base", "Base")
    scan_files.current_featureblock = base_block
    scan_files.fblocks.append(base_block)

    passthrough = _normalize_passthrough_dirs(root_passthrough_dirs)

    # Per-file content cache (cam_core/scan_cache.py): skips re-opening and
    # re-parsing a file's content when its (size, mtime_ns) hasn't changed
    # since the last scan of this base_dir/shared_dir pair. old_cache is
    # read-only lookup data from the last scan; new_cache is built fresh
    # from whatever's actually seen this walk, so files that no longer
    # exist (moved, renamed, deleted) simply don't get carried forward.
    old_cache = scan_cache.load_cache(base_dir, shared_dir)
    new_cache = {"files": {}}

    _scan_files_int(base_dir, include_ext, passthrough_dirs=passthrough, root_block=base_block,
                     old_cache=old_cache, new_cache=new_cache)

    if shared_dir:
        scan_files.current_featureblock = base_block
        _scan_files_int(shared_dir, include_ext, block_prefix="Shared",
                         passthrough_dirs=passthrough, root_block=base_block,
                         old_cache=old_cache, new_cache=new_cache)

    scan_cache.save_cache(base_dir, new_cache, shared_dir)

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


def _scan_files_int(base_dir: str, include_ext: Tuple[str,...]=(".nc",), block_prefix: str="",
                     passthrough_dirs: set = frozenset(), rel_path: str = "",
                     force_root: bool = False, root_block: FeatureBlock = None,
                     old_cache: dict = None, new_cache: dict = None):
    verbose = False
    skip_files = {"fixture_config.json5", "desktop.ini", "#*", ".*", ".DS_Store"}
    old_cache = old_cache if old_cache is not None else {"files": {}}
    new_cache = new_cache if new_cache is not None else {"files": {}}

    entries = sorted(os.scandir(base_dir), key=lambda x: getattr(x, 'name'))

    # scan ALL to create CAMFile objects, but skip dirs
    for entry in entries:
        fname = base_dir + "/" + entry.name
        # process all non-directory entries first
        if not entry.is_dir() and entry.name not in skip_files:
            st = entry.stat()
            cached_fields = scan_cache.lookup(old_cache, entry.path, st.st_size, st.st_mtime_ns)
            newfile = CAMFile(entry.name, base_dir, scan_files.current_featureblock.name == "Base",
                               cached=cached_fields)
            # Re-record on a hit too (using the same fields, no reparse) --
            # new_cache is rebuilt from scratch each scan_files() call, so a
            # hit that isn't re-added here would vanish after exactly one
            # successful hit instead of persisting across scans.
            fields = cached_fields if cached_fields is not None else newfile.to_cache_fields()
            scan_cache.record(new_cache, entry.path, st.st_size, st.st_mtime_ns, fields)
            newfile._is_passthrough_dir = force_root
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
            child_rel = f"{rel_path}/{entry.name}" if rel_path else entry.name
            child_force_root = force_root or child_rel.lower() in passthrough_dirs
            if child_force_root:
                # ROOT-PASSTHROUGH-DIRS: this subtree's files are still root/base
                # files (see fixture_config.json5), just physically organized under
                # a subdirectory for scale/caching reasons -- keep them anchored to
                # the Base block instead of starting a new FeatureBlock. Re-set
                # current_featureblock explicitly (rather than trusting whatever a
                # previously-processed sibling directory left it as) so a normal
                # feature dir processed just before this one can't misattribute
                # these files to the wrong block.
                scan_files.current_featureblock = root_block
                _scan_files_int(fname, include_ext, block_prefix, passthrough_dirs,
                                 child_rel, True, root_block, old_cache, new_cache)
            else:
                block_name = (block_prefix + "/" + entry.name) if block_prefix else entry.name
                scan_files.current_featureblock = FeatureBlock(block_name, entry.name)
                scan_files.fblocks.append(scan_files.current_featureblock)
                _scan_files_int(fname, include_ext, block_name, passthrough_dirs,
                                 child_rel, False, root_block, old_cache, new_cache)

    return

def normalize_step(stepin: str)->str:
    return stepin.format("")


def plan(cfg: Dict[str, Any],
        runtime_params: Dict[str, Any],
        files: List[CAMFile],
        base_dir: str,
        feature_blocks: list[FeatureBlock],
        features_enabled: list[CAMFeature],
        verbose: bool=False,
        req_missing_out: list=None,
        force_include: List[str]=None):
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
    # required_group: entries sharing a group name are OR'd for requiredness --
    # the group is satisfied if ANY of its active (condition-true) members
    # matched at least one file. Finalized after the base_entries loop below,
    # since a later entry in the same group can satisfy it after an earlier
    # one in the group already came up empty.
    req_group_state: Dict[str, Dict[str, Any]] = {}

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
        req_group = (entry.get("required_group") if isinstance(entry, dict) else None) or None
        cond = (entry.get("condition") if isinstance(entry, dict) else None) or ""
        ok = eval_condition(cond, params)
        if verbose:
            debug_print(f"[cond] {patt}: {cond or 'None'} => {ok}")
        if not ok:
            continue

        # If any token this pattern references currently resolves to its
        # parameter's "none" sentinel (Inlay="None", Radius="rNone", ...), the
        # operation was intentionally turned off for this run -- satisfied with
        # zero files and no warning, instead of requiring a hand-maintained
        # placeholder .nc file on disk just to give the pattern something to match.
        pattern_tokens = re.findall(r"<([A-Za-z_]\w*)(?::(?:lower|upper))?>", patt)
        if any(_is_none_value(params.get(t)) for t in pattern_tokens):
            if verbose:
                debug_print(f"[base] {patt}: a token is a 'None' sentinel -- satisfied, 0 files")
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

        # alias_of: if this entry's own pattern found nothing, fall back to matching
        # a DIFFERENT pattern's files instead -- but still bucket them under THIS
        # entry's own step (taken from patt's leading step token), not the step their
        # filename would otherwise imply. Lets one physical file (e.g. a "final radius"
        # pass) stand in for whichever step actually needs it depending on runtime
        # parameters, instead of requiring a hand-maintained duplicate on disk. A real,
        # distinctly-named file for this entry's own pattern always takes priority over
        # the alias -- alias_of is a fallback, not a substitute for a genuine match.
        # Single lookup level only: alias_of resolves against real scanned files, never
        # against another entry, so no alias chain/recursion is possible.
        alias_step = None
        alias_of = entry.get("alias_of") if isinstance(entry, dict) else None
        if not matches and alias_of:
            alias_attempts, alias_wc_to_value = _render_pattern(alias_of, params, pmap)
            for concrete, lvl in alias_attempts:
                if verbose:
                    debug_print(f"[debug] alias_of concrete='{concrete}'")
                for m in _match_files(files, concrete):
                    if id(m) not in seen:
                        seen.add(id(m))
                        matches.append(m)
            matches.sort(key=lambda m: _resolved_sort_key(m.name, alias_wc_to_value))
            if matches:
                step_match = re.match(r"^([A-Za-z]?\d{2})", patt)
                alias_step = step_match.group(1) if step_match else None
                if verbose:
                    debug_print(f"[alias] {patt} <- {alias_of}: matches={len(matches)} step={alias_step}")

        if verbose:
            debug_print(f"[base] {patt}: matches={len(matches)}")
        if required:
            if req_group:
                gs = req_group_state.setdefault(req_group, {"matched": False, "patterns": []})
                gs["patterns"].append(patt)
                if matches:
                    gs["matched"] = True
            elif not matches:
                req_missing.append(patt)
        for m in matches:
            step = alias_step or m.get_step()
            # A root file with no leading step-digit prefix falls back to the
            # -front/-back suffix for its step (see CAMFile.__init__), which
            # leaves it as the raw "FRONT"/"BACK" sentinel here -- substitute
            # the config's real step number, same as the Base-feature and
            # enabled-feature selection loops below, or it silently never
            # matches any output's step and gets dropped from by_step.
            if step == "FRONT":
                step = str(cfg.get("FRONT-STEP") or "00")
            elif step == "BACK":
                step = str(cfg.get("BACK-STEP") or "00")
            if verbose:
                debug_print(os.path.basename(m.filename) + "==>" + str(step))
            selected_by_step.setdefault(step, []).append(m)
            m.set_matching_search_string(f"{patt} (aliased from {alias_of})" if alias_step else patt)
            #print("match: " + patt + str(m.name))

    for group_name, gs in req_group_state.items():
        if not gs["matched"]:
            req_missing.append(f"one of: {', '.join(gs['patterns'])} (required_group '{group_name}')")

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

    # User-forced inclusion (Files panel +/X button): add files the rule/feature
    # matching above skipped, using the same step-resolution (FRONT/BACK
    # substitution, zero-pad) as regular feature files so they land in the same
    # step bucket a real match would have. Files already selected are left alone
    # (their real matching_search_string is more informative than "(forced)").
    if force_include:
        force_names = set(force_include)
        for f in files:
            if f.name not in force_names:
                continue
            raw_step = str(f.get_step())
            if raw_step == "FRONT":
                raw_step = cfg.get("FRONT-STEP") or "00"
            if raw_step == "BACK":
                raw_step = cfg.get("BACK-STEP") or "00"
            fstep = str(f'{raw_step:0>2}')
            existing = selected_by_step.setdefault(fstep, [])
            if not any(x is f for x in existing):
                existing.append(f)
                if not f.get_matching_search_string():
                    f.set_matching_search_string("(forced)")

    if req_missing:
        debug_print("[warn] required base patterns missing:" + ", ".join(req_missing))
    # Optional out-param rather than a new return value, so every existing
    # caller unpacking plan()'s 2-tuple (tests, cli, the GUI's other call
    # sites) keeps working unchanged -- only a caller that explicitly wants
    # to enforce this (write_output_files(), via run_plan()'s state) passes
    # a list here to read it back.
    if req_missing_out is not None:
        req_missing_out.extend(req_missing)

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


def format_missing_required_patterns(missing: List[str]) -> str:
    lines = [f"  {p}" for p in missing]
    return (
        "required base file pattern(s) matched no files -- output not generated:\n"
        + "\n".join(lines)
    )
