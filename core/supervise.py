"""Keeps the clerk alive. Run this INSTEAD of core.main on the runner (Erik's MacBook):

    DRY_RUN=0 python3 -m core.supervise

It starts the clerk (`python3 -m core.main`, kept awake with caffeinate on a Mac) and starts it again when it
ends: after a crash, or after `python3 -m core.restart` asked for a clean restart. It never touches git.
If the clerk dies right after starting 3 times in a row, the new code is broken: it keeps trying, but slower,
and shouts in the terminal and with a Mac notification. Stop everything with Ctrl+C.
"""
import os, shutil, subprocess, sys, time
from . import config, db, safety

QUICK_DEATH_S = 15


def alert(text):
    print("\n" + "!" * 70 + "\n" + text + "\n" + "!" * 70 + "\n", flush=True)
    if shutil.which("osascript"):
        subprocess.run(["osascript", "-e", 'display notification "%s" with title "Forwarder clerk" sound name "Basso"'
                        % text.replace('"', "'")[:200]], capture_output=True)


def main():
    if safety.is_locked():
        sys.exit("A clerk is already running. Stop it first (Ctrl+C in its terminal), then start the supervisor.")
    cmd = [sys.executable, "-m", "core.main"]
    if shutil.which("caffeinate"):
        cmd = ["caffeinate", "-i"] + cmd
    env = dict(os.environ, SUPERVISED="1")
    quick_deaths = 0
    while True:
        started = time.time()
        code = subprocess.call(cmd, cwd=config.ROOT, env=env)
        lived = time.time() - started
        quick_deaths = quick_deaths + 1 if (lived < QUICK_DEATH_S and code != 0) else 0   # a clean restart is no death
        db.event("clerk_exit", code=code, lived_s=round(lived, 1), quick_deaths=quick_deaths)
        if quick_deaths >= 3:
            alert("The clerk died %d times right after starting. The code on this machine is broken. "
                  "Fix it or go back to the last good commit. Trying again every 20 s." % quick_deaths)
        time.sleep(20 if quick_deaths >= 3 else 2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSupervisor stopped. The clerk is stopped too.")
