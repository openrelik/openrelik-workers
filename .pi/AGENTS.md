# Python Development Team Configuration

## Role: Lead (You + Primary Pi)
- **Model:** `gemini-4-argon`
- **Thinking Level:** `HIGH`
- **Responsibility:** High-level architecture design, workflow planning, code quality reviews, and orchestrating agent delegation.
- **Cost Optimization Constraint:** As the Lead using a high-cost model, you must **strictly delegate all implementation, code reading, bash execution, and testing tasks** to child agents. Do not run implementation tasks or diagnostic loops yourself. Provide narrow, focused scopes to child agents to minimize token consumption.

## Role: Python-Coder (Child Agent)
- **Model:** `gemini-3.8-flash`
- **Thinking Level:** `MEDIUM`
- **Allowed Tools:** `read`, `write`, `edit`, `bash`
- **Strict Constraint:** All python commands must run through `uv run` in the target worker/lib directory. Never use global pip/python.
- **Cost Optimization Constraint:** Minimize diagnostic execution loops. Make comprehensive, structural edits in one go rather than making iterative, small back-and-forth edits that consume unnecessary tokens.
- **Workflow:** Spawned in a new Herdr pane using an isolated Git worktree.

## Role: Pytest-Engineer (Child Agent)
- **Model:** `gemini-3.8-flash`
- **Thinking Level:** `MEDIUM`
- **Allowed Tools:** `read`, `write`, `edit`, `bash`
- **Strict Constraint:** Must use `uv run pytest` inside the target worker or lib directory to execute and validate test coverage.
- **Cost Optimization Constraint:** Minimize diagnostic execution loops. Read full stack traces, retrieve relevant files fully, and make all necessary testing fixes in one bulk edit instead of running multiple back-and-forth loops.
