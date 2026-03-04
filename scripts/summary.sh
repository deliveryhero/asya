#!/bin/sh
# summary.sh — generate structured project status overview
set -e

# --- parse args ---
output_fmt="txt"
brief=""
dir_slug=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output)  shift; output_fmt="$1" ;;
    --brief)   brief=1 ;;
    -*)        echo "error: unknown flag $1" >&2; exit 1 ;;
    *)         [ -z "$dir_slug" ] && dir_slug="$1" ;;
  esac
  shift
done

case "$output_fmt" in
  txt|md) ;;
  *) echo "error: --output must be 'txt' or 'md', got '$output_fmt'" >&2; exit 1 ;;
esac

# --- locate aints root ---
aint_root="$(git rev-parse --show-toplevel)/.aint/aints"

# --- collect aint data ---
list_args="--output json --status all"
if [ -n "$dir_slug" ]; then
  list_args="$list_args --in $dir_slug"
fi
# shellcheck disable=SC2086
aint_json=$(git aint list $list_args 2>/dev/null) || aint_json="[]"

# --- collect PR data (optional, cached once) ---
pr_json="[]"
if command -v gh >/dev/null 2>&1; then
  pr_json=$(gh pr list --state open --json number,headRefName,state 2>/dev/null) || pr_json="[]"
fi

# --- render with python3 ---
python3 -c '
import json, sys, os, glob

output_fmt = sys.argv[1]
brief = sys.argv[2] == "1"
dir_slug = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
aint_root = sys.argv[4]
aint_json_str = sys.argv[5]
pr_json_str = sys.argv[6]

aints = json.loads(aint_json_str)
prs = json.loads(pr_json_str)

# build PR lookup: branch -> pr number
pr_by_branch = {}
for pr in prs:
    pr_by_branch[pr.get("headRefName", "")] = pr.get("number")

# priority label
def pri_label(p):
    return "P" + str(p)

# extract branch and pr tags from an aint
def get_tag(aint, key):
    for t in aint.get("tags", []):
        if t.get("key") == key:
            return t.get("value", "")
    return None

# group aints by dir
dirs = {}
for a in aints:
    d = a.get("dir") or "(root)"
    dirs.setdefault(d, []).append(a)

# sort dirs alphabetically
dir_names = sorted(dirs.keys())

# compute status counts across all aints
status_map = {"Active": 0, "Open": 0, "Pushed": 0, "Backlog": 0, "Merged": 0, "Rejected": 0}
for a in aints:
    s = a.get("status", "")
    if s in status_map:
        status_map[s] += 1

# build header
parts = []
for label in ["Active", "Open", "Pushed", "Backlog"]:
    n = status_map.get(label, 0)
    if n > 0:
        parts.append(f"{n} {label.lower()}")
merged_n = status_map.get("Merged", 0) + status_map.get("Rejected", 0)
if not parts and merged_n == 0:
    header_line = "git-aint: all clear"
elif not parts:
    header_line = f"git-aint: all clear | {merged_n} merged"
else:
    header_line = "git-aint: " + ", ".join(parts)
    if merged_n > 0:
        header_line += f" | {merged_n} merged"

# helper: get rfc line count for a dir
def rfc_lines(d):
    if d == "(root)":
        return 0
    rfc_path = os.path.join(aint_root, d, "rfc.md")
    if os.path.isfile(rfc_path):
        with open(rfc_path) as f:
            return sum(1 for _ in f)
    return 0

