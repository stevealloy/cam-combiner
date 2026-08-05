"""
Reformat the INPUT-FILE-NAME-BASES array in one or more fixture_config.json5
files so every entry's "required"/"condition"/"alias_of" fields (and any
trailing "// comment") line up in aligned columns, using spaces only (no
tabs). Blank separator lines within the array are preserved; commented-out
entries ("//{ ... }") are aligned alongside active ones.

Usage:
    python align_input_file_name_bases.py <fixture_config.json5> [<fixture_config.json5> ...]
"""
import re
import sys
from collections import Counter

ENTRY_RE = re.compile(
    r'^(?P<indent>[ \t]*)(?P<cprefix>//)?\{\s*"name"\s*:\s*"(?P<name>[^"]*)"\s*,\s*'
    r'"required"\s*:\s*"(?P<required>[^"]*)"\s*,\s*'
    r'"condition"\s*:\s*"(?P<condition>[^"]*)"\s*'
    r'(?:,\s*"alias_of"\s*:\s*"(?P<alias_of>[^"]*)"\s*)?'
    r'\}\s*,?\s*(?P<trailing>//.*)?$'
)


def process_file(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start = end = None
    for i, line in enumerate(lines):
        if '"INPUT-FILE-NAME-BASES"' in line:
            start = i + 1
            continue
        if start is not None and end is None and line.strip().startswith("]"):
            end = i
            break
    if start is None or end is None:
        print("  SKIP (no array found):", path)
        return

    block = lines[start:end]
    parsed = []  # (is_entry, dict | raw_line_without_newline)
    for line in block:
        if not line.strip():
            parsed.append((False, ""))
            continue
        m = ENTRY_RE.match(line.rstrip("\n"))
        if not m:
            print("  WARNING: line didn't match entry pattern, leaving as-is:", line.rstrip("\n"))
            parsed.append((False, line.rstrip("\n")))
            continue
        parsed.append((True, m.groupdict()))

    entries = [d for is_entry, d in parsed if is_entry]
    if not entries:
        print("  SKIP (no entries parsed):", path)
        return

    # Normalize every entry to the file's own most-common indent, so a stray tab
    # or one-off indent width on a single line doesn't survive the reformat
    # (the ask was spaces-only, aligned columns -- not just padding preserved).
    canonical_indent = Counter(d["indent"] for d in entries).most_common(1)[0][0]

    def prefix(d):
        return f'{canonical_indent}{d["cprefix"] or ""}{{ "name":"{d["name"]}",'

    def tail(d):
        s = f'"required":"{d["required"]}", "condition":"{d["condition"]}"'
        if d["alias_of"] is not None:
            s += f', "alias_of":"{d["alias_of"]}"'
        return s + " },"

    prefix_col = max(len(prefix(d)) for d in entries) + 1

    # Build each entry's line (without trailing comment) to find the comment column.
    built = {}
    for d in entries:
        pfx = prefix(d)
        pad = " " * (prefix_col - len(pfx))
        built[id(d)] = pfx + pad + tail(d)

    has_comment = any(d["trailing"] for d in entries)
    comment_col = (max(len(built[id(d)]) for d in entries) + 1) if has_comment else None

    out_lines = []
    for is_entry, d in parsed:
        if not is_entry:
            out_lines.append("\n" if d == "" else d + "\n")
            continue
        line = built[id(d)]
        if d["trailing"]:
            pad = " " * max(1, comment_col - len(line))
            line = line + pad + d["trailing"]
        out_lines.append(line + "\n")

    lines[start:end] = out_lines
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
    print("  OK:", path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for p in sys.argv[1:]:
        print("Processing:", p)
        process_file(p)
