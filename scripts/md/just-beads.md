Beads got the vision right: issues should live in the repo, travel
with the code, and never require a running server. We agree on all of that.

git-aint takes a simpler path. No SQLite, no Dolt, no custom merge drivers.
Just markdown files on a single branch. Fully explicit, fully readable.
You can `cat` a task. You can edit it in vim. You can `grep` your backlog.

Built for interactive agent-driven workflows: an AI reads a task,
picks it up, does the work, closes it. No API tokens, no webhooks.
git-aint is thin automation over files you already know how to use.