# helper: get summary title for a dir
def dir_title(d):
    if d == "(root)":
        return ""
    summary_path = os.path.join(aint_root, d, "summary.md")
    if os.path.isfile(summary_path):
        with open(summary_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("title:"):
                    t = line[len("title:"):].strip().strip("\"").strip("'\''")
                    return t
    return ""

# helper: recently closed items for a dir
def closed_items(d):
    if d == "(root)":
        return []
    closed_dir = os.path.join(aint_root, d, ".closed")
    if not os.path.isdir(closed_dir):
        return []
    items = []
    # sort by mtime descending (newest first), limit to 5
    entries = [e for e in os.listdir(closed_dir) if e.endswith(".md")]
    entries.sort(key=lambda e: os.path.getmtime(os.path.join(closed_dir, e)), reverse=True)
    for fname in entries[:5]:
        # format: status.id.slug.md
        parts = fname[:-3].split(".", 2)
        if len(parts) >= 3:
            items.append({"status": parts[0], "id": parts[1], "slug": parts[2].replace("-", " ").title()})
        elif len(parts) == 2:
            items.append({"status": parts[0], "id": parts[1], "slug": ""})
    return items

# helper: resolve branch for an aint
def get_branch(a):
    b = get_tag(a, "branch")
    if b:
        return b
    return None

# helper: resolve pr for an aint
def get_pr(a):
    pr_tag = get_tag(a, "pr")
    if pr_tag:
        return pr_tag
    branch = get_branch(a)
    if branch and branch in pr_by_branch:
        return str(pr_by_branch[branch])
    return None

# helper: resolve worktree path for an aint
def get_worktree(a):
    return get_tag(a, "worktree")

# filter to open/active aints (non-closed)
open_statuses = {"Active", "Open", "Pushed", "Backlog"}

# status symbol for md
def status_sym(s):
    sl = s.lower()
    if sl == "active":
        return "\u25d0 active"
    elif sl == "open":
        return "\u25cb open"
    elif sl == "pushed":
        return "\u25d1 pushed"
    elif sl == "backlog":
        return "\u25a1 backlog"
    return sl

# === RENDER ===

lines = []

if output_fmt == "txt" and brief:
    lines.append(header_line)
    # one line per open/active aint, sorted by priority then status
    open_aints = [a for a in aints if a["status"] in open_statuses]
    open_aints.sort(key=lambda a: (a.get("priority", 4), a["status"] != "Active", a["status"] != "Open"))
    for a in open_aints:
        s = a["status"].lower()
        pri = pri_label(a.get("priority", 4))
        ref = a["id"]
        d = a.get("dir") or ""
        d_part = d + "/" if d else ""
        title = a.get("title", "")
        branch = get_branch(a)
        worktree = get_worktree(a)
        parts = [f"{s:<8}{pri} [{ref}] {d_part} {title}"]
        if worktree:
            parts[0] += f"  worktree:{worktree}"
        if branch:
            parts[0] += f"  branch:{branch}"
        lines.append(parts[0])
    # closed summary
    total_merged = status_map.get("Merged", 0)
    total_rejected = status_map.get("Rejected", 0)
    closed_parts = []
    if total_merged > 0:
        closed_parts.append(f"{total_merged} merged")
    if total_rejected > 0:
        closed_parts.append(f"{total_rejected} rejected")
    if closed_parts:
        lines.append("closed(all): " + ", ".join(closed_parts))

elif output_fmt == "txt" and not brief:
    lines.append(header_line)
    lines.append("")
    for d in dir_names:
        d_aints = dirs[d]
        rfc_n = rfc_lines(d)
        rfc_info = f"  (rfc.md: {rfc_n} lines)" if rfc_n > 0 else ""
        lines.append(f"  {d}/{rfc_info}")
        open_in_dir = [a for a in d_aints if a["status"] in open_statuses]
        open_in_dir.sort(key=lambda a: (a.get("priority", 4), a["status"] != "Active"))
        for a in open_in_dir:
            s = a["status"].lower()
            pri = pri_label(a.get("priority", 4))
            ref = a["id"]
            title = a.get("title", "")
            branch = get_branch(a)
            pr = get_pr(a)
            worktree = get_worktree(a)
            worktree_part = f"  worktree:{worktree}" if worktree else ""
            branch_part = f"  branch:{branch}" if branch else ""
            pr_part = f"  PR:#{pr}" if pr else "  PR:-" if branch else ""
            lines.append(f"    {s:<8}{pri} [{ref}]  {title}{worktree_part}{branch_part}{pr_part}")
        # recently closed
        closed = closed_items(d)
        if closed:
            lines.append("    recently closed:")
            for c in closed:
                slug_part = f" {c['\''slug'\'']}" if c["slug"] else ""
                lines.append(f"      {c['\''status'\'']} [{c['\''id'\'']}]{slug_part}")
        lines.append("")

elif output_fmt == "md" and brief:
    lines.append(f"# {header_line}")
    lines.append("")
    lines.append("```")
    open_aints = [a for a in aints if a["status"] in open_statuses]
    open_aints.sort(key=lambda a: (a.get("priority", 4), a["status"] != "Active", a["status"] != "Open"))
    for a in open_aints:
        s = a["status"].lower()
        pri = pri_label(a.get("priority", 4))
        ref = a["id"]
        d = a.get("dir") or ""
        d_part = d + "/" if d else ""
        title = a.get("title", "")
        branch = get_branch(a)
        worktree = get_worktree(a)
        worktree_part = f"  worktree:{worktree}" if worktree else ""
        branch_part = f"  branch:{branch}" if branch else ""
        lines.append(f"{s:<8}{pri} [{ref}] {d_part} {title}{worktree_part}{branch_part}")
    lines.append("```")

elif output_fmt == "md" and not brief:
    lines.append("<!-- auto-generated by git aint summary \u2014 do not edit -->")
    lines.append(f"# {header_line}")
    lines.append("")
    for d in dir_names:
        d_aints = dirs[d]
        dtitle = dir_title(d)
        title_part = f" \u2014 {dtitle}" if dtitle else ""
        rfc_n = rfc_lines(d)
        lines.append(f"## {d}/{title_part}")
        if rfc_n > 0:
            lines.append(f"> rfc.md: {rfc_n} lines")
        lines.append("")
        open_in_dir = [a for a in d_aints if a["status"] in open_statuses]
        open_in_dir.sort(key=lambda a: (a.get("priority", 4), a["status"] != "Active"))
        if open_in_dir:
            lines.append("| Status | Ref | Pri | Title | Worktree | Branch | PR |")
            lines.append("|--------|-----|-----|-------|----------|--------|----|")
            for a in open_in_dir:
                sym = status_sym(a["status"])
                ref = a["id"]
                pri = pri_label(a.get("priority", 4))
                title = a.get("title", "")
                branch = get_branch(a)
                pr = get_pr(a)
                worktree = get_worktree(a)
                worktree_cell = f"`{worktree}`" if worktree else "\u2014"
                branch_cell = f"`{branch}`" if branch else "\u2014"
                pr_cell = f"#{pr}" if pr else "\u2014"
                lines.append(f"| {sym} | [{ref}] | {pri} | {title} | {worktree_cell} | {branch_cell} | {pr_cell} |")
            lines.append("")
        # recently closed
        closed = closed_items(d)
        if closed:
            lines.append("### Recently closed")
            for c in closed:
                sym = "\u2713" if c["status"] == "merged" else "\u2717"
                slug_part = f" {c['\''slug'\'']}" if c["slug"] else ""
                lines.append(f"- {sym} {c['\''status'\'']} [{c['\''id'\'']}]{slug_part}")
            lines.append("")

print("\n".join(lines))
' "$output_fmt" "${brief:-0}" "$dir_slug" "$aint_root" "$aint_json" "$pr_json"
