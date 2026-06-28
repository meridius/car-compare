# Work

Pick and execute the next available task from `## Atomic` in `TASKS.md`.

## Step 1 — Select task

Read `TASKS.md`. Find the first unchecked (`- [ ]`) item in `## Atomic` where:

- No `blocked-by:` in its metadata, OR all tasks it is blocked by are checked off (`- [x]`) in `## Done`

If no eligible task exists, print "No unblocked Atomic tasks. Check Needs Scoping or add new tasks." and stop.

Print: "Working on: <task text>"

## Step 2 — Execute

Read the task's `flow`, `model`, and `effort` metadata line.

**Every feature is test-driven or, at minimum, test-verified.** A task is NOT done until `./bin/test.sh` passes, and any change to logic must add or extend a test that would fail without the change. Tests are stdlib `unittest` (no extra deps) under `tests/`; see `docs/conventions.md` → Testing.

**If `flow:ralph`** — implement directly. Spawn a subagent with the task's `model` to do the work. The subagent should:

1. Understand the task fully (read relevant files first).
2. **Write the test first (test-driven).** For any change to logic — `scrapers/core/`, `build/`, or the reference CSVs — add or extend a test in `tests/` that captures the intended behavior, then run `./bin/test.sh` and confirm it FAILS for the right reason before implementing. (Pure presentation changes — `site/` CSS/markup with no data/logic — are exempt from unit tests; rely on `verify_ui.py`.)
3. Implement until the new test passes.
4. Verify — every applicable check must pass:
   - **Logic** (`scrapers/core/`, `build/`, reference CSVs): `./bin/test.sh` green AND `python build/build_data.py` rebuilds without error. This is the fast offline loop — do NOT run a full scrape for logic/build changes.
   - **Scraper adapters** (`scrapers/sources/*.py` only): also run `python -m scrapers.run --source <name>` on a fresh CSV (delete existing first); check output columns + row counts.
   - **UI** (`site/`): run `python3 build/verify_ui.py` for the affected scenario(s), read the screenshot at `tmp/ui-verify/`, confirm it looks correct.
5. If verification fails: fix and re-verify (up to 3 attempts). If still failing, leave the task unchecked, add a `> ⚠️ blocked: <reason>` note, and stop.

**If `flow:feature-dev`** — invoke the `feature-dev:feature-dev` skill via the Skill tool before implementing. The test-driven rule still applies: the feature lands with its tests and `./bin/test.sh` must pass before Step 3.

## Step 3 — Commit

After successful verification, do this in order so everything lands in one commit:

1. In `TASKS.md`: change `- [ ]` to `- [x]` on the task line, move the full task entry (including metadata line) to `## Done`
2. Stage all changed files (implementation + tests + `TASKS.md`)
3. Commit with a short descriptive message (English, imperative mood)

One commit = implementation + task bookkeeping. Do not commit in two steps.

Print: "Done: #N <task text>"
