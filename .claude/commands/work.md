# Work

Pick and execute the next available task from `## Atomic` in `TASKS.md`.

## Step 1 — Select task

Read `TASKS.md`. Find the first unchecked (`- [ ]`) item in `## Atomic` where:

- No `blocked-by:` in its metadata, OR all tasks it is blocked by are checked off (`- [x]`) in `## Done`

If no eligible task exists, print "No unblocked Atomic tasks. Check Needs Scoping or add new tasks." and stop.

Print: "Working on: <task text>"

## Step 2 — Execute

Read the task's `flow`, `model`, and `effort` metadata line.

**If `flow:ralph`** — implement directly. Spawn a subagent with the task's `model` to do the work. The subagent should:

1. Understand the task fully (read relevant files first)
2. Implement the change
3. Verify:
   - For any change under `site/`: run `python3 build/verify_ui.py --page index --scenario grid`, read the screenshot at `tmp/ui-verify/`, confirm it looks correct. Run additional scenarios if the change affects a specific view.
   - For any change under `scrapers/` or `build/`: run the affected scraper with `python -m scrapers.run --source <name>` on a fresh CSV (delete existing first), check output columns and row counts.
4. If verification fails: fix and re-verify (up to 3 attempts). If still failing, leave the task unchecked, add a `> ⚠️ blocked: <reason>` note, and stop.

**If `flow:feature-dev`** — invoke the `feature-dev:feature-dev` skill via the Skill tool before implementing.

## Step 3 — Commit

After successful verification, do this in order so everything lands in one commit:

1. In `TASKS.md`: change `- [ ]` to `- [x]` on the task line, move the full task entry (including metadata line) to `## Done`
2. Stage all changed files (implementation + `TASKS.md`)
3. Commit with a short descriptive message (English, imperative mood)

One commit = implementation + task bookkeeping. Do not commit in two steps.

Print: "Done: #N <task text>"
