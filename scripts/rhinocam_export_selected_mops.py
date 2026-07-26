"""
Export each selected RhinoCAM machining operation (MOp) to its own individual
.nc file, instead of RhinoCAM's default of posting a whole setup as one
combined program.

Run this from Rhino's Python editor (Tools > PythonScript > Edit, or the
EditPythonScript command), with the part open and RhinoCAM's MILL module
active. Requires Rhino 6/7 on Windows with RhinoCAM + the RhinoCAM API SDK
(mecsoftcamapi) installed and licensed -- see "RhinoCAM API User doc.pdf".

The RhinoCAM API has no documented call to read which rows are highlighted in
the Operations Manager tree, so "selected" here means picked from a checklist
this script shows you (every MOp across every setup, pre-checked) -- tick the
ones you want, uncheck the rest.

Configure POSTPROCESSOR below to match the post your shop actually uses
(the name RhinoCAM shows in its own Post dialog, e.g. "AbilitySystems.spm").

This script deliberately does NOT call RegenerateMOp() before posting --
regenerating depends on the operation's correct geometry actually being
displayed/current in the Rhino viewport to be safe, which a script has no
way to guarantee or verify, and calling it has coincided with a Rhino crash
during manual testing. Operations you choose to export are assumed to
already be clean (regenerated, not dirty) via your own workflow; posting
just reads whichever toolpath the operation already has.

KNOWN ISSUE -- Rhino crashes have been reproduced coming from the RhinoCAM
API itself, NON-DETERMINISTICALLY: the same script over the same data has
crashed at different points on different runs (once well after everything,
including a test dialog, had already finished cleanly; another time mid-
GetName() on an operation that had succeeded the run before). This looks
like a genuine stability issue in the RhinoCAM 2021 API SDK's native layer,
not a bug fixable from script -- consider checking for a newer RhinoCAM
build and/or reporting this repro to MecSoft support.

Since no single line can be reliably blamed, this script checkpoints its
progress to CHECKPOINT_PATH (a JSON file next to this one) after every
single operation, so a crash costs you re-running, not re-doing: anything
already recorded there is trusted as-is on the next run and never re-
touched. Delete that file to start completely over.
"""
import datetime
import json
import os
import re

import rhinoscriptsyntax as rs
from mecsoftcamapi import *
import MecSoftCAM.Types.ModuleType as ModuleType
import MecSoftCAM.Managers.MOpManager as MOpManager
import MecSoftCAM.Managers.ToolManager as ToolManager

# EDIT ME: the post-processor name as RhinoCAM lists it (see RhinoCAM's own
# Post dialog for the exact string -- it's the .spm file's name).
POSTPROCESSOR = "AlloyShopsabre(WinCNC)ATC.spm"

# DIAGNOSTIC ONLY -- answered: crashes are non-deterministic (one run crashed
# well after a trivial MessageBox survived; the next crashed mid-GetName() on
# an operation that had succeeded cleanly the run before). Leave this False --
# it's not a specific dialog or operation, so there's nothing left to isolate
# this way; see CHECKPOINT_PATH below for the actual mitigation.
DIAGNOSTIC_TRIVIAL_DIALOG = False

# NOTE: this script deliberately never calls Regenerate() (neither
# mop.Regenerate() nor MOpManager.RegenerateMOp()) anywhere. That was tested
# on 2026-07-25 as a diagnostic and removed: mop.Regenerate() itself
# returned False on the first real test, and the process then crashed
# during a retry attempt on that same operation -- 20 consecutive automated
# relaunches all got stuck retrying that one operation with zero forward
# progress. That's a direct empirical confirmation of the original safety
# concern (a script can't verify displayed geometry is current/correct
# before regenerating) -- calling Regenerate() is more crash-prone, not a
# safe way to unblock Post(). Don't re-add it without a real reason.

