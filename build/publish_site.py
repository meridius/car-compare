"""Publish the static site as a versioned copy, swapped in atomically.

The public site sits behind a CDN that caches every file for weeks and keys on
the full URL. So every local asset an HTML page loads — scripts, the
stylesheet, the data fetches in the scripts — gets `?v=<build id>` appended,
and a new build means new URLs. Only the entry pages (index/reference/
transmissions.html) keep fixed names; those are purged from the CDN after the
swap. The build id is the git sha plus the build timestamp, because the data
changes daily without a commit.

    python build/publish_site.py build --out DIR [--version V]
        versioned copy of site/ into DIR (the GitHub Pages deploy uses this)
    python build/publish_site.py release --public DIR
        DIR/releases/<ts>/ + atomic swap of DIR/current, keeps the newest 3
    python build/publish_site.py purge --base-url URL --zone-id Z --token-file F
        purge the entry pages of URL from Cloudflare (run after `release`)
    python build/publish_site.py check DIR
        exit 1 if any local reference in DIR is unversioned

`build` and `release` both fail (and `release` leaves `current` untouched) if a
local reference escapes the versioning — e.g. a new fetch outside data/, which
the JS rewrite deliberately does not guess at.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
KEEP_RELEASES = 3
# Not shipped: developer notes, and dotfiles (site/data/.gitkeep).
_SKIP_DIRS = {"docs", "__pycache__"}

# src="…" / href="…" in HTML. Local = not a scheme / protocol-relative URL,
# not an in-page anchor. Entry pages (*.html, optionally with #fragment) keep
# their fixed names — they are what gets purged.
_HTML_REF_RE = re.compile(r'\b(src|href)="([^"]+)"')
# Quoted string literals in JS that are a data/ path.
_JS_DATA_RE = re.compile(r'(["\'])(data/[^"\'?#\s]+)\1')
# Any quoted JS literal that looks like a local asset path — the check's net,
# wider than what version_js rewrites, so a new unversioned kind fails loud.
_JS_ASSET_RE = re.compile(
    r'(["\'])((?![a-z]+:|//)[\w./-]+\.(?:js|mjs|css|json|parquet|csv|png|jpe?g|svg|ico|webp|woff2?))'
    r'(\?[^"\']*)?\1')


class PublishError(Exception):
    pass


def _is_local_asset(url: str) -> bool:
    if not url or url.startswith("#") or url.startswith("//"):
        return False
    if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.IGNORECASE):  # https:, mailto:, data:
        return False
    return not re.match(r"^[^?#]*\.html(#.*)?$", url)


def version_html(text: str, version: str) -> str:
    """Append ?v=<version> to every local asset src/href (idempotent)."""
    def sub(m):
        attr, url = m.group(1), m.group(2)
        if not _is_local_asset(url) or "?" in url:
            return m.group(0)
        return f'{attr}="{url}?v={version}"'
    return _HTML_REF_RE.sub(sub, text)


def version_js(text: str, version: str) -> str:
    """Append ?v=<version> to every quoted "data/…" literal (idempotent)."""
    return _JS_DATA_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}?v={version}{m.group(1)}", text)


_REWRITERS = {".html": version_html, ".js": version_js, ".mjs": version_js}


def unversioned_refs(site_dir: Path) -> list:
    """(file, reference) for every local asset reference lacking ?v=."""
    found = []
    for path in sorted(site_dir.rglob("*")):
        if path.suffix == ".html":
            for m in _HTML_REF_RE.finditer(path.read_text(encoding="utf-8")):
                url = m.group(2)
                if _is_local_asset(url) and "v=" not in url.partition("?")[2]:
                    found.append((str(path.relative_to(site_dir)), url))
        elif path.suffix in (".js", ".mjs"):
            for m in _JS_ASSET_RE.finditer(path.read_text(encoding="utf-8")):
                if "v=" not in (m.group(3) or ""):
                    found.append((str(path.relative_to(site_dir)), m.group(2)))
    return found


def _ignore(directory, names):
    return [n for n in names if n.startswith(".") or n in _SKIP_DIRS]


def build_site(site_dir: Path, out_dir: Path, version: str) -> None:
    """Versioned copy of site_dir into out_dir (must not exist); raises on leftovers."""
    shutil.copytree(site_dir, out_dir, ignore=_ignore)
    # The web server runs as another user than the job: world-readable.
    os.chmod(out_dir, 0o755)
    for path in out_dir.rglob("*"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
        rewrite = _REWRITERS.get(path.suffix)
        if rewrite:
            path.write_text(rewrite(path.read_text(encoding="utf-8"), version),
                            encoding="utf-8")
    leftovers = unversioned_refs(out_dir)
    if leftovers:
        raise PublishError("unversioned local references: "
                           + ", ".join(f"{f}: {r}" for f, r in leftovers))


def release(site_dir: Path, public: Path, sha: str, ts: str) -> Path:
    """public/releases/<ts>/, then repoint public/current at it, keep the newest 3.

    The copy is written under a hidden partial name and renamed into place, and
    `current` is swapped with a rename of a fresh symlink over the old one, so a
    reader (the web server follows `current` per request) never sees a
    half-written release. On any failure `current` is left as it was.
    """
    releases = public / "releases"
    final = releases / ts
    if final.exists():
        raise PublishError(f"release {final} already exists")
    releases.mkdir(parents=True, exist_ok=True)
    partial = releases / f".{ts}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    try:
        build_site(site_dir, partial, f"{sha}-{ts}")
        partial.rename(final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise

    # Relative target: the web container mounts public/ at another path.
    tmp_link = public / ".current.tmp"
    if tmp_link.is_symlink() or tmp_link.exists():
        tmp_link.unlink()
    os.symlink(f"releases/{ts}", tmp_link)
    os.replace(tmp_link, public / "current")

    for old in sorted(p for p in releases.iterdir()
                      if not p.name.startswith("."))[:-KEEP_RELEASES]:
        shutil.rmtree(old)
    return final


def purge_urls(base_url: str, site_dir: Path) -> list:
    """The fixed-name URLs a new release changes: / plus every entry page."""
    base = base_url.rstrip("/") + "/"
    return [base] + [base + p.name for p in sorted(site_dir.glob("*.html"))]


def purge(zone_id: str, token: str, urls: list) -> None:
    """Purge urls from the Cloudflare cache (purge-by-URL works on every plan)."""
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
        data=json.dumps({"files": urls}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise PublishError(f"purge HTTP {e.code}: {e.read()[:500]!r}") from e
    if not body.get("success"):
        raise PublishError(f"purge failed: {body.get('errors')}")


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--version")
    r = sub.add_parser("release")
    r.add_argument("--public", type=Path, required=True)
    p = sub.add_parser("purge")
    p.add_argument("--base-url", required=True)
    p.add_argument("--zone-id", required=True)
    p.add_argument("--token-file", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("dir", type=Path)
    args = ap.parse_args(argv)

    try:
        if args.cmd == "build":
            build_site(SITE, args.out, args.version or f"{_git_sha()}-{_now_ts()}")
            print(f"site -> {args.out}")
        elif args.cmd == "release":
            final = release(SITE, args.public, _git_sha(), _now_ts())
            print(f"release {final} is current")
        elif args.cmd == "purge":
            urls = purge_urls(args.base_url, SITE)
            purge(args.zone_id, args.token_file.read_text().strip(), urls)
            print(f"purged {len(urls)} URLs")
        elif args.cmd == "check":
            leftovers = unversioned_refs(args.dir)
            for f, ref in leftovers:
                print(f"unversioned: {f}: {ref}")
            return 1 if leftovers else 0
    except PublishError as e:
        print(f"publish_site: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
