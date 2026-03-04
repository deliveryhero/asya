# Workflows

Step-by-step guides for common git-aint workflows.

## 1. Starting a New Feature

Plan and execute a multi-aint feature.

### Step 1: Create a grouping dir with aints

```bash
# Create aints in a grouping directory
git aint create --title "Design auth schema" --in auth-rework --priority1
git aint create --title "Implement login endpoint" --in auth-rework --priority1
git aint create --title "Add session management" --in auth-rework --priority2

# Create with dependency
git aint create --title "Write auth tests" --in auth-rework --priority2 \
  --depends-on c9x8
```

### Step 2: Review the plan

```bash
git aint list --view tree              # see dependency tree
git aint list --in auth-rework         # list aints in dir
```

### Step 3: Pick up an aint

```bash
git aint pickup c9x8                   # creates worktree + branch, sets active
```

This creates:
- Branch: `auth-rework/c9x8.design-auth-schema`
- Worktree: `.worktrees/auth-rework/c9x8.design-auth-schema`

### Step 4: Work, push, merge

```bash
# Push code and create PR
git aint push c9x8

# After PR merged
git aint update c9x8 --status merged
```

### Step 5: Repeat for remaining aints

---

## 2. Quick Bug Fix

Fast path for small fixes.

### Step 1: Create in misc

```bash
git aint create --title "Fix null pointer in auth" --priority1 \
  --description "Users see crash on login when session expires"
```

### Step 2: Pick up and work

```bash
git aint pickup d4m1                   # creates worktree
# ... fix the bug in the worktree ...
```

### Step 3: Push and close

```bash
git aint update d4m1 --add-tag "pr:42" --status pushed
# after merge:
git aint update d4m1 --status merged
```

---

## 3. Managing Dependencies

```bash
# Add dependencies at creation
git aint create --title "Write tests" --in auth-rework \
  --depends-on c9x8 d4m1

# Add/remove dependencies later
git aint update e5n2 --add-dep c9x8
git aint update e5n2 --rm-dep c9x8

# View dependency graphs
git aint list --view tree              # grouped tree view
git aint list --columns deps           # flat list with deps column
```

---

## 4. Searching and Filtering

```bash
git aint list --search "authentication"       # full-text search
git aint list --status active                  # currently in progress
git aint list --status open active             # multiple statuses
git aint list --in auth-rework                 # aints in one dir
git aint list --priority 0                     # critical only
git aint list --tag "pr:42"                    # find aint for a PR
git aint list --in auth-rework --status active --priority 1 --output json
```

---

## 5. Direct File Editing

The source of truth is the files in `.aint/` (a git worktree on `aint-sync`).
You can read, edit, create, or delete aint files directly — they're just markdown
with YAML frontmatter.

### Reading files directly

```bash
cat .aint/aints/ci-setup/active.c9x8.fix-auth.md   # read an aint
ls .aint/aints/                                      # browse directories
```

### Editing files directly

Edit any aint file in `.aint/aints/`. To change status, rename the file
(e.g. `open.c9x8.fix-auth.md` → `active.c9x8.fix-auth.md`).

### After manual changes

```bash
git aint sync                          # commit + push changes
git aint sync --dry-run                # preview what would sync
git aint doctor                        # validate file structure
git aint doctor --fix                  # auto-fix detected issues
```

### Auto-sync

CLI write commands (`create`, `update`, etc.) auto-commit and push to
`aint-sync`. No manual sync needed when using the CLI.