# DIAGNOSTIC ONLY -- 2026-07-25: new theory -- the API doc shows MOpSetup has
# a SetActive() method ("Set MOpSetup as active"), and ToolManager has
# SetActiveTool(tool) (used in every worked example right after creating a
# tool, before creating/regenerating a MOp). Our script has never called
# either before Post() -- it just fetches setup/mop by index and posts
# directly. Many CAM APIs are stateful and act on whatever is "active"; this
# tests whether Post() silently no-ops (False) because neither the MOp's
# parent setup nor its own tool is the API's current active context.
DIAGNOSTIC_ACTIVATE_BEFORE_POST = True

# DIAGNOSTIC ONLY -- 2026-07-25: the official RhinoCAM SDK example
# (Examples/Net/ExampleRhinoPlugin/ExampleRhinoPluginCommand.cs) never calls
# the instance method mop.Post(path, postprocessor) that this script has
# used exclusively all day -- it posts via the MANAGER-level
# MOpManager.PostProcessAll(path, postprocessor) instead. The API doc's own
# reference table lists a manager-level per-MOp equivalent too:
# MOpManager.PostProcessMOp(path, postprocessor, mop). Testing that in place
# of mop.Post(), on the theory the two aren't equivalent internally (the
# manager-level call may establish context mop.Post() alone doesn't).
USE_MANAGER_LEVEL_POST = True

# DIAGNOSTIC ONLY -- ruled out: tested at 0s/5s/30s, both as a thread-blocking
# time.sleep() and a message-pumping rs.Sleep() (the mouse pointer just spun
# throughout the rs.Sleep() wait -- not evidence of real background work
# completing). Every variant produced the same crash signature. Startup
# timing is not the cause. Left at 0 (disabled) rather than removed outright,
# in case it's worth revisiting alongside some other change later.
STARTUP_DELAY_SECONDS = 0

# NOTE: this script used to make one throwaway warm-up Post() call before
# the real export loop, on the theory that the first live Post() call after
# a fresh Initialize() was uniquely crash-prone. That theory didn't hold up:
# after the warm-up absorbed the first slot on one run, the crash simply
# moved to the next fresh operation instead -- crashes happen at random
# points regardless. Removed 2026-07-26 since it never had a proven
# protective effect, just an extra Post()-equivalent call with the same
# crash risk as any other.

# DIAGNOSTIC ONLY -- when Post() returns False cleanly (not a crash -- a
# crash never reaches the retry check at all), retry that same call this
# many additional times before giving up. Cheap to try; unproven whether it
# actually changes anything, since False may be a deterministic "needs a
# real regenerate first" result rather than a transient one.
POST_RETRY_COUNT = 2

# DIAGNOSTIC ONLY -- speculative race-condition mitigation: a small pause +
# redraw BETWEEN each operation in the export loop (distinct from
# STARTUP_DELAY_SECONDS above, which was a single upfront wait and made no
# difference). There's no way to actually synchronize with RhinoCAM's own
# closed-source internals from Python -- this is the only lever available
# short of that. Set to 0 to disable.
INTER_OP_PAUSE_SECONDS = 2

# HEADLESS TESTING ONLY -- gated on an environment variable (not a hardcoded
# flag) so the normal interactive .bat can never accidentally run this way:
# it auto-selects every collected operation (no CheckListBox) and writes to
# HEADLESS_OUTPUT_DIR (no BrowseForFolder) instead of asking a human. Used to
# reproduce/characterize the non-deterministic crash across unattended runs
# via a SEPARATE launcher (run_rhinocam_export_headless_test.bat) that sets
# RHINOCAM_EXPORT_HEADLESS=1 before starting Rhino. Do not use for a real
# production export -- it skips the human review step entirely.
HEADLESS = os.environ.get("RHINOCAM_EXPORT_HEADLESS") == "1"

# EDIT ME: folder for the crash-proof debug log. Defaults to next to this
# script file; change if that folder isn't writable from wherever this runs.
try:
    LOG_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    LOG_DIR = os.environ.get("TEMP", "C:\\")

