# Scratchpads

Keep every scratchpad folder in `~/Desktop/scratchpads`. This rule replaces the session scratchpad directory that the harness supplies, and `/tmp` or `$TMPDIR`. Use one subfolder for each task, named after the branch or the worktree.

The sandbox does not permit a write to the Desktop, and the failure can be silent. Run the first `mkdir -p` for a new scratchpad folder outside the sandbox.
