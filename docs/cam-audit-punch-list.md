# CAM Fixture Audit — Punch List

Scan of all `fixture_config.txt` and `.nc` files across the 26 `*-in` directories under `Alloy-Standard-Builds-CAM` (the 14 top-level model dirs, 9 `Fixtures/*-fix-in` dirs, and 3 `MoserCAM` dirs), checked against the actual parsing logic in `cam_core/` (`jsonc_loader.py`, `cam_file.py`, `planner.py`).

**Links** are relative to this file's location (`docs/` inside `PycharmProjects/CC2/`) and go up three levels to the `Alloy-Standard-Builds-CAM` root. Open this file in an editor/IDE (PyCharm, VS Code) rather than a plain browser tab for the links to resolve as local file opens. If you move this file, the links break.

**Status checkboxes** are for manual tracking only — check whichever one applies (not mutually exclusive here the way the interactive web version is; just check one and leave the others).

There's also an interactive version of this same list (3-way toggle, persists in your browser, "copy status" button) published as a Claude Artifact if you'd rather work from that instead of editing this file by hand.

25 items were resolved and removed from this list in earlier rounds — see the "Retired directories" section below and the Claude conversation history for what was done.

---

## Tool-number conflicts

Same tool # assigned to two physically different bits — the most operationally dangerous class, since the CNC may load the wrong tool.

### [CRITICAL] Tool #17 conflict — s-in (sstyle-in retired as an exact duplicate) — ⚠️ PARTIALLY RESOLVED

"Undercut PT75 (0.75″ DIA)" vs "Drawer slotting mill .25 (1.25″ DIA)" sharing tool 17 in s-in. sstyle-in was confirmed byte-for-byte identical to s-in (same 122 files, same content, including this same conflict) via `diff -rq` and MD5 checksums, and was moved to `_trash/sstyle-in-2026-07-22` on 2026-07-22 — it's no longer part of the active build. **Only s-in still needs the tool-17 conflict fixed.**

Files:
- [s-in/Control/top-jack-pocket-front-03.nc](../../../s-in/Control/top-jack-pocket-front-03.nc)
- [s-in/Control/Rear-control-pot1-back-end.nc](../../../s-in/Control/Rear-control-pot1-back-end.nc)
- [s-in/Control/Rear-control-pot3-back-end.nc](../../../s-in/Control/Rear-control-pot3-back-end.nc)
- [_trash/sstyle-in-2026-07-22/](../../../_trash/sstyle-in-2026-07-22/) (retired duplicate — moved 2026-07-22, not part of the active build)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [WARNING] Tool #10 mislabel — JM-in

"Drill PT2756 7mm" vs "Drill PT3150 8mm" on tool 10 — both have the same 0.3150 DESC diameter, so the 7mm name looks like a stale label for the same physical bit rather than a true swap, but it's still a hard number conflict.

Files:
- [Control/Rear-Homewrecker-controls-front-01.nc](../../../JM-in/Control/Rear-Homewrecker-controls-front-01.nc) — 7mm label
- `JM-in/*.nc` (8mm label — exact file not captured)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [CRITICAL] Tool #15 conflict — ThroughNeck-in

0.5″ downcut compression bit vs 0.375″/0.25″ roundover bits sharing tool 15.

Files:
- `ThroughNeck-in/*.nc` (exact filenames not captured during the scan)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [WARNING] Tool #10 mislabel — ThroughNeck-in

"Drill PT3150 8mm SHORT" vs "Drill PT3150 8mm" — same diameter, likely a length variant mislabeled under the same tool number.

Files:
- [00-blank-locator-pins-AnyScale-02.nc](../../../ThroughNeck-in/00-blank-locator-pins-AnyScale-02.nc) — SHORT
- [Bridges/ThroughHolesSingleRow-back-02.nc](../../../ThroughNeck-in/Bridges/ThroughHolesSingleRow-back-02.nc)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

