<!--
Title: what changes, in plain words, ending with the version, e.g. "Milestone 6: Train Describer (0.10.0)" or
"Don't leave a transaction open after the retention run (0.8.3)".
Delete any section that doesn't apply, and these comments. Name files, tables, migrations, settings and services
in backticks. No attribution lines or session links.
-->

<!--
One short paragraph: what this does for the map or the data. Link the plan if there is one.
If stacked: "Stacked on #N (0.9.0). Once that merges, this will be pointed at `main`."
-->

## What's in it
<!--
One bullet per stage or area, bold label first: "- **Stage 1:** migration `010` adds `td_steps`…".
For a fix, use "## The bug" (what went wrong, where it was seen, with numbers) and "## The fix" instead.
-->
-

## Why
<!-- The choice a reviewer might question, and what was tried and dropped. -->

## Results
<!--
Measured numbers, with what was measured, when and how: the window, the sample size, the truth compared against.
Say what didn't improve too.
-->
| | Before | After |
|---|---|---|
| | | |

## Upgrading
<!--
What a deploy needs beyond rebuilding and restarting: migrations (the consumer applies them on start), one-off
commands, new `.env` settings, new Compose services, and an order if one matters. "Nothing beyond a rebuild" is fine.
-->
-

## Testing
- `uv run pytest` (with `TEST_DATABASE_URL`): N passed
- `uv run ruff check src tests`: clean
- In `web/`: `pnpm typecheck` and `pnpm lint` clean, `pnpm test` N passed
- <!-- New tests and what each catches. Where it ran against real data or was deployed, when, and what was seen. -->

## Release
- [ ] Version bumped in `pyproject.toml`: minor for features or schema changes, patch for fixes
- [ ] `uv lock` run
- [ ] `pnpm --dir web gen:api` run, so `web/openapi.json` carries the version
- [ ] `CHANGELOG.md` entry under the new version, naming new migrations, scripts and tables

## Notes
<!-- Defaults that differ from the plan, new dependencies, known gaps, follow-ups left for later. -->
