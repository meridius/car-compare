"""Backfill / reconcile the Přidáno + Upraveno date columns on the reference CSVs.

Přidáno = date a row (by PK) first appeared in git history.
Upraveno = date its content last changed, IGNORING the two date columns
           (so re-running this script is idempotent — it never bumps itself).

Derivation walks `git log --follow` (crosses the electric/combustion → unified
rename) oldest→newest, hashing each row's non-date content at every commit, then
reconciles against the current working tree (uncommitted new / changed rows → today).

Usage:
    python build/backfill_ref_dates.py            # both reference CSVs
    python build/backfill_ref_dates.py --check    # exit 1 if any file would change
"""
import argparse
import csv
import hashlib
import io
import os
import subprocess
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_DIR = os.path.join(BASE_DIR, "scrapers", "data", "reference")

PRIDANO = "Přidáno"
UPRAVENO = "Upraveno"
DATE_COLS = (PRIDANO, UPRAVENO)

# PK column per reference file.
PK_BY_FILE = {
    "ice_specs.csv": "Jednoznačná varianta vozu",
    "ev_specs.csv": "Model auta",
}


def row_content_hash(row):
    """Stable hash of a row's content, EXCLUDING the two date columns.

    Excluding them makes re-runs idempotent; a pre-migration blob (no date cols)
    hashes identically to the current row once the date cols are appended.
    """
    items = sorted((k, v) for k, v in row.items() if k not in DATE_COLS)
    payload = "\x1f".join(f"{k}\x1e{v}" for k, v in items)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def compute_dates(snapshots):
    """Derive {pk: {Přidáno, Upraveno}} from ordered content snapshots.

    snapshots: list of (date_str, {pk: content_hash}) oldest → newest, where
    content_hash already excludes the date columns.
    """
    pridano = {}
    upraveno = {}
    last_hash = {}
    for date_str, rows in snapshots:
        for pk, h in rows.items():
            if pk not in pridano:
                pridano[pk] = date_str
                upraveno[pk] = date_str
            elif last_hash.get(pk) != h:
                upraveno[pk] = date_str
            last_hash[pk] = h
    return {pk: {PRIDANO: pridano[pk], UPRAVENO: upraveno[pk]} for pk in pridano}


def _git(*args):
    return subprocess.run(
        ["git", *args], cwd=BASE_DIR, capture_output=True, text=True, check=True
    ).stdout


def _commit_paths(rel_path):
    """[(sha, date, path_at_that_commit)] oldest→newest, following renames.

    --name-status emits the historical path per commit (R<score>\\told\\tnew on a
    rename) so `git show <sha>:<path>` reads the right blob even before the
    electric/combustion → unified rename.

    NB: `--follow` is incompatible with `--reverse` (git collapses the log to a
    single commit), so we read newest→oldest and reverse in Python.
    """
    out = _git(
        "log", "--follow", "--date=short",
        "--format=C\x01%H\x01%ad", "--name-status", "--", rel_path,
    )
    commits = []
    sha = cdate = None
    for line in out.splitlines():
        if line.startswith("C\x01"):
            _, sha, cdate = line.split("\x01")
        elif line.strip() and sha:
            parts = line.split("\t")
            path = parts[-1]  # newpath on rename, else the path
            commits.append((sha, cdate, path))
            sha = None  # one path entry per commit block
    commits.reverse()  # oldest → newest
    return commits


def _blob_rows(sha, path, pk_col):
    """{pk: content_hash} for a file blob at a commit. Empty if unreadable."""
    try:
        text = _git("show", f"{sha}:{path}")
    except subprocess.CalledProcessError:
        return {}
    rows = {}
    for row in csv.DictReader(io.StringIO(text)):
        pk = (row.get(pk_col) or "").strip()
        if pk:
            rows[pk] = row_content_hash(row)
    return rows


def snapshots_from_git(rel_path, pk_col):
    """Ordered [(date, {pk: hash})] across the file's full --follow history."""
    return [
        (cdate, _blob_rows(sha, path, pk_col))
        for sha, cdate, path in _commit_paths(rel_path)
    ]


def _read_csv_raw(path):
    """(header, rows) as exact cell strings — no pandas coercion / reformatting."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def process_file(fname, today, write=True):
    """Backfill one reference file. Returns True if the on-disk content changed."""
    path = os.path.join(REF_DIR, fname)
    pk_col = PK_BY_FILE[fname]
    rel_path = os.path.relpath(path, BASE_DIR)

    header, data = _read_csv_raw(path)
    pk_idx = header.index(pk_col)
    has_dates = header[-2:] == [PRIDANO, UPRAVENO]
    base_cols = header[:-2] if has_dates else header

    # Working-tree snapshot (excluding date cols) → uncommitted new/changed rows
    # fold in as a final "today" snapshot, so compute_dates handles reconcile too.
    wt_rows = {}
    for r in data:
        row = dict(zip(base_cols, r[: len(base_cols)]))
        pk = (row.get(pk_col) or "").strip()
        if pk:
            wt_rows[pk] = row_content_hash(row)

    snapshots = snapshots_from_git(rel_path, pk_col) + [(today, wt_rows)]
    dates = compute_dates(snapshots)

    out_header = base_cols + [PRIDANO, UPRAVENO]
    out_rows = []
    for r in data:
        cells = r[: len(base_cols)]
        pk = (dict(zip(base_cols, cells)).get(pk_col) or "").strip()
        d = dates.get(pk, {PRIDANO: today, UPRAVENO: today})
        out_rows.append(cells + [d[PRIDANO], d[UPRAVENO]])

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(out_header)
    w.writerows(out_rows)
    new_text = buf.getvalue()

    with open(path, encoding="utf-8", newline="") as f:
        changed = f.read() != new_text
    if changed and write:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any file would change; write nothing")
    args = ap.parse_args(argv)
    today = date.today().isoformat()

    any_changed = False
    for fname in PK_BY_FILE:
        changed = process_file(fname, today, write=not args.check)
        any_changed = any_changed or changed
        if args.check:
            verb = "would change" if changed else "up to date"
        else:
            verb = "updated" if changed else "unchanged"
        print(f"  {fname}: {verb}")
    if args.check and any_changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