---

## Silent step-00 defaults

Filenames that don't match the app's step-detection pattern, so they silently fall into step "00" instead of their intended slot.

### [INFO] Silent step-00 default — JM-in

8 real cut files (valid TOOL/MOP headers) with no step prefix or front/back marker.

Files:
- [Control/Rear-JM-control-PT125-Cover.nc](../../../JM-in/Control/Rear-JM-control-PT125-Cover.nc)
- [Neck/Rear-JM-control-PT090-Cover.nc](../../../JM-in/Neck/Rear-JM-control-PT090-Cover.nc)
- [Neck/S-Neck-OnePT5Degree-JM-depth-01.nc](../../../JM-in/Neck/S-Neck-OnePT5Degree-JM-depth-01.nc)
- [Neck/S-Neck-OnePT5Degree-JM-depth-02.nc](../../../JM-in/Neck/S-Neck-OnePT5Degree-JM-depth-02.nc)
- [Neck/S-Neck-OnePT5Degree-JM-depth-03.nc](../../../JM-in/Neck/S-Neck-OnePT5Degree-JM-depth-03.nc)
- [Neck/S-Neck-OnePT8Degree-S-depth-01.nc](../../../JM-in/Neck/S-Neck-OnePT8Degree-S-depth-01.nc)
- [Neck/S-Neck-OnePT8Degree-S-depth-02.nc](../../../JM-in/Neck/S-Neck-OnePT8Degree-S-depth-02.nc)
- [Neck/S-Neck-OnePT8Degree-S-depth-03.nc](../../../JM-in/Neck/S-Neck-OnePT8Degree-S-depth-03.nc)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

---

## Stale or missing G-code headers

Cosmetic — doesn't affect cutting — but MOP:/FILE: header comments that no longer match reality can mislead anyone tracing a file back.

### [INFO] Header/filename drift — MoserCAM (general)

Widespread FILE:/MOP: header comments that don't match actual filenames or folders across all 3 MoserCAM dirs, beyond the benign D:\ vs G:\ drive difference. MoserCAM has since been retired to `_trash` — kept here only for the audit record.

Files:
- [_trash/MoserCAM/Moser-in/](../../../_trash/MoserCAM/Moser-in/) (whole directory, retired)
- [_trash/MoserCAM/Stick-in/](../../../_trash/MoserCAM/Stick-in/) (whole directory, retired)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [WARNING] Headers claim a different subproject — Stick-fixture-in

10 of 11 files have FILE: headers claiming origin from ThroughNeck-in/PUPs/... — a completely different sibling subproject. Strongly suggests these were generated from a ThroughNeck-in template/session and never corrected. MoserCAM has since been retired to `_trash`.

Files:
- [_trash/MoserCAM/Stick-fixture-in/](../../../_trash/MoserCAM/Stick-fixture-in/) (10 of 11 files, exact list not captured; retired)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [INFO] Possible accidental duplicate — MoserCAM/Stick-in — checked, not a duplicate

Diffed the two files: they use different tools (T12 "Ball PT750" vs T11 "Downcut PT750 ROUGH") and wildly different content (7041 lines vs 106 lines) — two unrelated ops that just happen to have adjacent step numbers in their names. Not an issue. MoserCAM has since been retired to `_trash`.

Files:
- [_trash/MoserCAM/Stick-in/11-rear-07-neck-carve-Moser-02.nc](../../../_trash/MoserCAM/Stick-in/11-rear-07-neck-carve-Moser-02.nc)
- [_trash/MoserCAM/Stick-in/11-rear-06-neck-carve-Moser-02.nc](../../../_trash/MoserCAM/Stick-in/11-rear-06-neck-carve-Moser-02.nc)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [INFO] Pre-rename header path — ADHD-in (all files)

All 55 files reference the old path ADHD\CAM\ADHD-in instead of the current Alloy-Standard-Builds-CAM\ADHD-in. Consistent, harmless rename artifact.

