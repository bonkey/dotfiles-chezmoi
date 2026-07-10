## Fundamental Coding Rules

### General Assistant Rules

- Do what has been asked; nothing more, nothing less. Do not show off!
- Do not explain simple changes in code, but be smart about it. Big changes require proper narrative.
- NEVER create new files unless they're absolutely necessary for achieving your goal or you're just asked for it
- ALWAYS prefer editing an existing file to creating a new one
- NEVER proactively create documentation files (\*.md), tests or README files. Only do it if explicitly requested by the user
- Do use documentation (e.g. Ref MCP) or web search when you are not sure about something or you are stuck

### Architecture & Design Principles

- Adhere religiously to high cohesion and low coupling rule
- Follow "Tell, don't ask" principle: objects should expose behavior, not internal state
- Do create deep modules (narrow, dedicated public interface)

### Comments & Documentation

- Do not use comments to explain simple code
- Always resolve code readability issues with proper code design and naming instead of comments
- Comments explaining hard issues or bugs or instructions for LLM can be preserved
- Write docs and comments in present state: describe what the code is, not how it changed. Remove history/transition phrasing ("previously", "migrated from", "no longer", "instead of") unless history is the purpose of the file.
- Preserve useful constraints, reasons, and warnings as current facts. Example: "changed to 30s because 10s was flaky" → "30s: shorter values flake under CI load". Keep only sentences a reader needs without knowing the old state.
- Workflow: define scope, skip history-focused files (changelogs, migration guides, ADRs), grep and read, make minimal reviewable edits, verify no important information was lost, and report per file as before → after.

## Git --no-pager

Always use --no-pager in all git commands where it's allowed. It helps to avoid hanging on interactive review

## Never overwrite $PATH

Whenever you write a shell script, never fucking ever create a variable with "path" name since it will break the whole shell. Same for other sensitive variables.

## No PAGER in shell

Whenever using shell, always set export PAGER=""

## Do Not Run Tests Unless Requested

Never run tests proactively. They often fail without the required local setup; run them only when explicitly asked.
