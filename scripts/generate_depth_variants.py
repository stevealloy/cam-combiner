"""
Generate depth-variant sibling .nc files from a template file whose filename
encodes its depth as a PT<digits> token (e.g. "PT19" -> 0.19 -> "Z0.1900").

The template's PT<digits> token is substituted (in the filename and every
header comment that embeds the filename/stem) for each requested target
token, and the matching Z-depth value in the toolpath body is substituted
to the new depth, formatted with the same number of decimal places the
template itself uses. Everything else in the file (X/Y coordinates, feed
rates, tool/speed) is left untouched.

Usage:
    python generate_depth_variants.py <input_file> <PT_TOKEN> [<PT_TOKEN> ...]

Example:
    python generate_depth_variants.py "01-backprep-face-PT19-NOMIRROR.nc" PT125 PT200 PT210 PT220 PT225 PT230 PT235 PT240 PT250 PT255 PT260 PT270 PT290 PT400
"""
import re
import sys
from pathlib import Path

PT_TOKEN_RE = re.compile(r"PT(\d+)", re.IGNORECASE)
Z_VALUE_RE = re.compile(r"Z(\d+\.\d+)")


def pt_token_to_value(token: str) -> float:
    m = PT_TOKEN_RE.fullmatch(token)
    if not m:
        raise ValueError(f"Not a PT<digits> token: {token!r}")
    return float("0." + m.group(1))


def find_source_token(filename: str) -> str:
    m = PT_TOKEN_RE.search(filename)
    if not m:
        raise ValueError(f"No PT<digits> token found in filename: {filename!r}")
    return m.group(0)


def find_z_string(text: str, value: float) -> str:
    """Find the exact "Z<...>" substring used in the file body for this depth
    value, so substitution preserves the file's own decimal-place formatting."""
    for m in Z_VALUE_RE.finditer(text):
        if abs(float(m.group(1)) - value) < 1e-9:
            return "Z" + m.group(1)
    raise ValueError(f"Could not find a Z-coordinate matching depth {value} in the source file")


def format_like(z_string: str, new_value: float) -> str:
    decimals = len(z_string.split(".")[1])
    return f"Z{new_value:.{decimals}f}"


def insert_generated_note(text: str, source_name: str) -> str:
    """Add a human-readable, G-code-comment note marking this file as machine-
    generated -- for readers browsing the directory, not parsed by any tool.
    Placed right after the "( FILE: ... )" header line if present, else at top."""
    note = (f"( NOTE: auto-generated from {source_name} by "
            f"scripts/generate_depth_variants.py -- do not hand-edit, "
            f"regenerate from the source template instead )")
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.lstrip().startswith("( FILE:"):
            lines.insert(i + 1, note + "\n")
            return "".join(lines)
    return note + "\n" + text


def generate(input_path: Path, target_tokens, dry_run: bool = False):
    text = input_path.read_text(encoding="utf-8")
    source_token = find_source_token(input_path.name)
    source_value = pt_token_to_value(source_token)
    source_z = find_z_string(text, source_value)

    # If the filename's own token never appears in the file's own header text,
    # the file was likely renamed at the filesystem level without its internal
    # header being updated to match -- token-based header substitution would
    # then silently match nothing (while the value-based Z substitution below
    # would still "work"), producing a file with the right depth but a stale
    # header pointing at the old name. Fail loudly instead of doing that.
    if text.count(source_token) == 0:
        raise ValueError(
            f"Source token {source_token!r} (from the filename {input_path.name!r}) "
            f"does not appear anywhere in the file's own header text. This template's "
            f"internal header is stale relative to its own filename (likely renamed on "
            f"disk without updating the header) -- fix the template's own MOP/FILE/marker "
            f"comments to match its filename before using it as a source."
        )

    print(f"Template: {input_path.name}")
    print(f"  source token: {source_token} (depth {source_value}), source Z string: {source_z}"
          f" ({text.count(source_z)} occurrence(s))")

    created = []
    for token in target_tokens:
        target_value = pt_token_to_value(token)
        target_z = format_like(source_z, target_value)

        new_text = text.replace(source_token, token)
        new_text = new_text.replace(source_z, target_z)
        new_text = insert_generated_note(new_text, input_path.name)

        new_name = input_path.name.replace(source_token, token)
        out_path = input_path.with_name(new_name)

        if dry_run:
            print(f"  [dry-run] would create: {new_name}  (depth {target_value}, {new_text.count(target_z)} Z occurrence(s))")
        else:
            out_path.write_text(new_text, encoding="utf-8")
            print(f"  created: {new_name}  (depth {target_value})")
        created.append(out_path)

    return created


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    dry = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    input_path = Path(args[0])
    targets = args[1:]
    generate(input_path, targets, dry_run=dry)