# HEADLESS TESTING ONLY -- see HEADLESS above. A disposable scratch folder,
# never the user's real export destination.
HEADLESS_OUTPUT_DIR = os.path.join(LOG_DIR, "headless_test_output")

# Crashes have proven non-deterministic -- the same script over the same data
# fails at a DIFFERENT point almost every run (sometimes not until well after
# everything finished). Since no specific line is reliably to blame, this
# checkpoint file makes the script resumable instead: every operation's
# result (name, or why it was skipped) is persisted here the instant it's
# known, so a crash on op N doesn't lose progress already made on ops 1..N-1
# -- re-running the script skips anything already recorded here and only
# touches whatever's left. Delete this file to start over from scratch.
CHECKPOINT_PATH = os.path.join(LOG_DIR, "rhinocam_export_checkpoint.json")

# EDIT ME: (setup_number, op_number) pairs to skip entirely, 1-indexed to match
# the "Setup X #Y" tags this script prints and the position counting down
# RhinoCAM's own Operations Manager tree.
#
# The RhinoCAM API has no documented -- or, it turns out, even reflectable --
# way to ask "is this suppressed/dirty" from script: dir(mop) on a confirmed-
# suppressed Cut2AxProfilingMOp turned up no boolean member matching "suppress"
# or "dirty" at all (the debugger's own property tree shows only Tool and
# NativePtr on these objects, consistent with that state living purely on the
# native/C++ side, unreachable from Python). Calling GetName() on a suppressed
# operation crashes Rhino itself, not just Python, so there is no safe way to
# detect and skip it automatically. Since you can already see suppressed/dirty
# state by eye in the Operations Manager, list what you find here before
# running -- this is the reliable substitute for automatic detection.
MANUAL_EXCLUDE = set()  # cleared 2026-07-25: layout shifted again (MOPs moved into
# folders), so prior positional exclusions no longer necessarily apply --
# re-derive from scratch against the current, now-stable document if a
# specific op proves to crash again.

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')

# The API doc's "MACHINING OPERATIONS API METHODS" section (GetName/Post/
# Regenerate/etc.) documents exactly these 9 creatable operation types as
# sharing that common interface. WorkZeroMOp (and anything else GetMOpByIndex
# might hand back) is a DIFFERENT object type with its own, much smaller,
# separately-documented API (just constructors -- no GetName/Post at all).
# Calling a common-interface method on one of those crashes Rhino itself
# rather than raising a catchable Python exception, so unknown/unsupported
# types must be filtered out by NAME before anything else touches them --
# never assumed safe just because GetMOpByIndex returned something non-None.
_EXPORTABLE_MOP_TYPES = {
    "Cut3AxPFinishingMOp",
    "Cut3AxProjPocketingMOp",
    "Cut3AxHRoughingMOp",
    "Cut2AxFaceTopMOp",
    "Cut2AxPocketingMOp",
    "Cut2AxProfilingMOp",
    "Cut2AxEngravingMOp",
    "DrillMOp",
    "Cut2AxFacingMOp",
}


_log_file = None  # set by _open_log(); _log() writes here as well as to Output


def _open_log():
    """Open a timestamped log file and return its path. Every _log() call
    below writes to it and flushes + fsyncs immediately, so if Rhino crashes
    hard (as it does on the suppressed-MOp case), whatever was logged right
    before the crash is already safely on disk -- the in-memory Output panel
    is not, and is lost with the rest of the process."""
    global _log_file
    path = os.path.join(LOG_DIR, "rhinocam_export_log_{}.txt".format(
        datetime.datetime.now().strftime("%Y%m%d_%H%M%S")))
    _log_file = open(path, "w")
    return path


