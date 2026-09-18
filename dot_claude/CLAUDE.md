# Global Agentic Coding Instructions

Follow these instructions for all work unless a higher-priority instruction conflicts with them. Treat **MUST**, **ALWAYS**, and **NEVER** as mandatory.

## CRITICAL: Protect existing code

These rules ALWAYS apply to new code, maintenance, code review, and review-feedback work unless the human explicitly directs otherwise.

Make the smallest change that fully satisfies the request. NEVER perform unrelated cleanup, refactoring, modernization, renaming, reformatting, or architectural changes.

Before changing an existing code file:

1. Inspect its history with `git --no-pager log --follow -- <file>` and its target lines with `git --no-pager blame -L <start>,<end> -- <file>`.
2. Inspect affected callers and tests.
3. Treat code as **legacy** when reliable automated tests do not cover the affected behavior. When uncertain, treat it as legacy.

When legacy code must change:

1. Trace the narrowest call and data path. Identify the behavior and contracts that MUST remain unchanged.
2. Before refactoring, establish green focused tests. Add characterization tests for the affected normal, boundary, error, and side-effect paths. Cover the planned change, not every theoretical case or a coverage target.
3. If no test seam exists, add only the smallest behavior-preserving seam, then add tests.
4. Keep refactoring separate from feature behavior. Refactor in small behavior-preserving steps and run the focused tests after each step. NEVER continue with failing tests.
5. Add the feature at the narrowest seam. Preserve existing callers, APIs, stored data, formats, side effects, and errors unless the request explicitly changes them.

STOP and ask for approval if the scope expands, behavior is unclear, a practical test safety net cannot be established, or the change requires broad refactoring, a breaking contract, or a data migration. Explain the required scope, risks, and smallest alternative.

Before finishing, inspect the complete diff and affected call sites, run the relevant tests, and report intentional behavior changes or validation gaps.

## One session, one topic

NEVER do two unrelated things in one session. A feature, a bug fix, a configuration change and a tooling change are separate topics. Unrelated means a different goal, even when the files overlap. A change that the current task requires is part of the current task.

When an unrelated request arrives:

1. NEVER start it in the current session.
2. Dispatch a new agent with the `Agent` tool. Give it the complete request, the working directory, and any decision already made. This rule authorizes the `Agent` tool for this purpose.
3. Return to the work in progress, or report its state.

If the new request needs its own branch, the new agent creates the worktree with `wt`, as **Git branches and worktrees** requires.

## Run CI's own checks before every commit

NEVER commit or push before running the checks CI will run, on every module the diff touches. A red CI run that a local command would have caught is a wasted cycle for the human waiting on it.

1. List the modules the diff touches: `git status --short` / `git diff --name-only`, mapped to their Gradle module.
2. Read the CI config to get the exact task list; do not guess it and do not rely on a project's prose docs, which drift. The task list is usually built per module type — find where the pipeline composes it.
3. Run that exact list for EVERY touched module, not a subset you judge relevant.
4. Only then commit.

Run the full list again for each follow-up commit. A check that passed on the previous commit says nothing about this one, and a new file can fail a check the module passed a minute ago.

When a check cannot run locally (a PR-body validator, a signing or deployment gate), say so explicitly rather than treating it as covered — and satisfy it by reading the template or config it enforces.

## Tests: UI and unit tests

Adding, refactoring, or improving tests does not count as changing legacy production code. Do this when it strengthens coverage or makes a production change safer.

Do not test UIKit behavior directly unless necessary; these tests are brittle and difficult to set up. UI snapshot tests are acceptable.

## Code principles

The best code is no code. Every extra line adds complexity and risk. Within the requested scope, safely remove dead code and simplify verbose constructs. Do not use this rule to justify unrelated cleanup.

Do not add code for behavior the request does not require. Omit low-value or speculative code.

## Comment on GitHub only when necessary

GitHub comments create noise for people and agents. Post one only when it serves a required action, such as requesting another pull request review, resolving a review comment, or explaining a rejection. Keep it concise.

## No outreach to other people

NEVER contact another person or team, and NEVER offer to. This covers Slack messages, channel posts, emails, Jira tickets, Confluence pages, GitHub issues, and any request for a policy change, an exception, or an access grant. It covers drafts as much as sent messages.

When something is blocked, report the block and stop. Daniel decides who hears about it.

The only exception is a pull request comment that the rules in **Comment on GitHub only when necessary** require.

## GitHub

- Always check paginated data up to the end (e.g. comments in PRs)
- Prefer the `gh` CLI and its extensions, e.g. `gh stack`

## iOS Simulators

Create a dedicated simulator for each task to avoid conflicts. Give it a meaningful name based on the branch or worktree.

Use a common current model and iOS version, e.g. iPhone 17 / iOS 26.

Remove the simulator when the task is done.

## Xcode test failures and abnormal termination

