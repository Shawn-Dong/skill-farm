#!/usr/bin/env python3
"""
SessionEnd hook for the Skill Farm plugin.

Starts build.py in its own detached process and returns at once, so the session
ends without waiting. It skips the build when the page was rebuilt less than
MIN_GAP seconds ago, the build is killed after TIMEOUT seconds, a lock file keeps
two builds from running together, and nothing is printed. Errors go to
<data dir>/last-build.log so a broken build can still be looked at.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 120
STALE = 600
MIN_GAP = 60


def data_home():
    env = os.environ.get("SKILL_FARM_HOME")
    return Path(env).expanduser() if env else Path.home() / ".claude" / "skill-farm"


def child():
    home = data_home()
    home.mkdir(parents=True, exist_ok=True)
    page = home / "skill-board.html"
    if page.exists() and time.time() - page.stat().st_mtime < MIN_GAP:
        return
    lock = home / ".build.lock"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > STALE:
            lock.unlink()
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except OSError:
        return
    try:
        with open(home / "last-build.log", "w", encoding="utf-8") as log:
            subprocess.run([sys.executable, str(ROOT / "build.py"), "--plugin", "--quiet"],
                           stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def main():
    if sys.argv[1:] == ["--child"]:
        return child()
    try:
        sys.stdin.close()
    except OSError:
        pass
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child"], **kw)
    except OSError:
        pass


if __name__ == "__main__":
    main()
