#!/usr/bin/env python3
"""One-time migration: replace [ref] with [[ref]] in aint markdown body text.

Uses pattern matching to identify base-36 aint references (e.g. [1bm2],
[init/1cw2], [misc/1d91]). Skips YAML frontmatter, code blocks, inline
code spans, and markdown links.
"""

import re
import sys
from pathlib import Path

AINT_DIR = Path(__file__).resolve().parent / ".aint" / "epics"

# Known all-letter epic names that should be treated as aint references.
KNOWN_ALPHA_EPICS = {"misc", "init"}


def _build_ref_pattern() -> re.Pattern:
    """Build regex matching [ref] where ref looks like an aint reference.

    Matches:
      [1b0]             bare ID with digit
      [misc]            known alpha epic
      [1b00/1bm2]       epic/task with digit IDs
      [misc/1d91]       alpha epic / task
      [init/1cw2]       alpha epic / task

    Does NOT match:
      [[1b0]]           already wiki-linked
      [text](url)       markdown link
      [some text]       no digits, not a known epic
    """
    alpha_alt = "|".join(re.escape(e) for e in sorted(KNOWN_ALPHA_EPICS))
    id_pat = r"[a-z0-9]{2,10}"

    # A "digit ID" is a base-36 ID containing at least one digit
    digit_id = r"(?=[a-z0-9]*[0-9])[a-z0-9]{2,10}"

    # Build alternatives for what can appear inside [...]
    ref_alternatives = "|".join([
        # epic/task where epic has a digit
        digit_id + r"/" + digit_id,
        # alpha_epic/task
        r"(?:" + alpha_alt + r")/" + digit_id,
        # bare digit ID
        digit_id,
        # bare alpha epic
        r"(?:" + alpha_alt + r")",
    ])

    pattern = (
        r"(?<!\[)"          # not preceded by [
        r"\[(" + ref_alternatives + r")\]"
        r"(?!\()"           # not followed by (
        r"(?!\])"           # not followed by ]
    )
    return re.compile(pattern)


REF_PATTERN = _build_ref_pattern()


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split YAML frontmatter from markdown body."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm_end = end + 4
            if fm_end < len(text) and text[fm_end] == "\n":
                fm_end += 1
            return text[:fm_end], text[fm_end:]
    return None, text


def replace_refs_in_body(body: str, pattern: re.Pattern) -> str:
    """Replace [ref] with [[ref]] in markdown body, skipping code blocks/spans."""
    lines = body.split("\n")
    result = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = not in_code_block
            result.append(line)
            continue

        if in_code_block:
            result.append(line)
            continue

        # Split by backtick sequences to protect inline code spans
        parts = re.split(r"(``[^`]*``|`[^`]*`)", line)
        new_parts = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                # Inside code span — leave as-is
                new_parts.append(part)
            else:
                # Outside code span — do replacement
                new_parts.append(pattern.sub(r"[[\1]]", part))
        result.append("".join(new_parts))

    return "\n".join(result)


def process_file(filepath: Path, pattern: re.Pattern, dry_run: bool) -> bool:
    """Process a single aint markdown file. Returns True if changes were made."""
    text = filepath.read_text()
    frontmatter, body = split_frontmatter(text)

    new_body = replace_refs_in_body(body, pattern)

    if new_body == body:
        return False

    if dry_run:
        print(f"  WOULD change: {filepath.relative_to(AINT_DIR)}")
        for old_line, new_line in zip(body.split("\n"), new_body.split("\n")):
            if old_line != new_line:
                print(f"    - {old_line.strip()}")
                print(f"    + {new_line.strip()}")
        return True

    new_text = (frontmatter or "") + new_body
    filepath.write_text(new_text)
    print(f"  Changed: {filepath.relative_to(AINT_DIR)}")
    return True


def main():
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    if not AINT_DIR.exists():
        print(f"Error: {AINT_DIR} does not exist", file=sys.stderr)
        sys.exit(1)

    pattern = REF_PATTERN
    print(f"Pattern: {pattern.pattern}\n")

    if dry_run:
        print("DRY RUN — no files will be modified\n")

    changed = 0
    total = 0
    for md_file in sorted(AINT_DIR.rglob("*.md")):
        total += 1
        if process_file(md_file, pattern, dry_run):
            changed += 1

    print(f"\n{'Would change' if dry_run else 'Changed'} {changed}/{total} files")
    if dry_run and changed > 0:
        print("Run without --dry-run to apply changes")


if __name__ == "__main__":
    main()
