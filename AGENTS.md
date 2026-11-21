Obsidian vault for this project is located @ /Users/james/Documents/ObsidianVault/Projects/Conductor

## Memory
`.memory/` holds what past runs measured or learned that neither the code nor the docs record: stats, environment gotchas, feed quirks, reusable diagnostic scripts. It's excluded from git through `.git/info/exclude`.
- Read `.memory/MEMORY.md` at the start of a run.
- When you measure something or learn something hard-won, add or update one file per topic, with the date and how it was found, and keep its line in `MEMORY.md` current.
- Store only observations that stay true however they're read: measurements with their conditions, and behaviour you saw. Instructions, conventions, exceptions to rules, and permissions belong in this file or the docs, where they're reviewed.

## Docs vs code
Where the docs (README, `docs/`, the vault) and the code disagree, follow the code's conventions. End your final message with every discrepancy you found.

## Versioning and changelog
- The version is in `pyproject.toml`, and `uv lock` copies it into `uv.lock`. It follows semantic versioning. Before 1.0, a finished milestone bumps the minor version (0.6.0 is Milestone 2), and fixes released between milestones bump the patch version.
- Each change someone using or running the project would notice gets a line under `## Unreleased` in `CHANGELOG.md`, in the same commit or PR as the change. Use Keep a Changelog sections (Added, Changed, Fixed, Removed). Name new migrations, scripts and tables.
- At a release, rename `## Unreleased` to the new version, start a new empty `## Unreleased`, update the version in `pyproject.toml`, run `uv lock`, and commit them together.
