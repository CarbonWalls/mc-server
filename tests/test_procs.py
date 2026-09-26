import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui.core import paths, procs

TMP = Path(__file__).resolve().parent / "tmp_procs"
INSTANCE = "proctest"
INST_DIR = paths.instances_dir() / INSTANCE
LOGS = paths.logs_dir()


def cleanup():
    for p in (TMP, INST_DIR):
        if p.exists():
            shutil.rmtree(p)
    for name in (f"{INSTANCE}.pid", f"{INSTANCE}.log"):
        f = LOGS / name
        if f.exists():
            f.unlink()


def test_status_helpers():
    assert paths.java_bin().is_file()
    assert procs.read_pid(LOGS / "does-not-exist") is None
    me = os.getpid()
    assert procs.pid_alive(me)
    assert not procs.pid_alive(999999)
    assert procs.classify(me, "python") == "running"
    assert procs.classify(me, "definitely-not-here") == "stale"
    assert procs.classify(None, "x") == "missing"
    assert procs.pid_rss(me) > 0
    assert procs.pid_uptime(me) >= 0
    rep = procs.process_report(me, "python")
    assert rep["state"] == "running" and rep["alive"]
    ver = procs.java_version()
    assert "version" in ver or "unavailable" in ver, ver
    major = procs.java_major()
    assert major is None or major >= 8, major
    print(f"ok helpers (java={ver[:40]}, rss={procs.format_bytes(rep['rss'])})")


def test_command_build():
    cmd = procs.build_server_command(paths.server_dir(), "paper.jar", "512M", "768M")
    assert "-Xms512M" in cmd and "-Xmx768M" in cmd
    assert "-XX:+UseG1GC" in cmd and "-Daikars.new.flags=true" in cmd
    assert cmd[-2:] == ["-jar", str(paths.server_dir() / "paper.jar")] or cmd[-3:-1] == ["-jar", str(paths.server_dir() / "paper.jar")]
    assert cmd[-1] == "nogui"
    assert cmd[0].endswith("/java")
    print(f"ok command build ({len(cmd)} args)")


def test_missing_paths():
    res = procs.start_server("no-such-instance-xyz")
    assert not res["ok"] and "missing paper.jar" in res["error"], res
    res2 = procs.start_playitd()
    if paths.bin_dir().joinpath("playitd").exists() and paths.playit_secret().exists():
        assert not res2["ok"] and "already running" in res2["error"], res2
    print("ok error paths")


def test_start_stop_cycle():
    cleanup()
    TMP.mkdir(parents=True)
    INST_DIR.mkdir(parents=True)
    (INST_DIR / "paper.jar").write_text("not a real jar")
    fake_java = TMP / "fakejava"
    fake_java.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(300)\n")
    fake_java.chmod(0o755)
    original = procs._resolve_jdk
    procs._resolve_jdk = lambda java_override="": fake_java
    try:
        status = procs.server_status(INSTANCE)
        assert status["state"] in ("missing", "stale"), status
        res = procs.start_server(INSTANCE, xms="64M", xmx="128M")
        assert res["ok"], res
        pid = res["pid"]
        time.sleep(0.3)
        assert procs.pid_alive(pid)
        status = procs.server_status(INSTANCE)
        assert status["state"] == "running", status
        assert status["pid"] == pid
        assert status["log_size"] >= 0
        assert procs.pid_rss(pid) >= 0
        dup = procs.start_server(INSTANCE)
        assert not dup["ok"] and "already running" in dup["error"], dup
        assert procs.clear_stale(INSTANCE) == "nothing to clear"
        res2 = procs.stop_server(INSTANCE, timeout=10)
        assert res2["ok"], res2
        time.sleep(0.3)
        assert not procs.pid_alive(pid)
        assert not (LOGS / f"{INSTANCE}.pid").exists()
        res3 = procs.stop_server(INSTANCE)
        assert res3["ok"] and "no pid file" in res3["message"]
    finally:
        procs._resolve_jdk = original
        if procs.pid_alive(read_pid_safe()):
            os.kill(read_pid_safe(), 9)
    print("ok start/stop cycle")


def read_pid_safe():
    return procs.read_pid(LOGS / f"{INSTANCE}.pid")


def test_stale_detection():
    cleanup()
    LOGS.mkdir(parents=True, exist_ok=True)
    proc = os.spawnlp(os.P_NOWAIT, "sleep", "sleep", "300")
    (LOGS / f"{INSTANCE}.pid").write_text(str(proc))
    try:
        status = procs.server_status(INSTANCE)
        assert status["state"] == "stale", status
        assert procs.clear_stale(INSTANCE).startswith("cleared stale")
        assert procs.read_pid(LOGS / f"{INSTANCE}.pid") is None
    finally:
        try:
            os.kill(proc, 9)
        except ProcessLookupError:
            pass
    print("ok stale detection")


def main():
    cleanup()
    test_status_helpers()
    test_command_build()
    test_missing_paths()
    test_start_stop_cycle()
    test_stale_detection()
    cleanup()
    print("PASS procs")


if __name__ == "__main__":
    main()
