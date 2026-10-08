# algorithmic_trading

Options swing-trading research and backtesting. The Python package `options_bt` is in `src/`. Environments are managed with uv.

- Quality gate (run before every commit): `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`
- Practices: TDD; logging through `logging.getLogger(__name__)`; specific errors (`DataError`, `ConfigError`, `NoContractFound`); readable, maintainable code. When in doubt, write less code.

## Subagent conventions

- **Implementers, per-task reviewers and re-reviewers run on Sonnet.**
- **The final whole-branch review always runs on Opus.** It focuses on code quality: repeated blocks that should be functions, too many comments, speed (profiled), and other quality issues. Use the standard prompt in `docs/superpowers/reviews/final-quality-review-prompt.md`.
- **The user reviews the final-review findings before any fix work is dispatched.** Present them a summary of the findings and the proposed fix list, and wait for their go-ahead and scope before dispatching implementers. This applies to every future fix list from a final review.
- Ask before changing any of these conventions.

## Punch list

- `docs/punch-list.md` is the single list of things we've decided to come back to later.
- Whenever a review, a discussion or the user defers something, add it there with a short description, where it came from (review/date), and any measurements.
- When an item is done or dropped, move it to **Closed** with the commit or the reason.
