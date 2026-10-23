import asyncio
import os
import shutil
import sys

from Encoder.config import UPSTREAM_REPO, UPSTREAM_BRANCH


async def _run(*cmd, timeout=300):
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode, out.decode(errors="replace").strip()


async def update_from_upstream():
    if shutil.which("git") is None:
        return "error", "git is not installed on this machine."

    if not os.path.isdir(".git"):
        if not UPSTREAM_REPO:
            return "error", "This folder is not a git repo. Set UPSTREAM_REPO in config.env."
        rc, out = await _run("git", "init", "-q")
        if rc:
            return "error", out

    rc, _ = await _run("git", "remote", "get-url", "origin")
    if rc:  # no origin yet
        if not UPSTREAM_REPO:
            return "error", "No git remote 'origin'. Set UPSTREAM_REPO in config.env."
        rc, out = await _run("git", "remote", "add", "origin", UPSTREAM_REPO)
    elif UPSTREAM_REPO:
        rc, out = await _run("git", "remote", "set-url", "origin", UPSTREAM_REPO)
    if rc:
        return "error", out

    branch = UPSTREAM_BRANCH
    if not branch:
        rc, out = await _run("git", "rev-parse", "--abbrev-ref", "HEAD")
        branch = out if rc == 0 and out != "HEAD" else "main"

    rc, old = await _run("git", "rev-parse", "--short", "HEAD")
    old = old if rc == 0 else None

    rc, out = await _run("git", "fetch", "origin", branch)
    if rc:
        return "error", out[-600:]
    rc, out = await _run("git", "reset", "--hard", "FETCH_HEAD")
    if rc:
        return "error", out[-600:]

    _, new = await _run("git", "rev-parse", "--short", "HEAD")
    if old == new:
        return "uptodate", f"Already up to date ({new})."

    changes = ""
    if old:
        rc, log = await _run("git", "log", "--oneline", "-n", "5", f"{old}..{new}")
        if rc == 0 and log:
            changes = "\n" + log

    # reinstall dependencies only when requirements.txt changed
    pip_note = ""
    req_changed = True
    if old:
        rc, _ = await _run("git", "diff", "--quiet", old, new, "--", "requirements.txt")
        req_changed = rc != 0
    if req_changed and os.path.exists("requirements.txt"):
        rc, out = await _run(sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt")
        pip_note = "\n✅ requirements installed" if rc == 0 else "\n⚠️ pip install failed:\n" + out[-300:]

    return "updated", f"{old or 'none'} → {new}{changes}{pip_note}"
