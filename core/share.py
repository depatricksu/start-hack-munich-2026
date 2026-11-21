"""Share the runner's data with the team, without git commits.

    python3 -m core.share          # runner: upload a snapshot of the live DB now
    python3 -m core.share --get    # anyone: download the newest snapshot to examples/real/snapshot.db

The snapshot is one SQLite file with the real mails, sessions, events, bids and board verdicts (no API keys,
those live only in .env). It is stored as a file on the GitHub release "runner-data" of our private repo, so
the runner's git state is never touched and the repo does not grow. core/supervise.py uploads one every
SHARE_EVERY_S seconds (default 15 min) when it runs live (DRY_RUN=0).

Use it:  DB_PATH=examples/real/snapshot.db python3 -m core.stats      python3 -m core.replay
"""
import os, shutil, sqlite3, subprocess, sys, threading, time
from . import config, db

RELEASE = "runner-data"
SNAPSHOT = os.path.join(os.path.dirname(config.DB_PATH), "snapshot.db")
LOCAL = os.path.join(config.ROOT, "examples", "real", "snapshot.db")


def _gh(*args):
    return subprocess.run(["gh"] + list(args), cwd=config.ROOT, capture_output=True, text=True, timeout=120)


def snapshot(path=SNAPSHOT):
    """A consistent copy of the live DB. Safe while the clerk writes (SQLite backup API)."""
    if os.path.exists(path):
        os.remove(path)
    src, dst = sqlite3.connect(config.DB_PATH), sqlite3.connect(path)
    with dst:
        src.backup(dst)
    dst.execute("PRAGMA journal_mode=DELETE")                # one self-contained file, no -wal next to it
    src.close()
    dst.close()
    return path


def upload():
    if not shutil.which("gh"):
        raise RuntimeError("gh (GitHub CLI) is not installed")
    path = snapshot()
    if _gh("release", "view", RELEASE).returncode != 0:
        r = _gh("release", "create", RELEASE, "--title", "Runner data", "--prerelease", "--notes",
                "Snapshot of the live clerk database, replaced every few minutes. Get it: python3 -m core.share --get")
        if r.returncode != 0:
            raise RuntimeError("could not create the release: " + r.stderr.strip()[:300])
    r = _gh("release", "upload", RELEASE, path, "--clobber")
    if r.returncode != 0:
        raise RuntimeError("upload failed: " + r.stderr.strip()[:300])
    return os.path.getsize(path)


def get():
    os.makedirs(os.path.dirname(LOCAL), exist_ok=True)
    r = _gh("release", "download", RELEASE, "-p", "snapshot.db", "-D", os.path.dirname(LOCAL), "--clobber")
    if r.returncode != 0:
        sys.exit("No snapshot yet (%s). The runner uploads one with: python3 -m core.share" % r.stderr.strip()[:200])
    age = time.time() - os.path.getmtime(LOCAL)
    c = sqlite3.connect(LOCAL)
    n = c.execute("SELECT COUNT(*), MAX(received_at) FROM mails").fetchone()
    print("Saved %s (%d mails, newest mail %s). Use: DB_PATH=%s python3 -m core.stats" % (
        os.path.relpath(LOCAL, config.ROOT), n[0],
        time.strftime("%H:%M:%S", time.localtime(n[1])) if n[1] else "none", os.path.relpath(LOCAL, config.ROOT)))


def start_background():
    """Called by the supervisor. Never raises: sharing must not disturb the clerk."""
    if config.DRY_RUN or config.SHARE_EVERY_S <= 0:
        return

    def _log(kind, **kw):                                    # a logging failure must never kill the uploader
        try:
            db.event(kind, **kw)
        except Exception:
            pass

    def loop():
        while True:                                          # nothing in here may raise out of the loop, or uploads stop for good
            try:
                size = upload()
                _log("snapshot_shared", size_kb=round(size / 1024))
            except Exception as e:
                _log("snapshot_share_failed", error=str(e)[:300])
            time.sleep(config.SHARE_EVERY_S)

    def guard():                                             # if the loop ever dies anyway, respawn it instead of going silent
        while True:
            t = threading.Thread(target=loop, daemon=True)
            t.start()
            t.join()
            _log("snapshot_share_thread_restarted")
            time.sleep(5)
    threading.Thread(target=guard, daemon=True).start()


if __name__ == "__main__":
    if "--get" in sys.argv:
        get()
    elif config.DRY_RUN and "--force" not in sys.argv:
        sys.exit("This machine runs in DRY_RUN, its DB is not the live one. Only the runner uploads. "
                 "To download the snapshot: python3 -m core.share --get")
    else:
        print("Uploaded snapshot, %d KB. Team gets it with: python3 -m core.share --get" % (upload() / 1024))