def _log(msg):
    print(msg)
    if _log_file is None:
        return
    _log_file.write(msg + "\n")
    _log_file.flush()
    try:
        os.fsync(_log_file.fileno())
    except (AttributeError, OSError):
        pass  # flush() alone still beats losing it entirely if fsync isn't available


def _load_checkpoint():
    """Return the persisted {"collected": {...}, "exported": {...}} dict, or
    a fresh empty one if no checkpoint file exists yet or it's unreadable."""
    if os.path.exists(CHECKPOINT_PATH):
        try:
            with open(CHECKPOINT_PATH, "r") as f:
                data = json.load(f)
            data.setdefault("collected", {})
            data.setdefault("exported", {})
            return data
        except Exception as e:
            _log("WARNING: couldn't read checkpoint ({}), starting fresh.".format(e))
    return {"collected": {}, "exported": {}}


def _save_checkpoint(state):
    """Overwrite the checkpoint file with the current state, flushed (+
    fsynced where supported) immediately -- called right after every single
    operation's result becomes known, not batched, since we can't predict
    which operation a crash will land on."""
    tmp_path = CHECKPOINT_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except (AttributeError, OSError):
            pass
    # Replace is effectively atomic on Windows for same-volume renames, so a
    # crash mid-write never leaves the real checkpoint file half-written.
    #
    # CHECKPOINT_PATH lives on a Google-Drive-synced Shared Drive path --
    # now that this is called after every single retry attempt (not just
    # once per operation), a 2026-07-25 test hit a WindowsError on
    # os.remove() here, almost certainly a transient lock from the Drive
    # sync client briefly holding the file. Retry with backoff instead of
    # letting that (fully avoidable) I/O hiccup take down the whole run.
    last_io_error = None
    for retry_delay in (0.1, 0.3, 0.6, 1.0):
        try:
            if os.path.exists(CHECKPOINT_PATH):
                os.remove(CHECKPOINT_PATH)
            os.rename(tmp_path, CHECKPOINT_PATH)
            return
        except OSError as e:
            last_io_error = e
            _log("  WARNING: checkpoint save hit {} -- retrying in {}s ...".format(e, retry_delay))
            rs.Sleep(int(retry_delay * 1000))
    # Out of retries -- re-raise so the caller's own handling (if any) still
    # sees a real failure instead of silently losing this checkpoint write.
    raise last_io_error


def _safe_filename(name, fallback):
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", (name or "").strip())
    return cleaned or fallback


def _find_bool_property(mop, keyword):
    """Best-effort, SAFE search for a boolean member whose name contains
    `keyword` (e.g. "suppress", "dirty") -- the RhinoCAM API doc doesn't
    document any such getter, so this doesn't assume a specific name.

    dir() is pure Python reflection (reads the type's member table, calls
    nothing) so it can't trigger the kind of crash calling an unsupported
    method does. getattr() only reads the attribute; only a member that's
    both name-matched AND turns out to be callable gets invoked, inside its
    own try/except. Returns (member_name, value) or (None, None) if nothing
    matching and boolean-valued was found.
    """
    for member in dir(mop):
        if member.startswith("_") or keyword not in member.lower():
            continue
        try:
            attr = getattr(mop, member)
            value = attr() if callable(attr) else attr
        except Exception:
            continue
        if isinstance(value, bool):
            return member, value
    return None, None


