A personal `~/bin` directory of standalone CLI utilities, shell scripts, and automation tools for macOS. Not a project with a build system — each script is independent.

## Common Patterns

### Shell Scripts (zsh)

- All shell scripts use zsh and source `_common.zsh` for shared utilities
- Common functions available: `_exec` (logged execution with timing), `log_message`/`log_error`, `eval_managers` (brew/mise/xcenv), `exec_unless_recently_modified` (skip-if-recent pattern)
- Scripts are executable with shebangs — run directly from `~/bin` (should be in PATH)

### Python Scripts

- Target python3, use standard library where possible
- Common pattern: CLI with argparse, optional curses interactive mode
- Config files read from `~/.config/<tool>/config.json`

### Ruby Scripts

- Use system ruby, no external gems
- Often used for plist manipulation, simulator management, or text processing

### Config Management

- Config files managed by chezmoi live at standard XDG paths (`~/.config/...`)
- Scripts may integrate with chezmoi via hooks (pre/post operations)
