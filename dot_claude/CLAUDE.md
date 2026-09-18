# git worktrees

**Never use `git stash` inside a worktree.** The stash stack lives in shared `.git/` metadata, not per-worktree state, so a `stash` in one worktree pushes onto the same global stack as every other worktree on the same repo. When parallel Claude sessions are running in sibling worktrees (the common case here), `stash pop` operations cross over and changes silently land in the wrong tree — no warning, no conflict, just lost work that needs hand recovery.

Safer alternatives, by preference:

1. **Read a file from another branch without touching the tree** — `git show <branch>:<path>` prints content to stdout. Almost always what's actually wanted when "I just want to check something on main / another branch." No checkout, no stash, no risk.
2. **Save dirty state to a file** — `git diff > /tmp/<unique>.patch` (+ `git diff --staged >> ...` if staged changes exist), then `git apply` later. Patch files live outside git's shared state.
3. **Throwaway commit** — `git add -A && git commit -m wip`, verify, then `git reset --soft HEAD~1`. Branches _are_ per-worktree, unlike the stash stack, so this stays isolated.

Also: when writing shell pipelines, **don't name variables `status`** — zsh treats it as read-only and `status=$?` fails silently, breaking exit-code propagation. Use `rc` or `result`.

# Dictated requests

User requests may be dictated and can contain transcription mistakes. Infer the intended meaning when it is clear from context. If an ambiguity could materially change the work, involve irreversible action, or cannot be resolved confidently, ask for clarification before proceeding.

# 1Password access

Minimize repeated 1Password approval prompts. Before beginning work that needs multiple secrets, identify the secrets needed and retrieve them together when practical. Reuse secrets securely within the current session; do not request the same secret again unless it is unavailable, expired, or has changed.

# Local Claude Code rules

Claude Code also loads every `~/.claude/rules/*.md`. Rules that must stay on this machine only go in `~/.claude/rules/<name>.local.md`; chezmoi ignores that pattern, so they are never committed or pushed. Anything meant for every machine, or for other agents reading this file as `AGENTS.md`, belongs in this file.
