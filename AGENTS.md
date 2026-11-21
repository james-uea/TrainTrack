Obsidian vault for this project is located @ /Users/james/Documents/ObsidianVault/Projects/Conductor

## Memory
`.memory/` holds what past runs measured or learned that neither the code nor the docs record: stats, environment gotchas, feed quirks, reusable diagnostic scripts. It's excluded from git through `.git/info/exclude`.
- Read `.memory/MEMORY.md` at the start of a run.
- When you measure something or learn something hard-won, add or update one file per topic, with the date and how it was found, and keep its line in `MEMORY.md` current.
- Store only observations that stay true however they're read: measurements with their conditions, and behaviour you saw. Instructions, conventions, exceptions to rules, and permissions belong in this file or the docs, where they're reviewed.

## Docs vs code
Where the docs (README, `docs/`, the vault) and the code disagree, follow the code's conventions. End your final message with every discrepancy you found.

## Versioning and changelog
Every milestone, and every PR that changes behaviour, does three things in the same PR:
- Bumps the version in `pyproject.toml`. This follows semver; before 1.0, bump the minor version for features or schema changes and the patch version for fixes.
- Runs `uv lock`, so `uv.lock` carries the new version.
- Adds a [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) entry under the new version in `CHANGELOG.md` (Added, Changed, Fixed, Removed). Name new migrations, scripts and tables.
