#!/bin/sh

# Parse args: [ref] [--fix] [--skip=category,...]
ref=""
fix=false
skip=""
for arg in "$@"; do
  case "$arg" in
    --fix) fix=true ;;
    --skip=*) skip="${arg#--skip=}" ;;
    -*) echo "error: unknown flag $arg" >&2; exit 1 ;;
    *) [ -z "$ref" ] && ref="$arg" ;;
  esac
done

should_skip() {
  echo ",$skip," | grep -q ",$1,"
}

repo_root=$(git rev-parse --show-toplevel) || exit 1
found=false

if [ -n "$ref" ]; then
  # --- Per-ref cleanup ---
  branch=$(git aint get "$ref" --format "{config:branch-pattern}") || exit 1
  wt_pattern=$(git aint get "$ref" --format "{config:worktree-pattern}") || exit 1
  tmux_name=$(git aint get "$ref" --format "{config:tmux-session-pattern}") || exit 1
  wt_dir="$repo_root/$(git config aint.worktree-dir 2>/dev/null || echo '.worktrees')/$wt_pattern"

  # Worktree
  if ! should_skip worktree && [ -d "$wt_dir" ]; then
    # Check for uncommitted changes
    wt_status=$(git -C "$wt_dir" status --porcelain 2>/dev/null)
    if [ -n "$wt_status" ]; then
      echo "worktree: $wt_dir (BLOCKED: uncommitted changes)"
      found=true
    else
      main=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
      [ -n "$main" ] || main="main"
      if git merge-base --is-ancestor "$branch" "$main" 2>/dev/null; then
        if $fix; then
          git worktree remove "$wt_dir" && echo "worktree: removed $wt_dir" || echo "worktree: failed to remove $wt_dir" >&2
        else
          echo "worktree: $wt_dir (would remove)"
          found=true
        fi
      else
        echo "worktree: $wt_dir (BLOCKED: branch $branch not merged into $main)"
        found=true
      fi
    fi
  fi

  # Branch
  if ! should_skip branch; then
    if git show-ref --verify --quiet "refs/heads/$branch" 2>/dev/null; then
      main=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
      [ -n "$main" ] || main="main"
      if git merge-base --is-ancestor "$branch" "$main" 2>/dev/null; then
        if $fix; then
          git branch -d "$branch" 2>/dev/null && echo "branch: deleted $branch" || echo "branch: failed to delete $branch" >&2
        else
          echo "branch: $branch (would delete)"
          found=true
        fi
      else
        echo "branch: $branch (BLOCKED: not merged into $main)"
        found=true
      fi
    fi
  fi

  # Tmux
  if ! should_skip tmux; then
    if tmux has-session -t "=$tmux_name" 2>/dev/null; then
      if $fix; then
        tmux kill-session -t "=$tmux_name" && echo "tmux: killed $tmux_name" || echo "tmux: failed to kill $tmux_name" >&2
      else
        echo "tmux: $tmux_name (would kill)"
        found=true
      fi
    fi
  fi

  # Tags
  if ! should_skip tags && $fix; then
    git aint update "$ref" --rm-tag "worktree:$wt_dir" --rm-tag "branch:$branch" 2>/dev/null
  fi

  if ! $fix && $found; then
    echo ""
    echo "Run with --fix to clean up."
  elif ! $fix && ! $found; then
    echo "Nothing to clean for [$ref]."
  fi

else
  # --- Broad cleanup: delegate to really hygienic ---
  args=""
  if $fix; then args="$args --fix"; fi
  # Translate --skip to --only (inverse)
  if [ -n "$skip" ]; then
    all_cats="worktrees branches tmux aints"
    only=""
    for cat in $all_cats; do
      # Normalize: cleanup uses singular (worktree, branch, tmux)
      # really hygienic uses plural (worktrees, branches, tmux, aints)
      skip_name=$(echo "$cat" | sed 's/s$//')
      if ! echo ",$skip," | grep -q ",$skip_name,"; then
        only="$only $cat"
      fi
    done
    if [ -n "$only" ]; then
      args="$args --only $only"
    fi
  fi
  git aint really hygienic $args
fi
