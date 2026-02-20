The architecture of git-aint is deliberately boring.

Markdown files with YAML frontmatter are the single source of truth.
No databases, no SQLite, no custom binary formats. One file per task,
one directory per epic. Minimal core commands, extensible workflows
through git aliases.

You can read every task with `cat`. You should read tasks you're creating.

Everything is files. RFCs and ADRs are files. Execution plans are files.
Epics are files. Tasks are files. Your messy ideas are also files. Files
are meant to be read by humans and tracked by Git.

Git handles everything that looks hard: sync, concurrency, conflict
resolution, history. The .aint/ directory is a git worktree on the
aint-sync branch, completely isolated from your main branch. Your
code and your tasks share a repo but never collide.

Every command is non-interactive. No prompts, no "are you sure?"
dialogs. Use --force flags instead. This makes every command safe
for AI agents to call without supervision.

Error messages always suggest the next step. Rust's compute is cheap;
user time is not. Timestamps like created_at and updated_at come from
git log, not from fields you have to maintain.

Git worktrees enable parallel work: one worktree per task, managed by
tmux integration that lets multiple agents execute side by side.
