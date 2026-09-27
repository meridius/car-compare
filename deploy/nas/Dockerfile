# car-compare daily job image — for a small always-on host (e.g. a home NAS)
# whose residential IP mobile.de does not block the way it blocks CI runners.
#
# The image carries only the dependencies: Python + the pinned requirements,
# Chromium for the Playwright sources, git, gh and supercronic. The code is NOT
# baked in — the repo clone is bind-mounted at $CAR_COMPARE_REPO and
# bin/nas-daily.sh resets it to origin/main on every run, so a merge goes live
# on the next firing without a rebuild. Rebuild only when requirements.txt or
# this directory changes.
#
# Build from the repo root (the .dockerignore there allowlists what is copied):
#   docker build -f deploy/nas/Dockerfile -t car-compare .
#
# Pinned tag+digest: docker resolves the digest, so the base is exact, and the
# tag keeps it readable. python:3.12-slim, digest resolved 2026-09-28.
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

# Unbuffered: a scheduled run must show progress in `docker logs` as it
# happens, not in one burst when the process exits. Browsers go to a fixed
# path because they are installed as root at build time but run as the
# unprivileged user, whose $HOME is /tmp.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    CAR_COMPARE_REPO=/repo

# git: the daily fetch of origin/main. tzdata: supercronic reads the schedule
# in $TZ, and a silent fallback to UTC would move the firing by 1-2 hours.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git tzdata \
 && rm -rf /var/lib/apt/lists/*

# The runtime user. compose's `user:` sets the uid, but a uid with no passwd
# entry breaks anything that resolves the current user (git among them).
# Defaults match a Synology user in the `users` group (gid 100, which already
# exists in the Debian base); override with --build-arg for another host.
ARG APP_UID=1026
ARG APP_GID=100
RUN useradd --uid "$APP_UID" --gid "$APP_GID" --home-dir /tmp --shell /bin/sh car-compare

# supercronic (cron inside the container) and gh (release upload + workflow
# dispatch). Both are fetched with the image's own Python and their sha256 is
# asserted before the bytes are written: an unpinned binary from a release page
# would otherwise be the one unverified thing in an image pinned by digest.
# supercronic v0.2.49 linux-amd64; gh 2.101.0 linux_amd64 (sha256 from the
# release's checksums.txt, re-computed from the download 2026-09-28).
ENV SUPERCRONIC_VERSION=v0.2.49 \
    SUPERCRONIC_SHA256=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1 \
    GH_VERSION=2.101.0 \
    GH_SHA256=9bca2d1c16825f109907a23307628a2f0698fbf99662b73a5cf0b020293072b8
# A plain script, not a RUN heredoc: heredocs need a newer Dockerfile frontend
# than an older host docker may ship.
COPY deploy/nas/fetch_pinned.py /tmp/fetch_pinned.py
RUN python /tmp/fetch_pinned.py && rm /tmp/fetch_pinned.py
RUN supercronic -version && gh --version

# Dependencies before the entrypoint, so editing the entrypoint does not
# re-run pip or the Chromium download. --with-deps pulls Chromium's shared
# libraries through apt (hence the second lists cleanup).
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/* /tmp/requirements.txt

COPY deploy/nas/entrypoint.sh /usr/local/bin/car-compare-entrypoint
RUN chmod 0755 /usr/local/bin/car-compare-entrypoint

# Inside the job the clone is disposable: bin/nas-daily.sh resets it to
# origin/main every run (the script defaults to off, so a laptop run never does).
ENV NAS_DAILY_FETCH=1

WORKDIR /repo
ENTRYPOINT ["/usr/local/bin/car-compare-entrypoint"]
CMD ["schedule"]
