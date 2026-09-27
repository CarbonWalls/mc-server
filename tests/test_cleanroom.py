"""Clean-room test: the tool on a machine that has nothing.

Everything here runs against an empty MCTUI_ROOT, so it exercises exactly the
state a first-time user is in: no JDK, no paper.jar, no instance index. The
claims it checks are the definition of done for --check:

  * on a raw tree, --check exits non-zero with a per-component report and an
    actionable message (it must NOT print "ok: all modules import")
  * the dashboard still renders instead of tracing back
  * the live checkout is left byte-identical

The network bootstrap (which would flip --check to exit 0) is gated behind
MCTUI_NET_BOOTSTRAP=1 because it downloads ~300 MB; run it manually:

    MCTUI_NET_BOOTSTRAP=1 python3 tests/test_cleanroom.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

MANIFEST_GLOBS = ("data", "instances", "server", "jdk", "bin", "logs")
# Paths a running server rewrites on its own: the spark profiler appends to a
# .jfr.tmp continuously and its native lib is unpacked fresh each session. A
# live server churning these is not the clean-room run mutating source, and
# hashing them makes this test flap whenever a real server is up.
MANIFEST_IGNORE = (Path("server/plugins/spark/tmp"),)


def manifest(root: Path) -> dict:
    out = {}
    for pattern in MANIFEST_GLOBS:
        base = root / pattern
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(path.is_relative_to(root / skip) for skip in MANIFEST_IGNORE):
                continue
            try:
                out[str(path.relative_to(root))] = hashlib.sha256(
                    path.read_bytes()).hexdigest()
            except OSError:
                pass
    return out


def run_check(root: Path) -> tuple:
    env = dict(os.environ, MCTUI_ROOT=str(root))
    proc = subprocess.run([sys.executable, "mc_tui.py", "--check"],
                          cwd=PROJECT, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout, proc.stderr


def spawn_dashboard(root: Path):
    """Borrow the pty harness from test_tui.py."""
    sys.path.insert(0, str(HERE))
    import test_tui

    proc, master, state = test_tui.spawn("dashboard")
    out = test_tui.pump(master, 2.5)
    errors = []
    for needle in ("mc-tui",):
        if not test_tui.wait_text(out, needle, 8.0, master):
            errors.append(f"dashboard never rendered {needle!r}")
    test_tui.finish(proc, master, out, state, errors, "cleanroom-dashboard")
    return errors


def test_raw_check():
    root = Path(tempfile.mkdtemp(prefix="mctui-clean-"))
    try:
        code, out, err = run_check(root)
        assert code != 0, "--check must not pass on an empty tree"
        assert "ok: all modules import" not in out, out
        assert "NOT READY" in out, out
        # per-component report names the actual missing pieces
        for needle in ("java runtime", "paper.jar"):
            assert needle in out, f"--check did not report {needle}: {out}"
        # and points at the fix
        assert "--bootstrap" in out, out
        assert err.strip() == "", f"--check must not traceback: {err}"
        print(f"ok raw --check exits {code} with a per-component report")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_raw_dashboard():
    root = Path(tempfile.mkdtemp(prefix="mctui-clean-"))
    os.environ["MCTUI_ROOT"] = str(root)
    try:
        errors = spawn_dashboard(root)
        assert not errors, errors
        print("ok dashboard renders on an empty tree (no traceback)")
    finally:
        os.environ.pop("MCTUI_ROOT", None)
        shutil.rmtree(root, ignore_errors=True)


def test_bootstrap_flips_check():
    if not os.environ.get("MCTUI_NET_BOOTSTRAP"):
        print("ok bootstrap->check skipped (set MCTUI_NET_BOOTSTRAP=1 to run)")
        return
    root = Path(tempfile.mkdtemp(prefix="mctui-clean-"))
    try:
        env = dict(os.environ, MCTUI_ROOT=str(root))
        proc = subprocess.run([sys.executable, "mc_tui.py", "--bootstrap"],
                              cwd=PROJECT, env=env, capture_output=True,
                              text=True, timeout=3600)
        assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]
        code, out, err = run_check(root)
        assert code == 0, f"--check should pass after bootstrap:\n{out}\n{err}"
        assert "READY" in out, out
        print("ok bootstrap -> --check exits 0")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_live_tree_untouched():
    before = manifest(PROJECT)
    root = Path(tempfile.mkdtemp(prefix="mctui-clean-"))
    os.environ["MCTUI_ROOT"] = str(root)
    try:
        spawn_dashboard(root)
        run_check(root)
    finally:
        os.environ.pop("MCTUI_ROOT", None)
        shutil.rmtree(root, ignore_errors=True)
    after = manifest(PROJECT)
    assert before == after, "the clean-room run mutated the live checkout"
    print(f"ok live tree byte-identical ({len(before)} files hashed)")


def main():
    test_raw_check()
    test_raw_dashboard()
    test_bootstrap_flips_check()
    test_live_tree_untouched()
    print("PASS cleanroom")


if __name__ == "__main__":
    main()
