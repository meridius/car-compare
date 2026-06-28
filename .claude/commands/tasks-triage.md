# Triage

Triage tasks in the `## New` section of `TASKS.md`.

If `## New` is empty (no unchecked items), print "Nothing to triage." and stop.

Use the Agent tool with `model: "haiku"` to classify the tasks — pass all New items in one call to keep cost low.

**Agent prompt:** Classify each task as Atomic or Needs Scoping using these rules:

**Default to Atomic. Assume sensible defaults instead of asking.** Most tasks are implementable now if you make the obvious default decisions. When a detail is ambiguous but has a clear conventional answer (which columns, ordering, placement, thresholds, a detection rule, where a small change lives), PICK the default, record it in an `assumptions` field, and classify Atomic. The owner can veto a written assumption far more cheaply than answering a question up front.

Atomic — implementable now (choose defaults for anything unstated):

- Diagnosed bug with file/line → `flow:ralph · model:haiku · effort:low`
- UI text or CSS tweak → `flow:ralph · model:haiku · effort:low`
- UI change requiring screenshot verification (layout, AG Grid) → `flow:ralph · model:sonnet · effort:low`
- AG Grid feature (new column, filter, grouping logic) → `flow:ralph · model:sonnet · effort:medium`
- New feature touching < 3 files, scoped (or scopeable with a default) → `flow:feature-dev · model:sonnet · effort:medium`
- Multi-file or schema-wide change with an obvious approach → `flow:feature-dev · model:opus · effort:high`
- Ambiguous detail with a clear default → choose it, write `assumptions`, classify Atomic (do NOT ask)

Needs Scoping — ONLY when the decision is genuinely the owner's and a wrong default is costly or hard to reverse. Be strict; this is the exception, not the default:

- Integrating a NEW external data source / paid API (which provider, auth, cost, ToS/legal — e.g. scraping a new site)
- Spending money, or irreversible / legal-sensitive actions
- Product-direction or prioritization calls with no obvious default

For these, write 1–3 specific clarifying questions. For everything else, default and promote to Atomic.

Return JSON:

```json
[
  { "text": "exact task text from New", "category": "atomic", "flow": "ralph", "model": "haiku", "effort": "low", "blocked_by": "", "assumptions": "default decisions you made (or '' if none were needed)" },
  { "text": "exact task text", "category": "scoping", "questions": ["Q1: ...", "Q2: ..."] }
]
```

After the agent returns results, update `TASKS.md`:

1. Find the highest existing task ID (`**#N**`) anywhere in the file. Assign next sequential IDs to incoming tasks.

2. For each Atomic task, append to the END of `## Atomic` (after the last existing item):

   ```
   - [ ] **#N** <task text>
     > flow:X · model:Y · effort:Z
     > 📌 assumes: <assumptions>
   ```

   Append `· blocked-by: #N` to the metadata line if `blocked_by` is non-empty. Include the `> 📌 assumes:` line only when `assumptions` is non-empty.

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
