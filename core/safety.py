"""Small safety helpers for the live clerk: one-clerk lock, heartbeat, restart flag, git commit.

  lock()             only ONE clerk per database. A second one would send every mail twice.
  restart_wanted()   True when `python3 -m core.restart` asked for a restart and we run under the supervisor.
  commit()           short git commit of the code that is loaded, for the log.
"""
import fcntl, os, subprocess, sys
from . import config

DATA_DIR = os.path.dirname(config.DB_PATH)
LOCK_PATH = os.path.join(DATA_DIR, "clerk.lock")
RESTART_FLAG = os.path.join(DATA_DIR, "restart.flag")
SUPERVISED = os.environ.get("SUPERVISED") == "1"          # set by core/supervise.py
_lock_file = None


def lock():
    """Take the one-clerk lock or stop. The OS frees it when the process ends, even after a crash."""
    global _lock_file
    os.makedirs(DATA_DIR, exist_ok=True)
    _lock_file = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("Another clerk is already running on %s. Not starting a second one (it would send mails twice)." % config.DB_PATH)
    _lock_file.seek(0)
    _lock_file.truncate()
    _lock_file.write(str(os.getpid()))
    _lock_file.flush()


def is_locked():
    """True if a clerk holds the lock right now (used by core.restart)."""
    if not os.path.exists(LOCK_PATH):
        return False
    with open(LOCK_PATH, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def restart_wanted():
    """Only honoured under the supervisor: a plain `python -m core.main` would exit and never come back."""
    if not SUPERVISED or not os.path.exists(RESTART_FLAG):
        return False
    os.remove(RESTART_FLAG)
    return True


def commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"
