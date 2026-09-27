import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from . import config, console, paths

AIKAR_FLAGS = [
    "-XX:+UseG1GC",
    "-XX:+ParallelRefProcEnabled",
    "-XX:MaxGCPauseMillis=200",
    "-XX:+UnlockExperimentalVMOptions",
    "-XX:+DisableExplicitGC",
    "-XX:G1NewSizePercent=30",
    "-XX:G1MaxNewSizePercent=40",
    "-XX:G1HeapRegionSize=8M",
    "-XX:G1ReservePercent=20",
    "-XX:G1HeapWastePercent=5",
    "-XX:G1MixedGCCountTarget=4",
    "-XX:InitiatingHeapOccupancyPercent=15",
    "-XX:G1RSetUpdatingPauseTimePercent=5",
    "-XX:SurvivorRatio=32",
    "-XX:+PerfDisableSharedMem",
    "-XX:MaxTenuringThreshold=1",
    "-Dusing.aikars.flags=https://mcflags.emc.gs",
    "-Daikars.new.flags=true",
]

PRESETS = {
    "phone": {
        "label": "phone (low RAM)",
        "xms": "256M",
        "xmx": "512M",
        "flags": AIKAR_FLAGS,
        "extra": ["-XX:+UseStringDeduplication", "-XX:MaxGCPauseMillis=150"],
        "view": 6,
        "simulation": 4,
        "max_players": 8,
    },
    "balanced": {
        "label": "balanced",
        "xms": "512M",
        "xmx": "768M",
        "flags": AIKAR_FLAGS,
        "extra": [],
        "view": 7,
        "simulation": 6,
        "max_players": 12,
    },
    "desktop": {
        "label": "desktop",
        "xms": "1G",
        "xmx": "2G",
        "flags": AIKAR_FLAGS,
        "extra": [],
        "view": 10,
        "simulation": 8,
        "max_players": 20,
    },
}


def read_pid(path) -> int | None:
    try:
        raw = Path(path).read_text().strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def pid_state(pid: int) -> str:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
        return fields[2]
    except (OSError, IndexError):
        return ""


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    reap_children()
    state = pid_state(pid)
    if state == "Z":
        return False
    if not state and not _pid_exists(pid):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


_CHILDREN = {}


def reap_children() -> None:
    if not _CHILDREN:
        return
    for pid in list(_CHILDREN):
        proc = _CHILDREN.get(pid)
        if proc is None:
            continue
        try:
            code = proc.poll()
        except Exception:
            code = -1
        if code is not None:
            _CHILDREN.pop(pid, None)


def proc_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def proc_comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def pid_started(pid: int) -> float:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
        ticks = int(fields[21])
        return time.time() - (ticks / os.sysconf("SC_CLK_TCK"))
    except (OSError, IndexError, ValueError, KeyError):
        return 0.0


def pid_uptime(pid: int) -> float:
    started = pid_started(pid)
    return max(0.0, time.time() - started) if started else 0.0


