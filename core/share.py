"""Share the runner's data with the team, without git commits.

    python3 -m core.share          # runner: upload a snapshot of the live DB now
    python3 -m core.share --get    # anyone: download the newest snapshot to examples/real/snapshot.db

The snapshot is one SQLite file with the real mails, sessions, events, bids and board verdicts (no API keys,
those live only in .env). It is stored as a file on the GitHub release "runner-data" of our private repo, so
the runner's git state is never touched and the repo does not grow. core/supervise.py uploads one every
SHARE_EVERY_S seconds (default 15 min) when it runs live (DRY_RUN=0).

Use it:  DB_PATH=examples/real/snapshot.db python3 -m core.stats      python3 -m core.replay
"""
import os, shutil, sqlite3, subprocess, sys, tempfile, threading, time
from . import config, db

RELEASE = "runner-data"
SNAPSHOT = os.path.join(os.path.dirname(config.DB_PATH), "snapshot.db")
LOCAL = os.path.join(config.ROOT, "examples", "real", "snapshot.db")


def _gh(*args):
    return subprocess.run(["gh"] + list(args), cwd=config.ROOT, capture_output=True, text=True, timeout=120)


def healthy(path):
    """True when the file is one complete SQLite database (nothing waiting in a -wal next to it)."""
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            return c.execute("PRAGMA quick_check").fetchone()[0] == "ok" and c.execute("SELECT COUNT(*) FROM mails").fetchone() is not None
        finally:
            c.close()
    except sqlite3.Error:
        return False


def snapshot(path=None):
    """A consistent copy of the live DB. Safe while the clerk writes (SQLite backup API).

    Every call writes into its OWN new folder: two uploaders (the supervisor's thread and a manual run) used to share
    data/snapshot.db, and anything that opened that file could keep pages in a -wal that was never uploaded. The copy
    is checked before it is handed out; a copy that does not pass is never uploaded."""
    if path is None:
        path = os.path.join(tempfile.mkdtemp(prefix="share-", dir=os.path.dirname(config.DB_PATH)), "snapshot.db")
    elif os.path.exists(path):
        os.remove(path)
    for leftover in (path + "-wal", path + "-shm", path + "-journal"):
        if os.path.exists(leftover):
            os.remove(leftover)
    src, dst = sqlite3.connect(config.DB_PATH), sqlite3.connect(path)
    try:
        with dst:
            src.backup(dst)
        mode = dst.execute("PRAGMA journal_mode=DELETE").fetchone()[0]   # one self-contained file, no -wal next to it
    finally:
        src.close()
        dst.close()
    if str(mode).lower() != "delete" or os.path.exists(path + "-wal") or not healthy(path):
        raise RuntimeError("snapshot at %s is not a complete database (journal mode %s): not uploaded" % (path, mode))
    return path


def upload():
    if not shutil.which("gh"):
        raise RuntimeError("gh (GitHub CLI) is not installed")
    path = snapshot()
    try:
        if _gh("release", "view", RELEASE).returncode != 0:
            r = _gh("release", "create", RELEASE, "--title", "Runner data", "--prerelease", "--notes",
                    "Snapshot of the live clerk database, replaced every few minutes. Get it: python3 -m core.share --get")
            if r.returncode != 0:
                raise RuntimeError("could not create the release: " + r.stderr.strip()[:300])
        r = _gh("release", "upload", RELEASE, path, "--clobber")
        if r.returncode != 0:
            raise RuntimeError("upload failed: " + r.stderr.strip()[:300])
        return os.path.getsize(path)
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)   # the private folder of this one upload


def get(tries=4, wait_s=6):
    """Download the runner's snapshot. It is checked in a folder of its own BEFORE it replaces the local copy, and it
    replaces it as a new file. 22 Nov 11:15: 'database disk image is malformed' on the other laptops, also after a
    second download, while the file on GitHub was intact (seven downloads in a row passed). A program that still had
    the old examples/real/snapshot.db open (control room, monitor.carriers --watch: core.db puts every DB it opens into
    WAL mode) wrote its old pages into the file that the download had overwritten in place."""
    os.makedirs(os.path.dirname(LOCAL), exist_ok=True)
    last = ""
    for attempt in range(tries):
        tmp = tempfile.mkdtemp(prefix=".snapshot-get-", dir=os.path.dirname(LOCAL))   # same disk: the move is one rename
        try:
            r = _gh("release", "download", RELEASE, "-p", "snapshot.db", "-D", tmp, "--clobber")
            new = os.path.join(tmp, "snapshot.db")
            if r.returncode != 0 or not os.path.exists(new):
                last = "download failed: %s" % (r.stderr.strip()[:200] or "no file")      # the runner replaces it every minute
            elif not healthy(new):
                last = "the downloaded file is not a complete database (the runner was replacing it)"
            else:
                for leftover in (LOCAL + "-wal", LOCAL + "-shm", LOCAL + "-journal"):       # of an older copy: never mix them
                    if os.path.exists(leftover):
                        os.remove(leftover)
                os.replace(new, LOCAL)                                                       # a NEW file, never written in place
                c = sqlite3.connect("file:%s?mode=ro" % LOCAL, uri=True)
                n = c.execute("SELECT COUNT(*), MAX(received_at) FROM mails").fetchone()
                c.close()
                print("Saved %s (%d mails, newest mail %s). Use: DB_PATH=%s python3 -m core.stats" % (
                    os.path.relpath(LOCAL, config.ROOT), n[0],
                    time.strftime("%H:%M:%S", time.localtime(n[1])) if n[1] else "none", os.path.relpath(LOCAL, config.ROOT)))
                print("If a control room or `monitor.carriers --watch` is running on this copy, restart it now: it still shows the old file.")
                return LOCAL
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if attempt + 1 < tries:
            time.sleep(wait_s)
    sys.exit("No usable snapshot after %d tries (%s). Your old copy was not touched. The runner uploads with: python3 -m core.share" % (tries, last))


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
