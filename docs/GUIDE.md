# CAM Combiner — User Guide, How-To & Developer Reference

CAM Combiner assembles a directory of small, single-purpose `.nc` (G-code)
files into a set of combined, per-step output programs for a multi-unit CNC
fixture run. Which small files get pulled into which combined output is
driven by a declarative `fixture_config.txt` plus a set of parameter choices
and feature checkboxes picked at run time (via the GUI, the CLI, or an Excel
batch sheet).

This document covers three things in one place:

1. **User Guide** — what the app does and the concepts behind it.
2. **How-To** — step-by-step workflows (GUI, CLI, batch mode).
3. **Developer Reference** — module map, algorithm internals, and how to test.

---

## 1. Core Concepts

| Term | Meaning |
|---|---|
| **Base directory** (`*-in`) | Folder of source `.nc` files for one fixture/model, plus its `fixture_config.txt`. Files directly in this folder are **base files**; files in subfolders are **feature files**. |
| **Shared GCode directory** | An optional second folder of base files shared across multiple models (auto-detected as `<base>/../SharedGCode`). Treated as part of the "Base" block. |
| **Output directory** (`*-out`) | Where combined output files, per-unit folders, session JSON, and logs are written. |
| **Parameter** | A named, dropdown-driven choice (e.g. `Scale`, `NutWidth`) declared in `fixture_config.txt`. Its value is substituted into base-file name patterns to pick the right source files. |
| **Feature** | A toggle (checkbox) corresponding to one logical group of files, auto-discovered from a subfolder of the base directory. Enabling a feature pulls its files into the plan. |
| **Step** | A two-digit (or letter+two-digit) prefix on a file name (e.g. `05-...`) that determines which combined output file it belongs to. |
| **Wildcard** | A placeholder file name (e.g. `AnyNutWidth`) that stands in for "any value of this parameter" — see [§7.3](#73-wildcards). |
| **Plan** | The result of `plan()`: for each configured output file, the ordered list of source `.nc` files that should be concatenated into it. |
| **Session** | A saved JSON snapshot of directories, parameter values, and enabled features, so a specific configuration can be reloaded later. |

---

## 2. Installation & Requirements

- Python 3.10+ (developed against 3.13).
- GUI: `pip install dearpygui`
- Excel batch mode (`--xlsx`): `pip install openpyxl`
- YAML config fallback (optional): `pip install pyyaml`
- Tests: `pip install pytest`

There is no `requirements.txt` in the repo yet — install the pieces above
that you need for the entry point you're running.

Entry points:

| File | Purpose |
|---|---|
| `cam_combiner_gui.py` | Interactive GUI (dearpygui). The primary way this tool is used day to day. |
| `cam_combiner_cli.py` | Headless CLI: plan (and optionally XLS-batch) without the GUI. |
| `main.py`, `cam_combiner_gui-UNCHANGED.py` | **Legacy reference only.** `main.py` is the original monolithic implementation the `cam_core` package was factored out of; `cam_combiner_gui-UNCHANGED.py` is a frozen earlier checkpoint of the GUI. Neither is part of the active app — don't extend them. |

---

## 3. Quick Start (GUI)

```
python cam_combiner_gui.py
```

1. **Choose Base** — pick a `*-in` directory. This:
   - Auto-loads `fixture_config.txt` from that folder (if present).
   - Auto-fills the Output directory by swapping the `-in` suffix for `-out`
     (e.g. `Fingerboards-in` → `Fingerboards-out`), if the base path ends in `-in`.
   - Auto-detects a Shared GCode directory at `<base>/../SharedGCode`, if one exists.
   - Scans both directories and populates the **Features** panel with one
     checkbox per subfolder-derived feature.
2. **Choose Output Dir** — override the auto-filled output directory if needed.
   Also updates the "Json Name" field to the output folder's own name.
3. Adjust **Parameters** (dropdowns/checkboxes, right panel) and **Features**
   (checkboxes, left panel) as needed. Each change automatically re-runs the
   plan and refreshes the **Outputs** table at the bottom, showing which
   source files will land in which combined output, per step.
4. **Unit 1 Only** / **Zip Subdirs** — sit in the same row. "Unit 1 Only"
   limits generation to unit 1 regardless of `MAXUNITS`. "Zip Subdirs", if
   checked, replaces each per-unit/`1toN` output folder with a `<name>.zip`
   in its place (see [§9](#9-output-directory-layout-what-generate-output-produces)).
5. **Generate Output** — writes the combined output files, per-unit
   subfolders, `summary.txt`, and `tools.txt` to the output directory, and
   saves a session JSON (see [§8](#8-sessions)).
6. **Sessions** — save/load a named JSON snapshot of the current
   directories/parameters/features via the dropdown + Load/Save buttons.

The **Files** panel (center) lists every scanned `.nc` file with its tool
number, step, and which base-selection pattern (if any) matched it — useful
for diagnosing why a file was or wasn't picked up. A root file with no
match is shaded gray, with the point where its name first diverges from the
closest candidate pattern highlighted in orange. The
**Tools** panel (right) lists every tool number/description pair found
across all files, highlighting ones that are part of the current plan, and
flagging tool-number conflicts (same number, different description).

---

## 4. Directory Layout Conventions

```
<Model>-in/
    fixture_config.txt
    01-blank-prep-s21-ftPT30.nc      <- base file (root of *-in)
    05-profile-s21-nw43-Gibson-...   <- base file
    Neck/                            <- a "feature block" (subfolder)
        02-neck-pocket-01.nc         <- feature file, feature = derived from name
    PUPs/
        Hum-PUP-Bridge-front-01.nc

<Model>-out/                          <- created if it doesn't exist
    01-blank-prep-back-up.nc          <- one combined file per OUTPUT-FILE-NAMES entry
    05-profile.nc
    summary.txt
    tools.txt
    <ModelName>.json                  <- autosave session (see §8)
    1/  2/  3/ ...                    <- one folder per unit, same file names, mirrored/offset per unit
        IndFiles/                     <- every individual source file, output standalone
    1to2/ 1to3/ ...                   <- cumulative "first N units" combined folders

<Model>-in/../SharedGCode/            <- optional, shared across models
    ...same shape as a base directory's root...
```

- **Base files** (root of `*-in`, and everything in the shared dir) are
  matched against name patterns from `fixture_config.txt`'s
  `INPUT-FILE-NAME-BASES`.
- **Feature files** (anything in a subfolder) are grouped automatically —
  see [§7.4](#74-features-subfolder-files).

---

## 5. File Naming Conventions

The planner reads meaning directly out of file names. All of these are
case-insensitive matches on the file's base name:

| Pattern | Meaning |
|---|---|
| `^(\d\d)-...` or `^([A-Ga-g]\d\d)-...` | **Step prefix.** Determines which output file this source belongs to (matched against each output name's own leading step prefix). |
| `...-front-...` / `...-front` (no step prefix) | Step is treated as the special token `FRONT`, resolved via the config's `FRONT-STEP`. |
| `...-back-...` / `...-back` (no step prefix) | Step is treated as `BACK`, resolved via `BACK-STEP`. |
| `...-first...` or `...-start...` | File is ordered **before** the normal files in its step (see [§7.5](#75-within-step-ordering)). |
| `...-end...` | File is ordered **after** the normal files in its step. |
| `...-lefty...` | File is only included when the `Lefty` parameter is on; dropped when off. |
| `...-righty...` | File is only included when `Lefty` is off; dropped when on. |
| `...-NODUP...` | Output only once (unit 1), not duplicated/offset per unit, not mirrored. |
| `...-NOMIRROR...` | Duplicated per unit as normal, but never mirrored even when `Lefty` is on. |

A feature file's **feature name** is derived from its own name by stripping
the step prefix, `-front`/`-back`, `-start`/`-end`, `-NODUP`/`-NOMIRROR`, and
any trailing `-NN` run number — files that reduce to the same feature name
(within the same subfolder) become one checkbox in the GUI.

---

## 6. `fixture_config.txt` Reference

Config files are **JSONC**: standard JSON plus `//` line comments, `/* */`
block comments, and trailing commas before `}`/`]`. Values are read from
this JSONC-relaxed JSON; if parsing fails, the loader falls back to YAML
(`pyyaml`, if installed). Scalar strings are auto-coerced: `"true"/"yes"/"on"`
→ `True`, `"false"/"no"/"off"` → `False`, `"none"/"null"/""` → `None`, and
purely numeric strings become `int`/`float`.

A full worked example lives at `Testing/Fingerboards-in/fixture_config.txt`.

### 6.1 Top-level keys

```jsonc
{
  "MODEL": "FingerboardsFileBased",   // used as the default session/save name

  "CLINE": -22.7994,       // fixture centerline position
  "CLINE_DELTA": 4,        // spacing between duplicated units
  "MAXUNITS": 5,           // max units the fixture can hold; "Unit 1 Only" overrides to 1
  "DIRECTION": "VERTICAL", // duplication axis: HORIZONTAL (X, bodies) or VERTICAL (Y, necks/fingerboards)

  "PARAMETERS": [ /* see §6.2 */ ],
  "INPUT-FILE-NAME-BASES": [ /* see §6.4 */ ],

  "FRONT-STEP": "02-",   // step prefix substituted for the "FRONT" pseudo-step
  "BACK-STEP": "08-",    // step prefix substituted for the "BACK" pseudo-step
  "NUM-STEPS": 10,        // number of entries from OUTPUT-FILE-NAMES to summarize in summary.txt

  "OUTPUT-FILE-NAMES": [ /* see §6.5 */ ]
}
```

`LEFTY`, `NUMUNITS`, and `HasStartAndEnd` used to be accepted in legacy
configs but were **never read** by the planner or GUI — `Lefty` and
"Unit 1 Only" are always GUI-driven toggles (defaulting to off), and
`MAXUNITS` alone governs unit count. As of 2026-07-20 these three keys have
been deleted from every `fixture_config.txt` in the repo and on the shared
build tree; the loader still silently ignores them if present, but don't add
them to new configs.

The loader also accepts the newer key names directly — `base_selection`,
`outputs`, `parameters` — if you're authoring configs from scratch;
`normalize_legacy()` derives them from the `*-CASE` legacy keys automatically
when only those are present, so existing configs don't need to be rewritten.

### 6.2 `PARAMETERS`

```jsonc
{
  "name": "NutWidth",              // token name, used as <NutWidth> in patterns
  "block": "Shape",                // GUI grouping label (cosmetic only)
  "values": ["nw38","nw41","nw43"],// dropdown choices — include any fixed literal prefix (e.g. "nw")
  "wildcard": "AnyNutWidth",       // placeholder text used in generic/base file names; "" disables wildcarding
  "default": "nw43"                // pre-selected value
}
```

Each `values` entry is the **literal text embedded in file names** for that
choice — the parameter system does not add separators for you, so if file
names look like `...-nw43-...`, the value itself must be `"nw43"`, not `"43"`.

Two parameters are always present, are not declared in `PARAMETERS`, and are
rendered as plain checkboxes: `Lefty` (handedness — see [§7.6](#76-handedness-lefty-filtering))
and `unit_1_only` ("Unit 1 Only" — forces single-unit output regardless of `MAXUNITS`).

### 6.3 Conditions

Each `INPUT-FILE-NAME-BASES` entry has a `condition` string, evaluated
against current parameter values by `cam_core/conditions.py`. Grammar:

- Bare parameter name → truthy value of that parameter (`"True"/"yes"/"on"/"1"` → true; `"False"/"no"/"none"/"0"/""` → false).
- `!X` — negation.
- `X&&Y`, `X||Y` — and / or (left-to-right, no precedence between them — don't mix without testing).
- `X==Y` — equality between two boolean sub-expressions.
- `None` or an empty string → always true (entry is unconditional).

Example: `"condition": "!FretStepAlone&&!UseAggregateFrets"` — only apply
this base entry when both `FretStepAlone` and `UseAggregateFrets` are false.

### 6.4 `INPUT-FILE-NAME-BASES` (base-file selection)

```jsonc
{
  "name": "05-profile-<Scale>-<NutWidth>-<NutSlot>-<HeelShape>-<NumFrets>",
  "required": "True",   // if true and nothing matches, a warning is logged (does not abort the run)
  "condition": "None"   // see §6.3
}
```

`<Token>` placeholders are replaced with the current parameter value (or,
optionally, `<Token:lower>` / `<Token:upper>` to force case). The resulting
string is matched as a **prefix** against the base directory's `.nc` files —
i.e. `05-profile-s21-nw43-Gibson-Inglewood-NFrets22` matches any file
starting with that string followed by `-` or `.` (so trailing run numbers,
suffixes, and extensions are all fine). See [§7](#7-how-planning-works) for
exactly how matches are found, unioned, and ordered.

### 6.5 `OUTPUT-FILE-NAMES`

A flat list of output file names, one per combined program:

```jsonc
"OUTPUT-FILE-NAMES": [
    "01-blank-prep-back-up.nc",
    "02-front.nc",
    "05-profile.nc"
]
```

Each name's own leading step prefix (extracted with `^([A-Za-z]?\d{2})` — a
looser pattern than the `^([A-Ga-g]?\d{2})-` used to parse source-file steps,
so e.g. `B00-...` and `s21-...` both extract a prefix here) determines which
step's matched source files get written into it. A name with no recognizable
prefix gets step `""`.

---

## 7. How Planning Works

This is the algorithm behind `plan()` in
`cam_core/planner.py`. Understanding it matters both for authoring configs
and for debugging "why didn't my file get picked up."

### 7.1 Scanning

`scan_files(base_dir, shared_dir=...)` walks the base directory (plus the
shared directory, treated as more base-block files) recursively:

- Every non-directory file becomes a `CAMFile` (parses its step, tool
  number, and — for subfolder files — its feature name).
- Files directly in the base/shared root are marked `is_root=True` (base
  files); everything else is a feature file, grouped into `CAMFeature`
  objects per `FeatureBlock` (subfolder).

### 7.2 Base-file matching

For each `INPUT-FILE-NAME-BASES` entry (in config order) whose `condition`
evaluates true:

1. Render the **exact** pattern (every `<Token>` replaced with its real
   current parameter value).
2. Render every **wildcard combination** of the pattern's tokens — for `n`
   tokens, that's every non-empty subset, each token in the subset replaced
   by its parameter's `wildcard` text instead of its real value (tokens with
   no configured wildcard are skipped from these combinations).
3. Match all of these concrete strings as file-name prefixes (§6.4) and take
   the **union** of every file matched by any of them, de-duplicated.
4. If `required` is true and nothing matched at all, log a warning (with the
   pattern) — this does not stop the run.

Matched files are appended, per entry, in the order the entries appear in
`INPUT-FILE-NAME-BASES`.

### 7.3 Wildcards

A wildcard placeholder (e.g. `AnyNutWidth`) represents "this file applies
regardless of this parameter's value" — it's a **generic base file**, not a
fallback that only kicks in when no exact-value file exists. Concretely:

- If both `...-nw43-...` (the literal current `NutWidth` value) and
  `...-AnyNutWidth-...` exist, **both are selected** for that step.
- Within a single output step, the combined result is ordered **as if every
  wildcard had been resolved** to its real parameter value — a wildcard
  file's sort position is computed by substituting its wildcard text with
  the resolved value before comparing names, so it slots into the sequence
  next to whichever exact-value files it would sit beside if it had been
  named concretely. It is *not* grouped separately at the end just because
  it was found on a later match attempt.

This lets a directory mix fully-specific files (`...-nw43-Gibson-...`) with
generic ones that intentionally omit one axis of variation
(`...-AnyNutWidth-Gibson-...`, applying to every nut width for that heel
shape) and have them combine predictably.

### 7.4 Features (subfolder files)

Every `CAMFeature` whose checkbox is enabled contributes all of its files.
Features are processed in alphabetical order by feature name; files within
a feature are processed in alphabetical order by file name. Each file's step
is resolved the same way as base files (including the `FRONT-STEP`/`BACK-STEP`
substitution).

### 7.5 Within-step ordering

Once a step's file list is assembled (base matches, in pattern order, each
internally ordered per §7.3, followed by feature files in feature-name
order), files are grouped into the final output order by two independent
flags derived from the file name:

1. `-first` / `-start` tagged files, **feature** ones before **base** ones
2. normal (untagged) files, **feature** before **base**
3. `-end` tagged files, **feature** before **base**

Within each of these six buckets, relative order is preserved from the
assembly order described above.

### 7.6 Handedness (`Lefty`) filtering

Applied last, across every step: any file whose name contains `-lefty` is
dropped unless the `Lefty` parameter is on; any file whose name contains
`-righty` is dropped unless `Lefty` is off. Files with neither marker are
unaffected either way.

---

## 8. Sessions

A session is a JSON file (`cam_core/session.py`) capturing: base/shared/output
directory paths, config path, parameter values, and the list of enabled
feature names. It does **not** capture the resolved plan itself — reloading
a session re-scans directories and re-runs planning from scratch.

- **Choosing a config** seeds the "Json Name" field with the config's
  `MODEL` value. Saving at that point (name unchanged) writes/overwrites
  `<output_dir>/<MODEL>.json` — treat this as the "working state" autosave.
- Changing "Json Name" to something else and saving creates a **named test
  case**: `<output_dir>/<name>.json`. Every save always overwrites any
  existing file of that name (no confirmation prompt).
- **Generate Output** also saves a session using the current "Json Name" — and if
  that name differs from both the output folder's own basename and `MODEL`,
  it additionally copies `summary.txt`, `tools.txt`, and every produced
  output file into `<output_dir>/<name>/` as a labeled snapshot of that run.
- The **Sessions** dropdown lists every `*.json` in the current output
  directory; **Load** re-applies one (directories, params, config, enabled
  features) and re-plans.

`tests/conftest.py` treats any `*.json` in a `*-out` directory whose stem is
**not** the config's `MODEL` as a curated test case, and parametrizes
integration tests over each one — see [§12.4](#124-testing).

---

## 9. Output Directory Layout (what "Generate Output" produces)

Given `MAXUNITS = N` (or `1` if "Unit 1 Only" is checked):

```
<output_dir>/
    summary.txt          # run parameters + per-step file listing
    tools.txt             # every tool number/description, usage + conflict flags
    <step-output>.nc       # one combined file per OUTPUT-FILE-NAMES entry (root = "as designed", unmirrored/all-units)
    1/ .. N/               # one folder per unit
        <step-output>.nc    # that unit's mirrored/offset copy of each combined output
        IndFiles/
            <source>.nc      # every individual source file, standalone, for that unit
    1to2/ .. 1toN/          # cumulative folders: units 1..k combined, for k = 2..N
        <step-output>.nc
        IndFiles/
            <source>.nc
    <json-name>.json        # session snapshot (see §8)
    <json-name>/             # only if json-name differs from output-dir name and MODEL
        summary.txt tools.txt <step-output>.nc ...   # copies, for archiving a specific test case
```

Within a combined step file, if more than one distinct tool number appears
across that step's files, a trailing `T<nn>` reload line is appended after
all file blocks, reselecting the **first** tool used in that step.

`-NODUP` files are written once (unit 1 only, unmirrored) and skipped
entirely from `1toN` folders. `-NOMIRROR` files are duplicated per unit
normally but never mirrored.

If **Zip Subdirs** is checked, every `1/ .. N/` and `1to2/ .. 1toN/` folder
is zipped to `<name>.zip` in `<output_dir>` and the folder itself is deleted
— e.g. `1/` becomes `1.zip`, `1to2/` becomes `1to2.zip`. `summary.txt`,
`tools.txt`, and the root combined output files are unaffected.

---

## 10. CLI Usage

```
python cam_combiner_cli.py --base <path-to-*-in-dir> [--config <path>] [--verbose]
```

- `--base` — required (unless using `--xlsx`). The `*-in` directory to scan.
- `--config` — defaults to `<base>/fixture_config.txt`.
- `--verbose` — dumps parameters and the full directory listing before planning.

The CLI runs `scan_files()` + `plan()` using each parameter's **default**
value (no interactive selection) and no features enabled, and prints
`[exit] status=ok`. It does not currently write output files — it's useful
for validating that a config loads and plans without errors (e.g. in CI),
not for producing `.nc` output. Use the GUI (or extend the CLI) to actually
generate output files headlessly.

---

## 11. XLS Batch Mode

```
python cam_combiner_cli.py --xlsx <workbook.xlsx>
```

Requires `openpyxl`. Expects a worksheet with (at minimum) `Config File`
and `Directory Listing` columns — one row per test case, where `Config File`
holds inline JSONC config text and `Directory Listing` holds a pasted
directory listing (used verbatim as the file list, no real disk scan). For
each row, it parses the config and file list, calls `plan()` with each
parameter's default value, and writes the resulting per-step matches back
into `Last Test Date` / `Last Test Output` / `Last Test Log` columns
(created if missing) in a copy of the workbook named `tests_out.xlsx`
alongside the input. Useful for regression-checking many configs' base-file
matching at once without a GUI or real files on disk.

---

## 12. Developer Reference

### 12.1 Module map

```
cam_core/
    jsonc_loader.py   JSONC/YAML config parsing + scalar coercion + legacy-key normalization
    conditions.py     Tiny boolean-expression evaluator for base-entry "condition" strings
    cam_file.py       CAMFile: parses one .nc file (step, tool, feature name), Unit/mirroring/output generation
    CAMFeature.py     One named group of feature files + its enabled/checkbox state
    FeatureBlock.py   One subfolder's worth of CAMFeatures + raw CAMFiles
    Tool.py           One tool number + description + the files that use it; tracks conflicts
    planner.py        scan_files() (directory → CAMFile/CAMFeature/FeatureBlock/Tool graph) and
                       plan() (config + params + enabled features → per-step ordered file lists)
    writer.py         write_output_file(): emits one CAMFile's G-code (with BEGIN/END markers) to a stream
    session.py        save_session()/load_session(): JSON snapshot of GUI state
    debug.py          debug_print() (mirrors to the GUI Log panel when available) + dump helpers
    xls_mode.py       process_xls(): Excel batch-mode driver
    version.py        Version string + banners

cam_combiner_gui.py   dearpygui front end: wires user input to scan_files()/plan(), renders the
                       Files/Tools/Outputs panels, and drives actual output-file writing on
                       "Generate Output"
cam_combiner_cli.py   Headless entry point: scan + plan (no file writing) or --xlsx batch mode
```

`main.py` and `cam_combiner_gui-UNCHANGED.py` are legacy/frozen reference
implementations only — see [§2](#2-installation--requirements).

### 12.2 Data model

- **`CAMFile`** (`cam_core/cam_file.py`) — constructed from an on-disk file
  (or `CAMFile.from_lines()` for in-memory/test use). Reads file contents
  once at construction, normalizes home moves (`X0Y0` / `G0 X2Y0` → the
  literal token `"HOME\n"`), extracts the step (via the leading-prefix /
  `-front` / `-back` regexes) and a single tool number+description (raises
  if a file references more than one tool). `create_unit_code()` +
  `get_output()` generate the per-unit, optionally-mirrored G-code lines
  used when writing output.
- **`CAMFeature`** — a name, its file list, and an enabled flag toggled by
  the GUI checkbox.
- **`FeatureBlock`** — one subfolder: its raw `CAMFile`s and the
  `CAMFeature`s derived from them.
- **`Tool`** — tracks every file using a given tool number and flags a
  conflict if two files claim the same number with different descriptions.

### 12.3 Planning algorithm — code map

`plan()` in `cam_core/planner.py` roughly:

1. `_param_lookup()` — index `PARAMETERS` by name for wildcard/default lookup.
2. Loop `base_selection.input_file_base_names`: `eval_condition()` gates the
   entry; `_render_pattern()` builds the exact + every wildcard-combo
   candidate string (and a `wildcard-text → resolved-value` map);
   `_match_files()` unions all matches (prefix regex, case-insensitive);
   `_resolved_sort_key()` orders the union as if wildcards were resolved
   (§7.3). Results accumulate into `selected_by_step[step]`.
3. If there are no `base_selection` entries at all, fall back to including
   every root-block file directly (legacy/no-pattern-config path).
4. Loop enabled features (alphabetical by feature, then by file), appending
   into the same `selected_by_step[step]` structure.
5. Apply the handedness filter (§7.6) to every step's list.
6. Classify each file into the six FEAT/BASE × FIRST/NORMAL/END buckets
   (§7.5) and emit `sorted_selected_by_step` in that bucket order.
7. Return `(outputs, sorted_selected_by_step)` — `outputs` is the config's
   `outputs` list (from `normalize_legacy()`), unfiltered; a caller should
   skip any output whose step has no entries in `sorted_selected_by_step`.

Everything in `plan()` is pure/stateless aside from mutating the passed-in
`CAMFile` objects' `_matching_search_string` (used only for the GUI's "Rule
Match" column) — safe to call repeatedly (e.g. on every parameter change).

### 12.4 Testing

```
python -m pytest tests/ -q                       # run everything against Testing/
python -m pytest tests/ -q -k "not fail"          # skip the intentional-failure fixtures
python -m pytest tests/ -v --base-dir "<path>"    # point at a real job folder instead of Testing/
```

- `tests/test_planner.py` — unit tests against `cam_core.planner.plan()`
  using `CAMFile.from_lines()` (no real files needed). Add cases here for
  new matching/ordering/filtering behavior.
- `tests/test_writer.py` — unit tests for `write_output_file()`.
- `tests/test_integration.py` + `tests/conftest.py` — **data-driven**
  integration tests. `conftest.py` scans `Testing/` (or `--base-dir`) for
  every `<Name>-in/` folder containing a `fixture_config.txt`, and for each
  one:
  - if the matching `<Name>-out/` folder has curated `*.json` session files
    (excluding the one named after the config's `MODEL`, which is treated
    as a working-state autosave, not a test case), one parametrized test
    run is generated **per session file** (loading that session's saved
    parameters/features before planning/asserting);
  - otherwise, one run using the config's bare defaults.

  This is also how the **golden-output** test works
  (`test_output_matches_golden`): a session's directory conventionally pairs
  with a `*-golden/` folder of expected combined output, and the test
  compares actual generated output against it byte-for-byte (see the
  `s21-golden-fail-in` fixture for a deliberately-mismatched negative case).

- **`*-fail-in` fixtures**: several `Testing/` directories are named with a
  `-fail-` segment (e.g. `s21-config-fail-in`, `s21-scan-fail-in`,
  `s21-golden-fail-in`) and are **intentionally broken** — a malformed
  config, an unscannable directory, a wrong golden file, etc. Their
  corresponding tests are expected to fail; `pytest -k "not fail"` is the
  normal way to run the suite excluding them. Don't "fix" these fixtures
  without first checking what failure mode each one is guarding against —
  making them pass would silently disable the negative-path coverage they
  exist for.

When adding a new real-world config/test case: drop a session `*.json` into
the matching `*-out/` folder (any name other than the config's `MODEL`) and
it's automatically picked up by `conftest.py` — no test code changes needed.

### 12.5 Known quirks / legacy fields

- `LEFTY`, `NUMUNITS`, `HasStartAndEnd` top-level config keys were never read
  by any current code path and have been removed from every
  `fixture_config.txt` (both `Testing/` fixtures and the shared build tree)
  as of 2026-07-20 (§6.1).
- `summary.txt` generation (`write_output_files()` in `cam_combiner_gui.py`)
  walks `range(0, NUM-STEPS)` against the legacy `OUTPUT-FILE-NAMES` list
  with zero-padded numeric step strings, independently of the
  `outputs`/`resolved` list used to actually write the combined output
  files. If a model uses non-numeric step prefixes (e.g. `B00`), double
  check `summary.txt` still reflects those steps correctly — the two
  mechanisms are not guaranteed to stay in lockstep for exotic step naming.
- `cam_combiner_cli.py` does not write output files (§10) — it's a
  plan-only smoke test today, not a full headless equivalent of "Generate Output".

---

## 13. Troubleshooting / FAQ

**A file I expected isn't in the plan.**
Check the Files panel's "Rule Match" column (GUI) for that file — an empty
value means no base pattern matched it and it's not part of any enabled
feature. The row is shaded gray, and the file name is split at the point
where it first diverges (case-insensitive) from whichever in-play base
pattern got the closest, with that diverging tail highlighted in orange —
point of divergence is not necessarily the actual typo, just the first
character position two candidate strings disagree on. Common causes: the
pattern's parameter values don't literally match the file name text (§6.2 —
`values` must include any fixed prefix like `nw`), the entry's `condition`
is false for the current parameters, or the file is a `-lefty`/`-righty`
file filtered out by the current `Lefty` setting (§7.6).

**Two files claim the same tool number with different descriptions.**
Check `tools.txt` in the output directory after a run — the `Tools` panel
in the GUI also highlights this. This does not currently block output
generation; verify manually that this is expected before running the job.

**A required base pattern shows a `[warn] required base patterns missing`
in the log.**
No file (exact or wildcard) matched that pattern for the current parameter
values. The run continues — this is a warning, not an abort.

**"Unit 1 Only" doesn't seem to change `1to2/`, `1to3/`, ... folders.**
Those folders are only created for `unitnum in range(2, units_to_produce+1)`
— with "Unit 1 Only" checked, `units_to_produce = 1`, so no `1toN` folders
are created at all for that run.
