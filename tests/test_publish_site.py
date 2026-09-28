"""Tests for build/publish_site.py — the versioned, atomically swapped site copy.

The public site sits behind a CDN that caches every file for weeks, so every
local asset an HTML page loads (scripts, stylesheet, data fetches) must carry
the build id in its URL; a new build then means new URLs, and only the fixed
HTML entry pages need a purge. These tests pin that no local reference escapes
the versioning, and the release/swap/prune/purge mechanics.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from build import publish_site as P  # noqa: E402

SITE = Path(ROOT) / "site"
V = "abc1234-20260928T070000Z"


class VersionTextTest(unittest.TestCase):
    def test_html_script_and_stylesheet_get_versioned(self):
        html = ('<link rel="stylesheet" href="style.css">\n'
                '<script src="url-state.js"></script>\n'
                '<script type="module" src="app.js"></script>')
        out = P.version_html(html, V)
        self.assertIn(f'href="style.css?v={V}"', out)
        self.assertIn(f'src="url-state.js?v={V}"', out)
        self.assertIn(f'src="app.js?v={V}"', out)

    def test_html_page_links_and_external_urls_stay_untouched(self):
        # Entry pages keep fixed names (they are purged instead), and CDN
        # assets are already versioned by their own URL.
        html = ('<a href="index.html">x</a><a href="reference.html#f=a">y</a>'
                '<script src="https://cdn.jsdelivr.net/npm/ag-grid@33/x.js"></script>'
                '<a href="#top">z</a>')
        self.assertEqual(P.version_html(html, V), html)

    def test_js_data_fetches_get_versioned(self):
        js = ('fetch("data/cars.parquet").then(f);\n'
              "fetch('data/reference.json');\n"
              '// the same cars.parquet payload\n')
        out = P.version_js(js, V)
        self.assertIn(f'fetch("data/cars.parquet?v={V}")', out)
        self.assertIn(f"fetch('data/reference.json?v={V}')", out)
        self.assertIn("// the same cars.parquet payload", out)  # prose untouched

    def test_versioning_is_idempotent(self):
        html = '<script src="app.js"></script>'
        once = P.version_html(html, V)
        self.assertEqual(P.version_html(once, V), once)
        js = 'fetch("data/cars.parquet")'
        self.assertEqual(P.version_js(P.version_js(js, V), V), P.version_js(js, V))


class UnversionedCheckTest(unittest.TestCase):
    def test_check_flags_unversioned_references(self):
        # The check must not be vacuous: a raw site has unversioned refs.
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "index.html").write_text(
                '<script src="app.js"></script><a href="reference.html">r</a>')
            (Path(td) / "app.js").write_text('fetch("data/cars-meta.json")')
            found = P.unversioned_refs(Path(td))
        self.assertEqual(sorted(r for _, r in found), ["app.js", "data/cars-meta.json"])

    def test_real_site_has_unversioned_refs_before_publish(self):
        # Guards the scanner against the real files: if this ever reads 0, the
        # patterns stopped seeing the site and the post-publish test is empty.
        refs = {r for _, r in P.unversioned_refs(SITE)}
        for expected in ("style.css", "app.js", "url-state.js", "hist-track.js",
                         "filter-chips.js", "reference.js", "transmissions.js",
                         "data/cars.parquet", "data/cars-archived.parquet",
                         "data/cars-meta.json", "data/reference.json",
                         "data/scrape_history.json"):
            self.assertIn(expected, refs)

    def test_published_copy_of_real_site_has_no_unversioned_refs(self):
        with tempfile.TemporaryDirectory() as td:
            # The real pages and scripts, without the (large, irrelevant) payload.
            site = Path(td) / "site"
            shutil.copytree(SITE, site, ignore=shutil.ignore_patterns("data"))
            out = Path(td) / "out"
            P.build_site(site, out, V)
            self.assertEqual(P.unversioned_refs(out), [])
            # Entry pages are copied under their fixed names; docs are not shipped.
            for page in ("index.html", "reference.html", "transmissions.html"):
                self.assertTrue((out / page).is_file())
            self.assertFalse((out / "docs").exists())


def _fake_site(root: Path) -> Path:
    site = root / "site"
    (site / "data").mkdir(parents=True)
    (site / "index.html").write_text('<script src="app.js"></script>')
    (site / "app.js").write_text('fetch("data/cars.parquet")')
    (site / "data" / "cars.parquet").write_bytes(b"PAR1")
    (site / "data" / ".gitkeep").write_text("")
    return site


class ReleaseTest(unittest.TestCase):
    def test_release_writes_versioned_copy_and_points_current_at_it(self):
        with tempfile.TemporaryDirectory() as td:
            site, public = _fake_site(Path(td)), Path(td) / "public"
            rel = P.release(site, public, "sha1", "20260928T070000Z")
            self.assertEqual(rel, public / "releases" / "20260928T070000Z")
            current = public / "current"
            self.assertTrue(current.is_symlink())
            # Relative target: the web container mounts public/ elsewhere.
            self.assertEqual(os.readlink(current), "releases/20260928T070000Z")
            self.assertIn("app.js?v=sha1-20260928T070000Z",
                          (current / "index.html").read_text())
            self.assertEqual((current / "data" / "cars.parquet").read_bytes(), b"PAR1")
            self.assertFalse((current / "data" / ".gitkeep").exists())

    def test_release_keeps_the_newest_three(self):
        with tempfile.TemporaryDirectory() as td:
            site, public = _fake_site(Path(td)), Path(td) / "public"
            for ts in ("20260925T070000Z", "20260926T070000Z", "20260927T070000Z",
                       "20260928T070000Z"):
                P.release(site, public, "sha1", ts)
            kept = sorted(p.name for p in (public / "releases").iterdir())
            self.assertEqual(kept, ["20260926T070000Z", "20260927T070000Z",
                                    "20260928T070000Z"])
            self.assertEqual(os.readlink(public / "current"), "releases/20260928T070000Z")

    def test_failed_build_leaves_current_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            site, public = _fake_site(Path(td)), Path(td) / "public"
            P.release(site, public, "sha1", "20260927T070000Z")
            # A fetch outside data/ is not rewritten, so the check fails.
            (site / "app.js").write_text('fetch("data/cars.parquet"); fetch("extra.json")')
            with self.assertRaises(P.PublishError):
                P.release(site, public, "sha2", "20260928T070000Z")
            self.assertEqual(os.readlink(public / "current"), "releases/20260927T070000Z")
            self.assertEqual(sorted(p.name for p in (public / "releases").iterdir()),
                             ["20260927T070000Z"])

    def test_release_refuses_an_existing_release_dir(self):
        with tempfile.TemporaryDirectory() as td:
            site, public = _fake_site(Path(td)), Path(td) / "public"
            P.release(site, public, "sha1", "20260928T070000Z")
            with self.assertRaises(P.PublishError):
                P.release(site, public, "sha1", "20260928T070000Z")


def _cf_response(body):
    """What urlopen returns: a context manager whose read() is the JSON body."""
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return resp


class PurgeTest(unittest.TestCase):
    def test_purge_urls_are_the_entry_pages_plus_root(self):
        urls = P.purge_urls("https://cars.example.org/", SITE)
        self.assertEqual(urls, [
            "https://cars.example.org/",
            "https://cars.example.org/index.html",
            "https://cars.example.org/reference.html",
            "https://cars.example.org/transmissions.html",
        ])

    def test_purge_posts_files_with_bearer_token(self):
        seen = {}

        def fake_urlopen(req, timeout):
            seen["url"] = req.full_url
            seen["auth"] = req.get_header("Authorization")
            seen["body"] = json.loads(req.data)
            return _cf_response({"success": True})

        with mock.patch.object(P.urllib.request, "urlopen", fake_urlopen):
            P.purge("zone123", "tok", ["https://x/", "https://x/index.html"])
        self.assertEqual(seen["url"],
                         "https://api.cloudflare.com/client/v4/zones/zone123/purge_cache")
        self.assertEqual(seen["auth"], "Bearer tok")
        self.assertEqual(seen["body"], {"files": ["https://x/", "https://x/index.html"]})

    def test_purge_raises_when_cloudflare_reports_failure(self):
        failure = _cf_response({"success": False, "errors": [{"code": 10000}]})
        with mock.patch.object(P.urllib.request, "urlopen", lambda req, timeout: failure):
            with self.assertRaises(P.PublishError):
                P.purge("zone123", "tok", ["https://x/"])


if __name__ == "__main__":
    unittest.main()