def pid_rss(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        pass
    return 0


def classify(pid: int | None, needle: str) -> str:
    if not pid:
        return "missing"
    if not pid_alive(pid):
        return "stale"
    cmdline = proc_cmdline(pid)
    if needle and needle not in cmdline:
        return "stale"
    return "running"


def process_report(pid: int | None, needle: str = "") -> dict:
    state = classify(pid, needle)
    report = {
        "state": state,
        "pid": pid if state == "running" else (pid if pid else None),
        "alive": bool(pid and pid_alive(pid)),
        "cmdline": proc_cmdline(pid) if pid and pid_alive(pid) else "",
        "uptime": pid_uptime(pid) if state == "running" else 0.0,
        "rss": pid_rss(pid) if state == "running" else 0,
    }
    return report


def server_status(instance_id: str, jar_name: str = "paper.jar") -> dict:
    lp = paths.log_paths(instance_id)
    pid = read_pid(lp["server_pid"])
    report = process_report(pid, jar_name)
    report["pid_file"] = str(lp["server_pid"])
    report["log_file"] = str(lp["server_log"])
    report["log_exists"] = Path(lp["server_log"]).exists()
    report["log_size"] = Path(lp["server_log"]).stat().st_size if Path(lp["server_log"]).exists() else 0
    report["instance"] = instance_id
    return report


def playitd_status() -> dict:
    lp = paths.log_paths("main")
    pid = read_pid(lp["playitd_pid"])
    report = process_report(pid, "playitd")
    report["pid_file"] = str(lp["playitd_pid"])
    report["socket_exists"] = paths.playit_socket().exists()
    return report


def tunnel_status() -> dict:
    lp = paths.log_paths("main")
    pid = read_pid(lp["tunnel_pid"])
    return process_report(pid, "playit")


def _resolve_jdk(java_override: str = "") -> Path:
    if java_override:
        p = Path(java_override)
        if p.is_file():
            return p
    jdk = paths.java_bin()
    if jdk.is_file():
        return jdk
    return Path("java")


def _java_runnable(exe) -> bool:
    """Would this java binary actually launch? An absolute path must be an
    executable file; a bare name must resolve on PATH."""
    try:
        p = Path(exe)
        if p.is_absolute():
            return p.is_file() and os.access(p, os.X_OK)
        return bool(shutil.which(str(p)))
    except (OSError, ValueError):
        return False


def _sync_server_port(instance_dir, env: dict | None) -> None:
    """Keep server.properties and the tunnel talking about the same port.

    Paper reads ``server-port`` from server.properties at startup; the bore /
    playit tunnel reads ``SERVER_PORT`` from the environment (see
    paths.env_overrides). If the setting changed and only the env was updated,
    the tunnel would forward to a port nothing listens on - so the properties
    file is rewritten to match before java is launched.
    """
    port = (env or {}).get("SERVER_PORT")
    if not port:
        return
    props_path = Path(instance_dir) / "server.properties"
    try:
        props = config.read_properties(props_path)
        if str(props.get("server-port", "")) != str(port):
            props["server-port"] = str(port)
            config.write_properties(props_path, props)
    except OSError:
        pass


def java_version(java_override: str = "") -> str:
    exe = _resolve_jdk(java_override)
    try:
        out = subprocess.run(
            [str(exe), "-version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable ({exc})"
    text = (out.stderr or out.stdout or "").strip().splitlines()
    return text[0] if text else "unavailable"


def java_major(java_override: str = "") -> int | None:
    import re

    text = java_version(java_override)
    match = re.search(r'version "(\d+)', text)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d+)\.\d+\.\d+", text)
    if match:
        return int(match.group(1))
    return None


def build_server_command(instance_dir, jar_name: str, xms: str, xmx: str, extra_flags=None) -> list:
    exe = _resolve_jdk()
    jar = Path(instance_dir) / jar_name
    cmd = [str(exe), f"-Xms{xms}", f"-Xmx{xmx}"]
    cmd.extend(AIKAR_FLAGS)
    if extra_flags:
        cmd.extend(extra_flags)
    cmd.extend(["-jar", str(jar), "nogui"])
    return cmd


def ensure_eula(instance_dir) -> bool:
    eula = Path(instance_dir) / "eula.txt"
    if eula.exists():
        return True
    try:
        eula.write_text("eula=true\n")
    except OSError:
        return False
    return True


def start_server(instance_id: str, jar_name: str = "paper.jar", xms: str = "512M",
                 xmx: str = "768M", extra_flags=None, env: dict | None = None) -> dict:
    instance_dir = paths.instance_path(instance_id)
    if not (Path(instance_dir) / jar_name).exists():
        return {"ok": False, "error": f"missing {jar_name} in {instance_dir}"}
    # Defect C: the bundled JDK is preferred but not mandatory - a usable java
    # on PATH is fine. Checking paths.java_bin() here used to reject that
    # fallback before build_server_command() could reach it (dead code path).
    exe = _resolve_jdk()
    if not _java_runnable(exe):
        return {"ok": False,
                "error": f"no usable java: bundled JDK missing at "
                         f"{paths.java_bin()} and no 'java' on PATH - run "
                         f"python3 mc_tui.py --bootstrap (or ./setup.sh)"}
    if not ensure_eula(instance_dir):
        return {"ok": False, "error": "could not write eula.txt"}
    _sync_server_port(instance_dir, env)
    lp = paths.log_paths(instance_id)
    existing = read_pid(lp["server_pid"])
    if classify(existing, jar_name) == "running":
        return {"ok": False, "error": f"already running as PID {existing}"}
    Path(lp["server_log"]).parent.mkdir(parents=True, exist_ok=True)
    cmd = build_server_command(instance_dir, jar_name, xms, xmx, extra_flags)
    try:
        handle = open(lp["server_log"], "wb")
    except OSError as exc:
        return {"ok": False, "error": f"cannot open log {lp['server_log']}: {exc}"}
    try:
        # Phase 6: stdin is a pipe, not DEVNULL, so the console screen can send
        # commands. The write end is moved into a detached relay (see
        # mctui.core.console) so it stays open for the server's whole life even
        # after this TUI process exits - exiting the TUI never stops a running
        # server, and this is what keeps its console alive after we are gone.
        proc = subprocess.Popen(
            cmd,
            cwd=str(instance_dir),
            stdin=subprocess.PIPE,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    except OSError as exc:
        handle.close()
        return {"ok": False, "error": f"failed to launch java: {exc}"}
    finally:
        try:
            handle.close()
        except OSError:
            pass
    relay = console.spawn_relay(proc, instance_id)
    try:
        proc.stdin.close()
    except OSError:
        pass
    _CHILDREN[proc.pid] = proc
    lp["server_pid"].write_text(f"{proc.pid}\n")
    out = {"ok": True, "pid": proc.pid, "log": str(lp["server_log"]), "cmd": cmd}
    if relay.get("ok"):
        out["console"] = relay["socket"]
    else:
        out["console_error"] = relay.get("error", "")
    return out


def stop_server(instance_id: str, timeout: float = 60.0, on_progress=None) -> dict:
    lp = paths.log_paths(instance_id)
    pid = read_pid(lp["server_pid"])
    if not pid:
        return {"ok": True, "message": "no pid file (already stopped)"}
    if not pid_alive(pid):
        _unlink(lp["server_pid"])
        return {"ok": True, "message": f"stale pid {pid} cleared"}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _unlink(lp["server_pid"])
        return {"ok": True, "message": "process already gone"}
    except PermissionError as exc:
        return {"ok": False, "error": f"permission denied signalling {pid}: {exc}"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            _unlink(lp["server_pid"])
            return {"ok": True, "message": f"stopped PID {pid}"}
        if on_progress:
            on_progress(min(1.0, (timeout - (deadline - time.time())) / timeout),
                        f"waiting for PID {pid} to save and exit")
        time.sleep(0.5)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    time.sleep(0.5)
    # reap the child we launched so it does not linger as a zombie (the
    # console relay treats a zombie as gone, but reaping keeps the pid file
    # and the process table honest)
    _reap(pid)
    _unlink(lp["server_pid"])
    return {"ok": True, "message": f"force-killed PID {pid} after {int(timeout)}s"}


def clear_stale(instance_id: str, jar_name: str = "paper.jar") -> str:
    lp = paths.log_paths(instance_id)
    pid = read_pid(lp["server_pid"])
    if pid and classify(pid, jar_name) == "stale":
        _unlink(lp["server_pid"])
        return f"cleared stale pid {pid}"
    return "nothing to clear"


def start_playitd(verbose: bool = True, first_run: bool = False) -> dict:
    exe = paths.bin_dir() / "playitd"
    if not os.access(exe, os.X_OK):
        return {"ok": False, "error": f"playitd binary missing or not executable: {exe}"}
    if not paths.playit_secret().exists():
        if not first_run:
            return {"ok": False, "error": f"playit secret missing at {paths.playit_secret()}"}
        # No secret yet: this is the one-time claim path. The daemon itself
        # does nothing but wait (playitd 1.0.10 logs "Waiting for frontend secret
        # provisioning over IPC" and idles) - the claim URL is minted by the
        # playit CLI, see web._claim_link_from_cli and start.sh's start_playit,
        # both of which mirror each other.
    status = playitd_status()
    if status["state"] == "running":
        return {"ok": False, "error": f"playitd already running as PID {status['pid']}"}
    lp = paths.log_paths("main")
    log = lp["playitd_verbose_log"] if verbose else lp["playitd_log"]
    cmd = [str(exe), "--socket-path", str(paths.playit_socket()),
           "--secret-path", str(paths.playit_secret())]
    if verbose:
        cmd.extend(["-l", str(log)])
    try:
        handle = open(log, "ab")
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        handle.close()
    except OSError as exc:
        return {"ok": False, "error": f"failed to launch playitd: {exc}"}
    _CHILDREN[proc.pid] = proc
    lp["playitd_pid"].write_text(f"{proc.pid}\n")
    return {"ok": True, "pid": proc.pid, "log": str(log)}


def stop_playitd(timeout: float = 15.0, on_progress=None) -> dict:
    lp = paths.log_paths("main")
    pid = read_pid(lp["playitd_pid"])
    if not pid:
        return {"ok": True, "message": "no playitd pid file"}
    if not pid_alive(pid):
        _unlink(lp["playitd_pid"])
        return {"ok": True, "message": f"stale pid {pid} cleared"}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _unlink(lp["playitd_pid"])
        return {"ok": True, "message": "playitd already gone"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid):
            _unlink(lp["playitd_pid"])
            _unlink(lp["tunnel_pid"])
            return {"ok": True, "message": f"playitd stopped (PID {pid})"}
        if on_progress:
            on_progress(0.5, "waiting for playitd to exit")
        time.sleep(0.3)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    _unlink(lp["playitd_pid"])
    return {"ok": True, "message": f"playitd force-killed (PID {pid})"}


def start_tunnel_attach() -> dict:
    exe = paths.bin_dir() / "playit"
    if not os.access(exe, os.X_OK):
        return {"ok": False, "error": f"playit CLI missing: {exe}"}
    if playitd_status()["state"] != "running":
        return {"ok": False, "error": "playitd is not running"}
    lp = paths.log_paths("main")
    cmd = [str(exe), "--socket-path", str(paths.playit_socket()), "--stdout", "attach"]
    try:
        handle = open(lp["tunnel_log"], "wb")
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=handle,
                                stderr=subprocess.STDOUT, start_new_session=True)
        handle.close()
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    _CHILDREN[proc.pid] = proc
    lp["tunnel_pid"].write_text(f"{proc.pid}\n")
    return {"ok": True, "pid": proc.pid}


def stop_tunnel_attach() -> dict:
    lp = paths.log_paths("main")
    pid = read_pid(lp["tunnel_pid"])
    if not pid:
        return {"ok": True, "message": "no attach pid"}
    if not pid_alive(pid):
        _unlink(lp["tunnel_pid"])
        return {"ok": True, "message": f"stale pid {pid} cleared"}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    _unlink(lp["tunnel_pid"])
    return {"ok": True, "message": f"stopped attach PID {pid}"}


def heap_info(pid: int) -> str:
    jcmd = paths.jcmd_bin()
    if not os.access(jcmd, os.X_OK):
        return "jcmd not available"
    try:
        out = subprocess.run([str(jcmd), str(pid), "GC.heap_info", str(pid)],
                             capture_output=True, text=True, timeout=12)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"jcmd failed: {exc}"
    text = (out.stdout or out.stderr or "").strip()
    return text or "no output"


def format_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def format_uptime(seconds) -> str:
    return playit_uptime(seconds)


def playit_uptime(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _unlink(path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def _reap(pid: int) -> None:
    """Reap a child we launched so it exits the process table."""
    proc = _CHILDREN.pop(pid, None)
    if proc is None:
        return
    try:
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass
