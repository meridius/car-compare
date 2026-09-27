"""Download supercronic + gh into /usr/local/bin, asserting each sha256 first.

Build-time helper for deploy/nas/Dockerfile; versions and digests come from the
Dockerfile's ENV so there is one place to bump them.
"""
import hashlib
import io
import os
import sys
import tarfile
import urllib.request


def fetch(url, want):
    blob = urllib.request.urlopen(url, timeout=120).read()
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        sys.exit(f"sha256 mismatch for {url}: got {got}, want {want}")
    return blob


def install(path, data):
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o755)


env = os.environ
install("/usr/local/bin/supercronic", fetch(
    "https://github.com/aptible/supercronic/releases/download/"
    f"{env['SUPERCRONIC_VERSION']}/supercronic-linux-amd64",
    env["SUPERCRONIC_SHA256"]))

v = env["GH_VERSION"]
blob = fetch(f"https://github.com/cli/cli/releases/download/v{v}/gh_{v}_linux_amd64.tar.gz",
             env["GH_SHA256"])
with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
    install("/usr/local/bin/gh", tar.extractfile(f"gh_{v}_linux_amd64/bin/gh").read())