Files:
- [ADHD-in/](../../../ADHD-in/) (55 files)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [INFO] Stale "s-in" headers + filename drift — sstyle-in — ⚠️ NOTE: sstyle-in retired

sstyle-in was moved to `_trash/sstyle-in-2026-07-22` on 2026-07-22 after being confirmed byte-for-byte identical to s-in. This finding no longer applies to anything in the active build, kept here only for the audit record.

Files:
- [_trash/sstyle-in-2026-07-22/](../../../_trash/sstyle-in-2026-07-22/) (retired duplicate)

Status: [x] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [INFO] Header points to a different folder and filename — Test-in — now moot (retired)

The one real .nc file's header claimed Fingerboards-in/02a-inlay-...nc — different folder AND different filename than where it actually lived. Test-in has since been moved to `_trash`, so this no longer matters — left open only pending your review, not auto-closed.

Files:
- `_trash/Test-in/` (retired, single file, current name not captured)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [INFO] Header block missing — one file in s-fix-in

Isolated case — just this one file has no header wrapper (no MOP:/FILE:/tool-list at all, starts straight at G90).

Files:
- [03-backup-jig-04-Gasket Channel.nc](../../../Fixtures/s-fix-in/03-backup-jig-04-Gasket%20Channel.nc)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

---

## Minor / cosmetic

Small inconsistencies worth a glance but low risk on their own.

### [INFO] CLINE sign-flip worth a sanity check — Fingerboards-in & Test-in

CLINE: -22.7994 sits next to a comment `// was 22.7982` (positive) in both configs — looks like a recent edit that flipped the sign. Test-in likely copied from/to Fingerboards-in. Test-in itself has since been retired to `_trash`.

Files:
- [Fingerboards-in/fixture_config.txt](../../../Fingerboards-in/fixture_config.txt)
- [_trash/Test-in/fixture_config.txt](../../../_trash/Test-in/fixture_config.txt) — retired

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [INFO] Negative CLINE worth a glance — MoserCAM/Stick-in

CLINE: -21.00 — may be intentional for this axis convention, but flagged for a human sanity check since other configs use positive values. MoserCAM has since been retired to `_trash`.

Files:
- [_trash/MoserCAM/Stick-in/fixture_config.txt](../../../_trash/MoserCAM/Stick-in/fixture_config.txt)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [INFO] Orphaned righty file — t-in

No -lefty counterpart anywhere in the tree. May be intentional (a righty-only fixture op) or a missing file — worth a glance.

Files:
- [11-Full-body-StandardT-01-righty-pt01.nc](../../../t-in/11-Full-body-StandardT-01-righty-pt01.nc)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

### [INFO] Lefty/righty naming drift — ThroughNeck-in

01-mill-body-edges-standards-01.nc (righty) vs 01-mill-body-edges-standards-01y.nc (lefty) — the "01" vs "01y" divergence suggests these were meant to be a matched pair but the names drifted apart.

Files:
- [01-mill-body-edges-standards-01.nc](../../../ThroughNeck-in/01-mill-body-edges-standards-01.nc) — righty
- [01-mill-body-edges-standards-01y.nc](../../../ThroughNeck-in/01-mill-body-edges-standards-01y.nc) — lefty

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _should be covered with new -lefty/-righty tests_

### [INFO] ~31 orphaned righty files — neck-in

