## Memory
`.memory/` holds what past runs measured or learned that neither the code nor the docs record: stats, environment gotchas, feed quirks, reusable diagnostic scripts. It's excluded from git through `.git/info/exclude`.
- Read `.memory/MEMORY.md` at the start of a run.
- `.memory/` isn't tracked, so a worktree has none: use the main checkout's (`git worktree list | head -1` gives its path).
- When you measure something or learn something hard-won, add or update one file per topic, with the date and how it was found, and keep its line in `MEMORY.md` current.
- Store only observations that stay true however they're read: measurements with their conditions, and behaviour you saw. Instructions, conventions, exceptions to rules, and permissions belong in this file or the docs, where they're reviewed.

## Checks
Run everything from the repo root: entry points read `.env` from the current directory. Commands are in the README's Usage section.
- `uv run pytest` with `TEST_DATABASE_URL` pointing at a database it may wipe. Without it the database tests skip and the run still passes.
- `uv run ruff check src tests` (`docs/spikes/` isn't kept lint-clean).
- In `web/`: `pnpm typecheck`, `pnpm lint`, `pnpm test`.

## Docs vs code
Where the docs (README, `docs/`) and the code disagree, follow the code's conventions. End your final message with every discrepancy you found.

## Pull requests
Write each PR's description from `.github/pull_request_template.md`. When PRs are stacked, open each against the one below it and point it at `main` once that one merges.

## Versioning and changelog
Every milestone, and every PR that changes behaviour, does four things in the same PR:
- Bumps the version in `pyproject.toml`. This follows semver; before 1.0, bump the minor version for features or schema changes and the patch version for fixes.
- Runs `uv lock`, so `uv.lock` carries the new version.
- Regenerates `web/openapi.json` and the front end's types (`pnpm --dir web gen:api`): the schema carries the version, and `test_api.py` fails until it matches.
- Adds a [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) entry under the new version in `CHANGELOG.md` (Added, Changed, Fixed, Removed). Name new migrations, scripts and tables.
