# Python Development Team Configuration

## Role: Lead (You + Primary Pi)
- **Model:** `gemini-4-argon`
- **Thinking Level:** `HIGH`
- **Responsibility:** High-level architecture design, workflow planning, code quality reviews, and merging agent branches.

## Role: Python-Coder (Child Agent)
- **Model:** `gemini-3.8-flash`
- **Thinking Level:** `MEDIUM`
- **Allowed Tools:** `read`, `write`, `edit`, `bash`
- **Strict Constraint:** All python commands must run through `uv run` in the target worker/lib directory. Never use global pip/python.
- **Workflow:** Spawned in a new Herdr pane using an isolated Git worktree.

## Role: Pytest-Engineer (Child Agent)
- **Model:** `gemini-3.8-flash`
- **Thinking Level:** `MEDIUM`
- **Allowed Tools:** `read`, `write`, `edit`, `bash`
- **Strict Constraint:** Must use `uv run pytest` inside the target worker or lib directory to execute and validate test coverage.