- Never ignore or normalize abnormal Xcode or `xcodebuild` behavior, including a test-host crash, stuck test-session cleanup, missing or corrupt result bundle, signal termination, or other abnormal test exit.
- Treat abnormal Xcode or `xcodebuild` behavior as possible evidence of broken code, a concurrency defect, or a leaked task or continuation until investigation shows otherwise.
- Isolate the affected tests, inspect the result bundle, crash reports, diagnostics, and asynchronous task lifecycle, and check for leftover Xcode or XCTest processes.
- A later green rerun does not replace the abnormal result. Report both results and the evidence that explains the difference. Do not call the test suite green until the abnormal behavior has a concrete explanation or no longer reproduces under focused verification.

## Code comments

When adding or modifying code comments:

- Describe current behavior directly and accurately.
- Do not describe history, transitions, or absences.
- Include only non-trivial reasons, constraints, or behavior that the code does not make obvious.
- Use plain language and short, readable sentences.

## Shell commands

- Never infer what an unfamiliar command, alias, or shorthand does.
- Before you run it, use `which <command>` to identify it. For example, do not assume that `gf` means `git fetch`.
- When writing shell pipelines, **don't name variables `status`** — zsh treats it as read-only and `status=$?` fails silently, breaking exit-code propagation. Use `rc` or `result`.

### The shell sets `noclobber`

`>` fails with `file exists` when the target file is already present. This applies to every output redirection, including `2> file` and a heredoc such as `cat > file <<'EOF'`.

- To write a new file, use `>`. It fails if the file exists, which prevents an accidental overwrite.
- To overwrite an existing file on purpose, use `>|`.
- To add to a file, use `>>`.
- Read the exit code and the message. `file exists` is a `noclobber` refusal, not a permission error or a sandbox block.

## Credentials and 1Password

Minimize repeated 1Password approval prompts. Before beginning work that needs multiple secrets, identify the secrets needed and retrieve them together when practical. Reuse secrets securely within the current session; do not request the same secret again unless it is unavailable, expired, or has changed.

- Retrieve all required credentials early and in one 1Password request whenever possible.
- Reuse fetched credentials only through task-scoped environment variables.
- Store persistent credentials only in an approved secure credential store such as 1Password. Never store them in plaintext.

## Git branches and worktrees

- Use worktrees for isolated branch work. If a change needs a branch, create and manage its worktree with `wt` (Worktrunk).
- Never create a branch directly in an existing working directory or use another tool to manage worktrees or their branches.

**Never use `git stash` inside a worktree.** The stash stack lives in shared `.git/` metadata, not per-worktree state, so a `stash` in one worktree pushes onto the same global stack as every other worktree on the same repo. When parallel Claude sessions are running in sibling worktrees (the common case here), `stash pop` operations cross over and changes silently land in the wrong tree — no warning, no conflict, just lost work that needs hand recovery.

Safer alternatives, by preference:

1. **Read a file from another branch without touching the tree** — `git show <branch>:<path>` prints content to stdout. Almost always what's actually wanted when "I just want to check something on main / another branch." No checkout, no stash, no risk.
2. **Save dirty state to a file** — `git diff > /tmp/<unique>.patch` (+ `git diff --staged >> ...` if staged changes exist), then `git apply` later. Patch files live outside git's shared state.
3. **Throwaway commit** — `git add -A && git commit -m wip`, verify, then `git reset --soft HEAD~1`. Branches _are_ per-worktree, unlike the stash stack, so this stays isolated.

## Git signing and authentication

Commits use SSH signing through the 1Password SSH agent (`gpg.format=ssh`). Pushes use the same agent for SSH authentication.

Never bypass signing or hooks to work around sandbox failures. Do not use `--no-gpg-sign`, `-c commit.gpgsign=false`, or `--no-verify`. Run the operation outside the sandbox.

## Pull request comments

Add this attribution as the final line of every pull request comment, including top-level comments and thread replies: `🤖 Generated with <AGENT_NAME> (<MODEL_NAME>).`

Where "<AGENT_NAME>" is a type of the agent you are: Claude Code, Codex, Copilot, OpenCode, Kimi etc. And <MODEL_NAME> is current LLM model, e.g. Fable, GPT-6 (Astra), GPT-5.6 (Sol), DeepSeek V4 Flash, etc.

### Comment triage

When you address pull request comments with `/pr-comment-triage` or a similar workflow, monitor the pull request for new comments after you push changes to the remote.

## Dictated requests

User requests may be dictated and can contain transcription mistakes. Infer the intended meaning when it is clear from context. If an ambiguity could materially change the work, involve irreversible action, or cannot be resolved confidently, ask for clarification before proceeding.

## Local Claude Code rules

Claude Code also loads every `~/.claude/rules/*.md`.

The chezmoi source repository for this file is public. Nothing that names an employer, a customer, an internal system, or a path on this machine belongs in this file or in `dot_claude/rules/*.md`.

Rules that must stay on this machine only go in `~/.claude/rules/<name>.local.md`; chezmoi ignores that pattern, so they are never committed or pushed. Shared Claude Code rules go in `dot_claude/rules/<name>.md`. Anything meant for every machine, or for other agents reading this file as `AGENTS.md`, belongs in this file.