def _collect_all_mops(checkpoint):
    """Return [(setup_idx, mop_idx, display_label), ...] (0-indexed) across
    every MOpSetup, skipping any object whose type isn't one of the 9
    documented operation types (e.g. WorkZeroMOp), or that tests as
    suppressed/dirty, before calling GetName() on it.

    Crashes have proven non-deterministic (see CHECKPOINT_PATH comment
    above), so any (setup_idx, mop_idx) already recorded in checkpoint
    ["collected"] is trusted as-is and never re-touched -- not even
    GetMOpByIndex() is called again for it. Only genuinely new items reach
    GetName(), and the result (success or skip reason) is persisted via
    _save_checkpoint() the instant it's known, before moving to the next item.

    Returns indices rather than the setup/mop objects themselves, since a
    prior run showed the crash happening right after a Rhino UI dialog
    (CheckListBox) opened following RhinoCAM API calls -- the mitigation is
    to fully Uninitialize the API before showing dialogs and re-Initialize +
    re-fetch fresh objects by index afterward, so nothing here should hold
    onto a setup/mop handle across that boundary."""
    entries = []
    skipped = []
    warned_no_suppress_probe = False
    warned_no_dirty_probe = False
    collected = checkpoint["collected"]
    setup_count = MOpManager.GetMOpSetupCount()
    for setup_idx in range(setup_count):
        setup = MOpManager.GetMOpSetupByIndex(setup_idx)
        if setup is None:
            continue
        mop_count = MOpManager.GetMOpCount(setup)
        for mop_idx in range(mop_count):
            tag = "Setup {} #{}".format(setup_idx + 1, mop_idx + 1)
            key = "{}:{}".format(setup_idx, mop_idx)

            cached = collected.get(key)
            if cached is not None:
                if cached.get("ok"):
                    entries.append((setup_idx, mop_idx, cached["label"]))
                else:
                    skipped.append(cached["reason"])
                continue

            mop = MOpManager.GetMOpByIndex(setup, mop_idx)
            if mop is None:
                continue
            type_name = type(mop).__name__
            _log("Checking {} ({})...".format(tag, type_name))

            def _record_skip(reason):
                skipped.append(reason)
                collected[key] = {"ok": False, "reason": reason}
                _save_checkpoint(checkpoint)

            if (setup_idx + 1, mop_idx + 1) in MANUAL_EXCLUDE:
                _record_skip("{}: {} (manually excluded)".format(tag, type_name))
                continue
            if type_name not in _EXPORTABLE_MOP_TYPES:
                _record_skip("{}: {}".format(tag, type_name))
                continue

            # Best-effort bonus check -- kept in case a future SDK/version does
            # expose this via a differently-named boolean member, but
            # MANUAL_EXCLUDE above is the mechanism actually relied on.
            suppress_member, is_suppressed = _find_bool_property(mop, "suppress")
            if is_suppressed:
                _record_skip("{}: {} (suppressed, via {})".format(tag, type_name, suppress_member))
                continue
            if not suppress_member and not warned_no_suppress_probe:
                warned_no_suppress_probe = True
                _log("  NOTE: no 'suppress'-like member found on this type -- "
                     "can't confirm suppressed state this way, see script docstring.")

            dirty_member, is_dirty = _find_bool_property(mop, "dirty")
            if is_dirty:
                _record_skip("{}: {} (dirty, via {})".format(tag, type_name, dirty_member))
                continue
            if not dirty_member and not warned_no_dirty_probe:
                warned_no_dirty_probe = True
                _log("  NOTE: no 'dirty'-like member found on this type -- "
                     "can't confirm dirty state this way, see script docstring.")

            _log("  calling GetName() on {} ...".format(tag))
            try:
                name = mop.GetName()
            except Exception as e:
                _record_skip("{}: {} (GetName() raised: {})".format(tag, type_name, e))
                continue
            label = "{}: {}".format(tag, name)
            entries.append((setup_idx, mop_idx, label))
            collected[key] = {"ok": True, "label": label}
            _save_checkpoint(checkpoint)
    if skipped:
        _log("Skipped {} item(s):".format(len(skipped)))
        for s in skipped:
            _log("  - {}".format(s))
    return entries


