# Triage

Triage tasks in the `## New` section of `TASKS.md`.

If `## New` is empty (no unchecked items), print "Nothing to triage." and stop.

Use the Agent tool with `model: "haiku"` to classify the tasks — pass all New items in one call to keep cost low.

**Agent prompt:** Classify each task as Atomic or Needs Scoping using these rules:

Atomic — implementable without further discussion (specific file named, behavior clearly described, < 5 files affected):

- Diagnosed bug with file/line → `flow:ralph · model:haiku · effort:low`
- UI text or CSS tweak → `flow:ralph · model:haiku · effort:low`
- UI change requiring screenshot verification (layout, AG Grid) → `flow:ralph · model:sonnet · effort:low`
- AG Grid feature (new column, filter, grouping logic) → `flow:ralph · model:sonnet · effort:medium`
- New feature touching < 3 files, clearly scoped → `flow:feature-dev · model:sonnet · effort:medium`
- Multi-file or schema-wide change, still well-scoped → `flow:feature-dev · model:opus · effort:high`

Needs Scoping — vague, touches unknown scope, requires design decision, or is a new external data source:

- Write 1–3 specific clarifying questions (not generic — specific to what's ambiguous about THIS task)
- Always scoping: new data sources, "widen/expand/add" without specifics, schema changes touching build + UI + data

Return JSON:

```json
[
  { "text": "exact task text from New", "category": "atomic", "flow": "ralph", "model": "haiku", "effort": "low", "blocked_by": "" },
  { "text": "exact task text", "category": "scoping", "questions": ["Q1: ...", "Q2: ..."] }
]
```

After the agent returns results, update `TASKS.md`:

1. Find the highest existing task ID (`**#N**`) anywhere in the file. Assign next sequential IDs to incoming tasks.

2. For each Atomic task, append to the END of `## Atomic` (after the last existing item):

   ```
   - [ ] **#N** <task text>
     > flow:X · model:Y · effort:Z
   ```

   Append `· blocked-by: #N` to the metadata line if `blocked_by` is non-empty.

3. For each Needs Scoping task, append to the END of `## Needs Scoping` (after the last existing item):

   ```
   - [ ] **#N** <task text>
     > ❓ Q1: ...
     > ❓ Q2: ...
   ```

   One `> ❓` line per question so the user can reply directly under each one.

4. Remove triaged items from `## New`; leave only the placeholder comment.

5. Do NOT modify tasks already in Atomic, Needs Scoping, or Done.

6. Preserve all other content and formatting in the file.
