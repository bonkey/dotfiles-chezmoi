## Fundamental Coding Rules

## General Assistant Rules

- Do what has been asked; nothing more, nothing less. Do not show off!
- Do not explain simple changes in code, but be smart about it. Big changes require proper narrative.
- NEVER create new files unless they're absolutely necessary for achieving your goal or you're just asked for it
- ALWAYS prefer editing an existing file to creating a new one
- NEVER proactively create documentation files (*.md), tests or README files. Only do it if explicitly requested by the user
- Do use documentation (e.g. Ref MCP) or web search when you are not sure about something or you are stuck

### Architecture & Design Principles

- Adhere religiously to high cohesion and low coupling rule
- Follow "Tell, don't ask" principle: objects should expose behavior, not internal state
- Do create deep modules (narrow, dedicated public interface)

### Comments & Documentation

- Never add comments after changes
- Do not use comments to explain simple code
- Always resolve code readability issues with proper code design and naming instead of comments
- Comments explaining hard issues or bugs or instructions for LLM can be preserved

## Git --no-pager

Always use --no-pager in all git commands where it's allowed. It helps to avoid hanging on interactive review

## Never overwrite $PATH

Whenever you write a shell script, never fucking ever create a variable with "path" name since it will fucking break the whole shell. Same for other sensitive variables.

## No PAGER in shell

Whenever using shell, always set export PAGER=""

## No tests!

DO NOT FUCKING RUN ANY TESTS UNLESS REQUESTED!!!

Never ever, do not run tests until asked!

They often fail without proper setup.