def export_selected_mops():
    log_path = _open_log()
    print("Logging to: {}".format(log_path))  # plain print: shown even if _log_file somehow fails to open
    _log("=== Run started {} ===".format(datetime.datetime.now().isoformat()))
    _log("Log file: {}".format(log_path))

    if STARTUP_DELAY_SECONDS:
        _log("DIAGNOSTIC: rs.Sleep()-ing {}s before any RhinoCAM API call (startup-race theory, "
             "message pump kept alive) ...".format(STARTUP_DELAY_SECONDS))
        rs.Sleep(int(STARTUP_DELAY_SECONDS * 1000))
        _log("DIAGNOSTIC: sleep done, proceeding.")

    checkpoint = _load_checkpoint()
    _log("Loaded checkpoint: {} collected, {} exported".format(
        len(checkpoint["collected"]), len(checkpoint["exported"])))

    api_open = False
    try:
        # --- Phase 1: collect, with the RhinoCAM API initialized ---
        _log("Phase 1: Initialize + collect")
        MecSoftCAM.API.Initialize()
        api_open = True
        MecSoftCAM.API.SetActiveModule(ModuleType.MILL)
        entries = _collect_all_mops(checkpoint)
        # DIAGNOSTIC: 3 consecutive clean headless runs each crashed on the
        # very FIRST Post() call in Phase 3 -- always the first call after a
        # fresh Initialize(), never the same operation twice, and GetName()
        # on that same object succeeds fine right before it. That points at
        # the Uninitialize()/Initialize() cycle around the dialog phase
        # (below) rather than any specific operation's data. HEADLESS mode
        # has no dialogs to protect against, so here it skips that cycle
        # entirely and keeps ONE continuous Initialize() spanning collect
        # and export, to test that theory. Interactive mode is untouched --
        # it still fully uninitializes before showing dialogs (see the
        # CHECKPOINT_PATH-era finding that motivated that in the first
        # place) and re-initializes after.
        if not HEADLESS:
            MecSoftCAM.API.Uninitialize()
            api_open = False
        _log("_collect_all_mops() returned {} entries".format(len(entries)))
        if not entries:
            _log("No machining operations found -- nothing to export.")
            return

        # --- Phase 2: Rhino UI dialogs. Interactive mode uninitializes the
        # RhinoCAM API first (see above); HEADLESS mode has no dialogs and
        # deliberately leaves the API initialized (see DIAGNOSTIC above). ---
        _log("Phase 2: dialogs{}".format(
            " [HEADLESS, API stays initialized]" if HEADLESS else " (API uninitialized)"))

        if HEADLESS:
            chosen = entries
            _log("HEADLESS: auto-selected all {} entries.".format(len(chosen)))
        else:
            labels = [(label, True) for (_setup_idx, _mop_idx, label) in entries]  # all pre-checked
            _log("Built {} checklist labels, opening CheckListBox dialog...".format(len(labels)))
            picked = rs.CheckListBox(labels, "Choose operations to export individually", "Export CAM Ops")
            _log("CheckListBox returned: {}".format("None (cancelled)" if picked is None else "{} entries".format(len(picked))))
            if picked is None:
                _log("Cancelled.")
                return

            chosen = [entries[i] for i, (_label, checked) in enumerate(picked) if checked]
            _log("{} operation(s) checked.".format(len(chosen)))
        if not chosen:
            _log("Nothing checked -- nothing to export.")
            return

        if HEADLESS:
            out_dir = HEADLESS_OUTPUT_DIR
            if not os.path.isdir(out_dir):
                os.makedirs(out_dir)
            _log("HEADLESS: using scratch output dir {}".format(out_dir))
        else:
            _log("Opening BrowseForFolder dialog...")
            out_dir = rs.BrowseForFolder(message="Choose the export folder")
        _log("BrowseForFolder returned: {}".format(out_dir))
        if not out_dir:
            _log("Cancelled -- no export folder chosen.")
            return

        # --- Phase 3: export, re-fetching fresh objects by index rather than
        # reusing anything obtained in Phase 1. In HEADLESS mode the API is
        # already open (see DIAGNOSTIC above) so this reuses that same
        # Initialize() rather than cycling it again. Anything already
        # recorded in checkpoint["exported"] from a prior (crashed) run is
        # trusted as-is and skipped entirely -- not re-posted. ---
        _log("Phase 3: export{}".format(
            " [HEADLESS, reusing Phase 1's Initialize]" if HEADLESS else " (re-Initialize)"))
        exported_ck = checkpoint["exported"]
        if not api_open:
            MecSoftCAM.API.Initialize()
            api_open = True
            MecSoftCAM.API.SetActiveModule(ModuleType.MILL)

        exported, failed = [], []
        active_setup_idx = None  # tracks which setup_idx SetActiveSetup() was last called for
        for setup_idx, mop_idx, label in chosen:
            key = "{}:{}".format(setup_idx, mop_idx)
            cached = exported_ck.get(key)
            if cached is not None:
                _log("Already exported {} -> {} (from checkpoint, skipping)".format(label, cached.get("path")))
                (exported if cached.get("ok") else failed).append((label, cached.get("path")))
                continue

            if INTER_OP_PAUSE_SECONDS:
                # DIAGNOSTIC: speculative race-condition mitigation -- a
                # small pause + redraw BETWEEN operations (distinct from the
                # single upfront startup delay already ruled out above) on
                # the theory that giving Rhino's message loop a moment to
                # settle between native RhinoCAM calls might reduce the
                # chance of catching some internal async task mid-flight.
                # Low confidence -- there is no way to actually synchronize
                # with RhinoCAM's own (closed-source) internals from Python,
                # this is the only lever available short of that.
                rs.Redraw()
                rs.Sleep(int(INTER_OP_PAUSE_SECONDS * 1000))

            _log("Exporting {} ...".format(label))
            attempt = 0
            ok = False
            out_path = None
            last_exception = None
            # IMPORTANT: checkpoint is saved after EVERY attempt below, not
            # just once after retries are exhausted -- a 2026-07-25 test
            # (while briefly testing a since-removed Regenerate() call)
            # showed that saving only at the end meant a crash during a
            # later retry lost the fact
            # that an earlier attempt already completed, so every one of 20
            # automated relaunches got stuck retrying the SAME operation
            # from scratch with zero forward progress. Saving per-attempt
            # means a crash mid-retry still leaves the last known result on
            # disk, so the next launch moves on to the next operation.
            while attempt <= POST_RETRY_COUNT:
                attempt += 1
                try:
                    setup = MOpManager.GetMOpSetupByIndex(setup_idx)
                    mop = MOpManager.GetMOpByIndex(setup, mop_idx)
                    # Individual export: post THIS MOp alone, not its whole
                    # setup, so each operation lands in its own file.
                    #
                    # Not calling RegenerateMOp() for correctness here: it
                    # depends on the correct geometry actually being
                    # displayed/current in the Rhino viewport to be safe,
                    # which this script has no way to guarantee or verify.
                    # Operations chosen for export are assumed to already be
                    # clean/regenerated by the user's own workflow -- posting
                    # just reads whichever toolpath the operation already has.
                    _log("  reading name for {} (attempt {}/{}) ...".format(
                        label, attempt, POST_RETRY_COUNT + 1))
                    filename = _safe_filename(mop.GetName(), "mop_{}".format(len(exported) + len(failed) + 1)) + ".nc"
                    out_path = os.path.join(out_dir, filename)
                    if DIAGNOSTIC_ACTIVATE_BEFORE_POST:
                        # See DIAGNOSTIC_ACTIVATE_BEFORE_POST above -- make
                        # this MOp's parent setup, and its own tool, the
                        # API's active context before posting. Using the
                        # MANAGER-level MOpManager.SetActiveSetup(setup),
                        # not the instance method setup.SetActive() tried
                        # earlier -- the official SDK example
                        # (ExampleRhinoPluginCommand.cs) uses this form.
                        #
                        # Only called when setup_idx actually changes from
                        # the last call, not on every single MOp -- the
                        # example calls this once per setup, before touching
                        # any of its MOps, not once per MOp. Every native
                        # call carries the same random crash risk we've
                        # documented all day, so skipping redundant calls
                        # when we're already in the right setup reduces
                        # total exposure across a run.
                        if setup_idx != active_setup_idx:
                            try:
                                MOpManager.SetActiveSetup(setup)
                                active_setup_idx = setup_idx
                                _log("  DIAGNOSTIC: MOpManager.SetActiveSetup() called for {} ...".format(label))
                            except Exception as act_e:
                                _log("  DIAGNOSTIC: MOpManager.SetActiveSetup() raised: {}".format(act_e))
                        else:
                            _log("  (setup already active, skipping redundant SetActiveSetup() for {})".format(label))
                        try:
                            mop_tool = mop.GetMOpTool()
                            if mop_tool is not None:
                                ToolManager.SetActiveTool(mop_tool)
                                _log("  DIAGNOSTIC: ToolManager.SetActiveTool() called for {} ...".format(label))
                            else:
                                _log("  DIAGNOSTIC: mop.GetMOpTool() returned None for {} -- skipping SetActiveTool".format(label))
                        except Exception as tool_e:
                            _log("  DIAGNOSTIC: tool activation raised: {}".format(tool_e))
                    _log("  posting {} -> {} ...".format(label, out_path))
                    if USE_MANAGER_LEVEL_POST:
                        ok = MOpManager.PostProcessMOp(out_path, POSTPROCESSOR, mop)
                    else:
                        ok = mop.Post(out_path, POSTPROCESSOR)
                    last_exception = None
                except Exception as e:
                    last_exception = e
                    _log("  ERROR on {} (attempt {}/{}): {}".format(label, attempt, POST_RETRY_COUNT + 1, e))
                    exported_ck[key] = {"ok": False, "path": "(exception, no file written)"}
                    _save_checkpoint(checkpoint)
                    break  # an exception is a real error, not the transient-False case -- don't retry it

                # Save THIS attempt's result now, regardless of whether we
                # retry again -- see the IMPORTANT note above.
                exported_ck[key] = {"ok": bool(ok), "path": out_path}
                _save_checkpoint(checkpoint)

                if ok:
                    break
                if attempt <= POST_RETRY_COUNT:
                    # Post() returned False (not a crash -- if it were, we
                    # wouldn't reach this line at all) -- retry a couple of
                    # times in case this is transient, not a deterministic
                    # "this operation needs a real regenerate first" result.
                    _log("  Post() returned False for {}, retrying ({}/{} used) ...".format(
                        label, attempt, POST_RETRY_COUNT))
                    rs.Sleep(500)

            if last_exception is not None:
                failed.append((label, "(exception, no file written)"))
                continue

            (exported if ok else failed).append((label, out_path))

        _log("Exported {} operation(s):".format(len(exported)))
        for label, path in exported:
            _log("  OK   {} -> {}".format(label, path))
        if failed:
            _log("Failed {} operation(s):".format(len(failed)))
            for label, path in failed:
                _log("  FAIL {} -> {}".format(label, path))
        _log("=== Run finished {} ===".format(datetime.datetime.now().isoformat()))
    finally:
        # DIAGNOSTIC: dropped the final MecSoftCAM.API.Uninitialize() call
        # here (2026-07-25) -- the one run that got all the way through Phase
        # 3 without crashing (all 8 remaining ops posted, none excluded)
        # still crashed right at the very end, after "Run finished" logged
        # (confirmed by the user: toolpaths were valid beforehand, ruling out
        # bad data; the crash flash was too fast to read but landed right
        # here). This was the only RhinoCAM API call left in that run. Not
        # calling it leaves the API "initialized" from this script's point of
        # view once the script exits, but Rhino stays open for further manual
        # testing anyway, so there's no real cost to skipping it.
        if _log_file is not None:
            _log_file.close()


if __name__ == "__main__":
    export_selected_mops()
