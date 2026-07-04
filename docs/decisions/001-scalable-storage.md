# 001 — Scalable storage for large scrapes (enable DE ICE)

Date: 2026-07-04 · Status: accepted · Owner: Martin (implemented autonomously by Claude)

## Problem

Enabling mobile.de Germany for ICE (`ICE_COUNTRIES += "DE"`) multiplies the dataset:
measured 2026-07-04 with DE on — **133,062 mobilede rows (38.5 MB CSV)**, total
**140,975 rows**, `cars.json` = **129.0 MB**. The previous storage (CSV committed to
git daily + one `cars.json` fetched by the dashboard) fails at this scale:

- GitHub blocks any file > **100 MiB** at push (`cars.json` is 129 MB — dead on arrival);
  50 MiB triggers warnings; repos are recommended < 1 GB, hard-capped at 10 GB `.git`
  ([docs](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)).
- Daily churn of tens of MB of data in git grows history unboundedly (removed listings
  are retained forever by `merge_with_previous`, and DE churn is thousands of rows/day).
- A 129 MB JSON payload takes **9.0 s** to fetch+parse in Chromium (measured, localhost)
  and would crash mobile Safari (tab dies at ~100–200 MB JS heap,
  [verified Jan 2026](https://lapcatsoftware.com/articles/2026/1/7.html)).

Constraints: no server, free or nearly free, durable ("won't lose it"), frequent
schema changes (add/remove/alter columns), AG Grid dashboard must keep working.

## Decision

**Parquet everywhere; GitHub Releases as the canonical, versioned data store; Pages
artifact carries the payload; AG Grid stays.** No new accounts, $0.

1. **State layer** — each source's merged state is `scrapers/data/scrapes/<slug>.parquet`
   (zstd), **stringly-typed** (every column str, blanks `""`) to keep exact semantic
   parity with the old `pd.read_csv(dtype=str).fillna("")`. Git-ignored.
2. **Canonical store** — a rolling GitHub Release tagged `data` holds
   `state-<slug>.parquet` + built payload + `scrape_history.json`, updated (clobbered)
   by the daily workflow. On the 1st of each month the workflow additionally publishes an
   **immutable snapshot release** `data-YYYY-MM`. Releases allow 2 GiB/asset, no stated
   total cap, and `GITHUB_TOKEN` can manage them
   ([docs](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)).
3. **Retention bound** — new canonical column **`Odstraněno dne`** (date a listing was
   first seen missing). `merge_with_previous()` drops removed rows older than
   **`REMOVED_RETENTION_DAYS = 60`**. Because 60 d > 31 d (snapshot interval), every row
   that ever existed appears in ≥ 1 immutable monthly snapshot — nothing is ever lost,
   while live data plateaus at (live market + 60 days of churn) instead of growing forever.
4. **Payload** — `build_data.py` writes `site/data/cars.parquet` (zstd, **numeric columns
   float64** — int64 would decode to BigInt in the browser and break the grid) +
   `site/data/cars-meta.json` (the old `metadata` object). Both ship only inside the
   Pages deploy artifact; **no data is committed to git anymore**. Bootstrap seeds
   (the frozen last CSVs + a seed `scrape_history.json`) stay tracked for
   release-less first runs and offline dev.
5. **Dashboard** — AG Grid Community 33.1.1 clientSideRowModel **unchanged**; only the
   loader swaps: `hyparquet@1.26.2` + `hyparquet-compressors@1.1.1` (pinned jsDelivr ESM)
   decode `cars.parquet` into the same row objects `init(data)` always received.

## Measured evidence (real DE-scale data, 140,975 rows, 2026-07-04)

| payload | size | Chromium decode | JS heap |
|---|---|---|---|
| cars.json | 129.0 MB (7.3 MB gzip wire) | 9.0 s | 214 MB |
| cars.parquet snappy | 7.8 MB | 1.6 s | 204 MB |
| **cars.parquet zstd** | **5.5 MB** | **1.4 s** | 198 MB |

AG Grid at 141k rows: `verify_ui` scenarios grid / stav-filter / summary all PASS
(DOM stays virtualized at ~90 rendered rows). GitHub Pages serves with
`accept-ranges: bytes` (verified 206) and `access-control-allow-origin: *`, and
auto-gzips JSON — measured live against the deployed site.

Projection: ~1M rows ≈ 35–40 MB parquet — still trivially inside every limit above;
the browser payload stays bounded by retention regardless.

## Alternatives rejected

- **Git LFS** — Pages *cannot serve LFS content* (official:
  [about-git-large-file-storage](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage));
  free tier is 10 GiB storage + 10 GiB/month bandwidth (metered, 2026 model) and every
  Actions checkout of data would eat it. Wrong tool twice.
- **Keep committing CSVs/JSON** — 129 MB file exceeds the 100 MiB push block; even below
  it, daily churn bloats history and `mobilede.csv` crosses 50 MB within months.
- **GitHub Actions cache as store** — 7-day LRU eviction; not durable by design.
- **SQLite (committed or LFS)** — binary blobs delta poorly in git; browser would need
  sql.js/VFS plumbing; pandas+parquet already covers query needs with zero new infra.
- **Cloudflare R2 / Backblaze B2 / Hugging Face datasets** — all viable and free at this
  size (R2: 10 GB + zero egress; HF: generous public-dataset storage, verified
  Range+CORS). Rejected as *primary* because each needs a new account/token and the
  GitHub-native path is equally free and durable. Documented as optional off-GitHub
  mirror if extra redundancy is ever wanted (a one-step `gh release download` →
  `rclone`/`huggingface_hub` upload).
- **DuckDB-WASM + Infinite Row Model now** — unnecessary at current scale (grid verified
  at 141k client-side); costs ~35 MB WASM download and a rewrite of the custom
  SetFilter (which iterates all in-memory nodes). Kept as the documented upgrade path
  if live data ever exceeds ~500k rows: Pages supports Range requests (verified), but
  note the gzip+Range interaction gotcha in docs/gotchas.md.

## Consequences

- `docs/conventions.md` "CSVs are the sole output format" is superseded: parquet is the
  storage/payload format; CSV remains only as frozen bootstrap seed.
- New dependency: `pyarrow` (build + scrape legs).
- Schema is 27 columns (`Odstraněno dne` added after `Stav`).
- The daily workflow no longer commits data; the repo becomes code-only again.
- First run on main bootstraps state from the frozen seed CSVs, then the release takes
  over; afterwards the seeds may be deleted at leisure.
- Local dev: `gh release download data` fetches current state (private repo needs gh
  auth); without it, seeds keep everything working offline.
