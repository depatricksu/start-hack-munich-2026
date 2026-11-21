"""Safe update of the live clerk. Run on the runner AFTER `git pull`:

    python3 -m core.restart          # check the new code, then restart the clerk
    python3 -m core.restart --check  # only check, do not restart

The running clerk keeps the OLD code in memory until it restarts, so pulling alone changes nothing live.
This command checks the new code first: (1) it imports, (2) all tests pass, (3) one fake mail gets a quote.
Only if all three pass does it ask the clerk to restart (between two loop turns, about 2 s, no mail is lost:
the mailbox position and all open sessions are in the database). If a check fails, nothing is restarted and
the old code keeps running.
"""
import os, subprocess, sys, tempfile, time
from . import config, db, safety


def run(label, cmd, env=None):
    print("  %-28s" % label, end="", flush=True)
    p = subprocess.run(cmd, cwd=config.ROOT, env=env, capture_output=True, text=True, timeout=300)
    print("ok" if p.returncode == 0 else "FAILED")
    return p.returncode == 0, (p.stdout + p.stderr)


def checks():
    """Returns (ok, output of the first failing check)."""
    test_env = dict(os.environ, DRY_RUN="1", LLM_FAKE="1", FIVEU_API_KEY="", BID_EXPERIMENT="1",
                    DB_PATH=os.path.join(tempfile.mkdtemp(), "check.db"))
    test_env.pop("SUPERVISED", None)
    ok, out = run("code imports", [sys.executable, "-c", "import core.main"], test_env)
    if not ok:
        return False, out
    ok, out = run("all tests pass", [sys.executable, "-m", "unittest", "discover", "-q"], test_env)
    if not ok:
        return False, out
    ok, out = run("fake mail gets a quote", [sys.executable, "-m", "core.main", "--fake", "examples/rfq.json"], test_env)
    if ok and "quote_sent" not in out:
        ok = False
        print("  (the fake mail ended without a quote)")
    if ok:
        replay_report(test_env)
    return ok, out


def replay_report(env):
    """Report only, never blocks: what would today's code have quoted on the real requests we already got?"""
    snap = os.path.join(config.ROOT, "examples", "real", "snapshot.db")
    live = config.DB_PATH if os.path.exists(config.DB_PATH) and safety.is_locked() else None   # a clerk runs here: the runner
    path = live or (snap if os.path.exists(snap) else None)
    if not path:
        return print("  %-28s%s" % ("replay of real requests", "skipped (no snapshot: python3 -m core.share --get)"))
    p = subprocess.run([sys.executable, "-m", "core.replay", path], cwd=config.ROOT, env=env, capture_output=True,
                       text=True, timeout=300)
    last = (p.stdout.strip().splitlines() or ["no output"])[-1]
    print("  %-28s%s" % ("replay of real requests", "ok" if p.returncode == 0 else "LOOK AT THIS (not blocking)"))
    print("    " + last)
    if p.returncode != 0:
        print("    Details: python3 -m core.replay %s" % path)


def main():
    print("Checking the code at commit %s:" % safety.commit())
    ok, out = checks()
    if not ok:
        print("\n" + out[-3000:])
        sys.exit("\nNOT restarting. The clerk keeps running the old code. Fix the problem, pull, run this again.")
    if "--check" in sys.argv:
        return print("All checks passed. (--check: not restarting)")
    if not safety.is_locked():
        return print("All checks passed, but no clerk is running. Start it: DRY_RUN=0 python3 -m core.supervise")
    if db.get_state("supervised") != "1":
        sys.exit("All checks passed, but the clerk was NOT started with the supervisor, so it cannot restart itself.\n"
                 "Between two requests: stop it (Ctrl+C) and start  DRY_RUN=0 python3 -m core.supervise")
    before = db.get_state("started_at")
    open(safety.RESTART_FLAG, "w").write(str(time.time()))
    print("All checks passed. Asked the clerk to restart...", end="", flush=True)
    for _ in range(30):
        time.sleep(1)
        if db.get_state("started_at") != before:
            return print(" done. Now running commit %s." % db.get_state("commit"))
    print("\nNo restart seen after 30 s. Look at the supervisor terminal.")


if __name__ == "__main__":
    main()
