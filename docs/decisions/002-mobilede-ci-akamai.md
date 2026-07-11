# 002 — Why CI wasn't deploying mobile.de (it's NOT an Akamai block)

Date: 2026-07-11 · Status: **resolved (no new action)** · Owner: Martin (investigated by Claude)

## The question

Prod serves **~20.7k** cars; a local build produces **~152.8k**. The whole gap is
mobile.de Germany. The assumption going in: Akamai Bot Manager blocks the mobile.de
scrape from the GitHub-hosted (Azure) runner, so DE never reaches prod. The plan was to
beat Akamai (proxy / self-hosted runner / fingerprint impersonation), or failing that,
pace the scrape into smaller batches.

## What the evidence actually shows

**The mobile.de scrape from the GitHub runner succeeds — fully, EV *and* ICE incl. DE.**

Latest scheduled run (`29144865354`, 2026-07-11 07:39 UTC, `ubuntu-latest`, Azure
eastus2):

```
scrape (mobilede)  success
  Kurz EUR/CZK: 24.25
  Hotovo – uloženo 148256 aut do mobilede.parquet
```

148,256 rows scraped from a datacenter IP — no 403, no partial abort. **Akamai is not
blocking us.** The historical 2026-07 CI block documented in `gotchas.md` was mitigated
by the adapter changes that followed it (`CONCURRENCY=3`, every request semaphore-bound
incl. counts, progressive 5/15/45/90 s backoff on 403/429/503). Those work. There is
nothing to pace, proxy, or fingerprint — the scrape is fine.

### So why is prod stuck at 20.7k?

The daily pipeline was dying **one job later, in `build`** — not in `scrape`:

```
scrape (mobilede)  success
scrape (sauto)     success
scrape (autodraft) success
scrape (energycars) success
build              failure   ← here
deploy             skipped
```

The `build` job failed at its "pull yesterday's state from the release" step:

```
gh release download data --pattern '*.parquet' --pattern 'scrape_history.json' ...
  [ -f "/tmp/release-data/$src.parquet" ] && cp ...
##[error]Process completed with exit code 1.
```

Under `set -e`, the shell idiom `[ -f X ] && cp X …` **evaluates to non-zero when `X`
is absent** (a source with no release asset yet), aborting the whole step — so a
perfectly good 148k scrape was thrown away and `deploy` was skipped. Prod kept serving
whatever a prior **push**-triggered rebuild had last shipped from stale release state:
20,754 rows.

## Resolution — already fixed

Commit **`3282a2b`** ("fix(ci): stop build failing on absent release assets; bump
actions off Node 20"), pushed **2026-07-11 15:57 UTC** — *after* the two failed crons
(07-10 09:18, 07-11 07:39) — rewrote that step from the leaky `&&` idiom into explicit
`if [ -f … ]; then cp …; fi` blocks that cannot exit non-zero on an absent asset. Verified
present on `origin/main`.

The two push runs since the fix (15:57, 16:05) were **push**-triggered, so by design they
rebuild from release state without scraping — which is why prod is still 20.7k right now.

## Expectation / verification

The **next scheduled cron (06:00 UTC daily)** should: scrape ~148k mobile.de rows (as it
already does) → `build` now succeeds (fix is in) → `deploy` publishes → **prod jumps from
~20.7k to ~148k**, and the release payload catches up.

To confirm without waiting a day, trigger a manual `workflow_dispatch` (with scraping, not
`skip_scrape`) and watch `build`/`deploy` go green and `cars-meta.json.totalCars` on Pages
jump. This is a real prod scrape+deploy, so run it deliberately.

## Standing Akamai note (unchanged, for the record)

The block *can* return — Akamai keys on datacenter-IP reputation + cumulative volume, and
`/api/s/` is undocumented and could tighten. If a future run 403s hard mid-scrape again,
the levers, in order of reliability, are: residential/mobile **proxy** for the mobile.de
requests (dominant signal is IP), a **self-hosted residential runner** for the mobilede
leg only, `curl_cffi` with an **okhttp/Android** TLS fingerprint to match the
`X-Mobile-Client` header (dep-gated, complementary — never sufficient alone from a
datacenter IP), or the sanctioned **Search-API** (manual credential grant). Playwright
cookie-priming is a dead end (headless is 403'd on the HTML site too). But none of this is
needed today — the scrape works; the bug was in the build step and is fixed.