04-back-carve-*-righty files with no lefty counterpart in the same folder. May well be intentional (symmetric ops that don't need a mirrored file) — flagged for a human sanity check.

Files:
- `neck-in/**/04-back-carve-*-righty*.nc` (~31 files)

Status: [ ] Ignore &nbsp;&nbsp; [ ] Auto-fix it &nbsp;&nbsp; [ ] Fixed by me

Note: _(add your note here — how you want this changed)_

---

## Retired directories

Tracking what's been moved to `_trash/` during this audit, so it's clear why something referenced elsewhere in this list might no longer be at its original path.

| Directory | Moved to | Date | Reason |
|---|---|---|---|
| `sstyle-in` | `_trash/sstyle-in-2026-07-22` | 2026-07-22 | Confirmed byte-for-byte identical to `s-in` (same 122 files, same content) via `diff -rq` and MD5 checksum comparison — no unique content, retired as a duplicate rather than permanently deleted. |
| `Test-in`, `Test-out` | `_trash/Test-in`, `_trash/Test-out` | 2026-07-22 | Retired directly by the user. |
| `MoserCAM` (all 3 dirs) | `_trash/MoserCAM` | 2026-07-22 | Retired directly by the user. |
| `Fixtures/LP-fix-in` | `_trash/LP-fix-in-2026-07-22` | 2026-07-22 | Orphaned config (its files didn't match its own OUTPUT-FILE-NAMES at all) — retired whole per user request. |
| `Fixtures/BAFurguson-fix-in`, `-fix-out` | `_trash/BAFurguson-fix-in-2026-07-22`, `_trash/BAFurguson-fix-out-2026-07-22` | 2026-07-22 | Retired whole per user request (all 10 files were missing their header block entirely, plus a truncated NUM-STEPS sequence). |
| All contents of `Fixtures/neck-fix-in` and `Fixtures/Fingerboard-fix-in` except `fixture_config.txt` | `_trash/neck-fix-in-2026-07-22`, `_trash/Fingerboard-fix-in-2026-07-22` | 2026-07-22 | Per user request, confirmed first since it also swept up properly-named production files (e.g. `01-neckjig-*`, `BassFB/`) beyond the originally-flagged HSPlatform/Options/add-Bstep-pins issues. |

---

## Fixes applied directly (not just moved to trash)

- **Fingerboards-in tool #20** — 7 fret files reassigned to T38; wheel-slot files left on T20.
- **JM-in tool #14** — "Roundover PT500" files reassigned to T16, "Roundover PT375" files reassigned to T17; "Roundover PT4375 7/16th" left on T14.
- **ADHDFlat-in** BACK-STEP corrected from "08" to "07".
- **PB-fixture-in** NUM-STEPS corrected from 7 to 6 (matches its own OUTPUT-FILE-NAMES entry count, and sibling Fixtures configs' max-index convention).
- **tiltback-necks-in** FRONT-STEP corrected from 2 to 3 (now matches neck-in/bass-neck-in convention).
- **neck-in** NUM-STEPS corrected from 7 to 6; **JM-in** NUM-STEPS corrected from 11 to 10 (both now use the max-step-index convention).
- **ThroughNeck-in** NUM-STEPS added (6); **Fingerboard-fix-in** NUM-STEPS added (4).
- **LP-in** duplicate `DIRECTION` key removed.
- **s-fix-in** one file's stale `FILE:` header corrected to include the `Fixtures\` path segment.
- **ADHD-in Bridges/Wraparound** — confirmed the PUPs-subdirectory copy no longer exists; only the Bridges copy remains.
- **s00-jmfix (JM-fix-in)** — the two offending files removed to `_trash`.

All verified with the actual filesystem and the project's `cam_core` test suite (122 passed, 7 skipped, same 13 pre-existing failures in the intentionally-broken `s21-*-fail-in` test fixtures — unrelated to this work).

---

## Checked and ruled out

No action needed — these were investigated and are not issues:

- Repeated-looking keys (`name`, `block`, `values`) inside `PARAMETERS` array entries — normal array structure, not duplicate JSON keys.
- Short "placeholder" files (~30–300 bytes, literal `Placeholder file no actions` content) in neck-in, bass-neck-in, s-fix-in — confirmed intentional stubs.
- Zero-byte or truncated files — none found across all 26 directories.
- Multiple-TOOL-line or zero-TOOL-line files — none found; every file declares exactly one tool.
