"""Bootstrap a Minecraft server from zero on a raw machine.

``doctor()`` inspects the host and reports what is already present and what
is still missing, without changing anything. ``bootstrap()`` turns an empty
checkout into a runnable server: folder tree, Temurin JDK, Paper jar, the
bore.pub + playit.gg tunnel clients, the EULA, ``server.properties`` and the
Geyser/Floodgate plugin pair configured for the playit tunnel.

Everything uses the Python standard library only - no pip, no root and no
system-wide installs. Every step is idempotent and guarded: an artifact that
is already on disk is reused, so re-running after a crash picks up where it
left off.

Port layout (appendix A, see docs/PORT_SETUP.md):

    Java Edition    TCP 25565   local server port
    Bedrock/Geyser  UDP 19132   local Geyser port == playit tunnel destination
    broadcast-port  19132       the public port playit assigned, told to clients
"""

import platform
import shutil
import sys
import tarfile
from pathlib import Path

from . import config, download, paths, version

# --- the port contract (appendix A section 3) ------------------------------
JAVA_PORT = 25565
BEDROCK_PORT = 19132          # default Geyser port; do not move it
BEDROCK_TRANSPORT = "raknet"
CLONE_REMOTE_PORT = False     # bedrock port must NOT follow the java port
BEDROCK_HAPROXY = True        # playit speaks proxy-protocol v2
JAVA_HAPROXY = False          # the Paper server itself does not

JDK_MAJOR = 25                # Paper 26.x requires Java 21+; we ship Java 25
BORE_VERSION = "v0.6.0"
PLAYIT_VERSION = "v1.0.11-preview1"

BORE_URL = ("https://github.com/ekzhang/bore/releases/download/"
            f"{BORE_VERSION}/bore-{BORE_VERSION}-{{arch}}.tar.gz")
PLAYIT_CLI_URL = ("https://github.com/playit-cloud/playit-agent/releases/download/"
                  f"{PLAYIT_VERSION}/playit-cli-linux-{{arch}}")
PLAYIT_DAEMON_URL = ("https://github.com/playit-cloud/playit-agent/releases/download/"
                     f"{PLAYIT_VERSION}/playit-linux-{{arch}}")

MIN_DISK_BYTES = 700 * 1024 * 1024    # JDK + paper + plugins + a small world
MIN_RAM_BYTES = 512 * 1024 * 1024     # smallest heap we consider usable

# (id, label, url-template-builder) for the tunnels
TUNNEL_BINARIES = (
    ("bore", "bore.pub tunnel client", BORE_URL),
    ("playit", "playit.gg agent (cli)", PLAYIT_CLI_URL),
    ("playitd", "playit.gg agent (daemon)", PLAYIT_DAEMON_URL),
)


def _machine() -> str:
    return platform.machine().lower()


def host_arch() -> str:
    """Normalised CPU architecture, or "" when unsupported."""
    machine = _machine()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    if machine.startswith("armv7"):
        return "armv7l"
    return ""


def _bore_arch() -> str:
    return {
        "x86_64": "x86_64-unknown-linux-musl",
        "aarch64": "aarch64-unknown-linux-musl",
        "armv7l": "armv7-unknown-linux-musleabi",
    }.get(host_arch(), "")


def _playit_arch() -> str:
    return {"x86_64": "amd64", "aarch64": "aarch64", "armv7l": "armv7"}.get(host_arch(), "")


def binary_urls() -> dict:
    """Release URLs for the tunnel clients on this architecture."""
    arch = host_arch()
    if not arch:
        return {}
    return {
        "bore": BORE_URL.format(arch=_bore_arch()),
        "playit": PLAYIT_CLI_URL.format(arch=_playit_arch()),
        "playitd": PLAYIT_DAEMON_URL.format(arch=_playit_arch()),
    }


# --- what is already on disk -------------------------------------------------
def _memory_bytes() -> int:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def inventory() -> dict:
    """Everything bootstrap cares about, read-only. Never touches the disk."""
    java = paths.java_bin()
    server = paths.server_dir()
    geyser_cfg = server / "plugins" / "Geyser-Spigot" / "config.yml"
    urls = binary_urls()
    return {
        "arch": host_arch(),
        "machine": _machine(),
        "os": f"{platform.system()} {platform.release()}",
        "python": ".".join(map(str, sys.version_info[:3])),
        "jdk": java.is_file() and java.exists(),
        "jdk_path": str(java) if java.exists() else "",
        "jdks": version.installed_jdks(),
        "paper_jar": (server / "paper.jar").is_file(),
        "eula": (server / "eula.txt").is_file(),
        "properties": (server / "server.properties").is_file(),
        "geyser_jar": (server / "plugins" / "Geyser-Spigot.jar").is_file(),
        "floodgate_jar": (server / "plugins" / "Floodgate-Spigot.jar").is_file(),
        "geyser_config": geyser_cfg.is_file(),
        "bore_bin": (paths.bin_dir() / "bore-bin").is_file(),
        "playit_bin": (paths.bin_dir() / "playit").is_file(),
        "playitd_bin": (paths.bin_dir() / "playitd").is_file(),
        "playit_secret": config.secret_present(paths.playit_secret()),
        "ram_bytes": _memory_bytes(),
        "disk_bytes": paths.free_bytes(),
        "urls": urls,
    }


# --- planned steps ------------------------------------------------------------
def plan(spec: dict | None = None) -> list:
    """The ordered bootstrap steps, each flagged ``needed`` when the artifact
    is missing. Pure: no network, no writes - safe to run anywhere."""
    inv = inventory()
    spec = dict(spec or {})
    steps = [
        {"id": "dirs", "label": "folder tree",
         "needed": not (paths.server_dir().is_dir() and paths.logs_dir().is_dir()),
         "note": "server/, logs/, bin/, cache/, data/, instances/, backups/"},
        {"id": "jdk", "label": f"Temurin JDK {JDK_MAJOR}",
         "needed": not inv["jdk"], "note": "Paper 26.x needs Java 21+, we bundle 25"},
        {"id": "paper", "label": "Paper server jar",
         "needed": not inv["paper_jar"], "note": "latest stable build, sha256 verified"},
        {"id": "bore", "label": "bore.pub client",
         "needed": not inv["bore_bin"], "note": "zero-config TCP tunnel"},
        {"id": "playit", "label": "playit.gg agent",
         "needed": not (inv["playit_bin"] and inv["playitd_bin"]),
         "note": "persistent address + UDP for Bedrock"},
        {"id": "eula", "label": "Mojang EULA",
         "needed": not inv["eula"], "note": "required to start the server"},
        {"id": "properties", "label": "server.properties",
         "needed": not inv["properties"], "note": f"java port {JAVA_PORT}"},
        {"id": "geyser", "label": "Geyser + Floodgate",
         "needed": not (inv["geyser_jar"] and inv["floodgate_jar"]
                       and inv["geyser_config"]),
         "note": "Bedrock players join without a Java account"},
    ]
    if spec.get("force"):
        for step in steps:
            step["needed"] = True
    return steps


def needed_steps(spec: dict | None = None) -> list:
    return [s for s in plan(spec) if s["needed"]]


# --- doctor -------------------------------------------------------------------
def geyser_findings(inv: dict) -> list:
    """Audit the Geyser config against the port contract (appendix A s.3).

    Returns (status, message) pairs; status is ok / warn / err.
    """
    cfg = paths.server_dir() / "plugins" / "Geyser-Spigot" / "config.yml"
    if not cfg.is_file():
        return [("warn", "Geyser config not written yet (run the bootstrap)")]
    out = []
    checks = [
        (["bedrock", "port"], str(BEDROCK_PORT),
         f"bedrock port is {BEDROCK_PORT} (the playit tunnel forwards here)"),
        (["bedrock", "clone-remote-port"], "true" if CLONE_REMOTE_PORT else "false",
         "clone-remote-port off: bedrock port must not follow the java port"),
        (["advanced", "bedrock", "use-haproxy-protocol"],
         "true" if BEDROCK_HAPROXY else "false",
         "proxy-protocol v2 on: playit forwards the real player IP"),
        (["advanced", "bedrock", "broadcast-port"], str(BEDROCK_PORT),
         "broadcast-port is the public port playit assigned"),
    ]
    for yaml_path, want, why in checks:
        got = config.yaml_get_file(cfg, yaml_path)
        key = ".".join(yaml_path)
        if got is None:
            out.append(("warn", f"{key}: unset (expected {want}) - {why}"))
        elif got.strip().lower() == want.lower():
            out.append(("ok", f"{key}: {got} - {why}"))
        else:
            out.append(("err", f"{key}: {got}, expected {want} - {why}"))
    if not config.secret_present(paths.playit_secret()):
        out.append(("warn", "playit agent not claimed yet (TUNNEL=playit needs a "
                            "one-time browser claim)"))
    return out


def doctor() -> list:
    """Read-only health report for a raw machine. Returns (status, message)."""
    inv = inventory()
    out = []
    if inv["arch"]:
        out.append(("ok", f"architecture {inv['machine']} -> {inv['arch']} "
                          f"({inv['os']}, python {inv['python']})"))
    else:
        out.append(("err", f"unsupported architecture {inv['machine']!r}; "
                           f"supported: x86_64, aarch64/arm64, armv7l"))
        return out  # nothing else is meaningful without a matching toolchain

    if inv["ram_bytes"]:
        mb = inv["ram_bytes"] // (1024 * 1024)
        if inv["ram_bytes"] >= MIN_RAM_BYTES:
            out.append(("ok", f"memory available: {mb} MB"))
        else:
            out.append(("warn", f"memory available only {mb} MB - expect lag; "
                                f"lower XMX in settings"))
    else:
        out.append(("warn", "could not read memory (non-Linux host?)"))

    gb = inv["disk_bytes"] / (1024 ** 3)
    if inv["disk_bytes"] >= MIN_DISK_BYTES:
        out.append(("ok", f"free space: {gb:.1f} GB"))
    else:
        out.append(("err", f"free space only {gb:.1f} GB; JDK + Paper + a world "
                           f"need ~{MIN_DISK_BYTES / (1024 ** 3):.1f} GB"))

    for step in plan():
        if step["needed"]:
            out.append(("todo", f"missing: {step['label']} - {step['note']}"))
        else:
            out.append(("ok", f"present: {step['label']}"))

    if inv["jdk"] and inv["jdks"]:
        names = ", ".join(j["name"] for j in inv["jdks"] if not j.get("symlink"))
        out.append(("ok", f"jdk: {names or inv['jdk_path']}"))
    out.extend(geyser_findings(inv))
    return out


# --- the build ----------------------------------------------------------------
def _write_default_properties() -> dict:
    props = {
        "server-port": str(JAVA_PORT),
        "motd": "a minecraft server",
        "max-players": "12",
        "view-distance": "7",
        "simulation-distance": "6",
        "white-list": "false",
        "online-mode": "false",
        "enable-query": "false",
        "enable-rcon": "false",
        "level-name": "world",
        "allow-nether": "true",
        "spawn-animals": "true",
        "spawn-monsters": "true",
        "spawn-npcs": "true",
        "generate-structures": "true",
        "difficulty": "normal",
        "gamemode": "survival",
        "pvp": "true",
        "enforce-secure-profile": "false",
    }
    try:
        config.write_properties(paths.server_dir() / "server.properties", props,
                                header="#Minecraft server properties (written by mc_tui bootstrap)")
        return {"ok": True, "port": JAVA_PORT}
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _download_paper(job, paper_version: str = "") -> dict:
    """Resolve the newest stable build of the requested line and fetch it."""
    try:
        if paper_version:
            builds = version.paper_builds(paper_version, limit=5)
            build = next((b for b in builds
                          if version._looks_release(str(b.get("channel", "")))
                          or b.get("sha256")), None) or (builds[0] if builds else None)
        else:
            builds = version.paper_versions(limit=20)
            entry = next((e for e in builds if e.get("release")), None) or \
                (builds[0] if builds else None)
            build = (entry or {}).get("build")
            paper_version = (entry or {}).get("key", "")
        if not build or not build.get("url"):
            return {"ok": False, "error": f"no stable Paper build found for "
                                          f"{paper_version or 'latest'}"}
    except download.DownloadError as exc:
        return {"ok": False, "error": f"paper metadata: {exc}"}

    dest = paths.server_dir() / "paper.jar"

    def progress(done, total):
        job.update(0.20 + 0.45 * (done / max(total, 1)),
                   f"paper {done // 1048576}/{(total or 0) // 1048576} MB")

    try:
        res = download.download(build["url"], dest, sha256=build.get("sha256") or None,
                                expected_size=build.get("size") or None,
                                on_progress=progress, timeout=900)
    except download.DownloadError as exc:
        return {"ok": False, "error": f"paper download: {exc}"}
    return {"ok": True, "version": paper_version, "build": build.get("number"),
            "size": res["size"], "verified": res["verified"]}


def _download_tunnels(job) -> dict:
    urls = binary_urls()
    if not urls:
        return {"ok": False, "error": f"no tunnel release for arch {host_arch()}"}
    got = {}
    for binary_id, label, _tpl in TUNNEL_BINARIES:
        url = urls.get(binary_id)
        if not url:
            continue
        dest = paths.bin_dir() / binary_id
        if binary_id == "bore":
            dest = paths.bin_dir() / "bore-bin"
        if dest.is_file():
            got[binary_id] = {"ok": True, "reused": True}
            continue
        try:
            job.update(0.55, f"downloading {label}")
            if url.endswith(".tar.gz"):
                archive = paths.cache_dir() / "bore.tar.gz"
                download.download(url, archive, timeout=600)
                with tarfile.open(archive, "r:gz") as tar:
                    for member in tar.getmembers():
                        parts = Path(member.name).parts
                        if member.name.startswith("/") or ".." in parts or not parts:
                            continue
                        tar.extract(member, path=paths.bin_dir(), filter="data")
                shipped = paths.bin_dir() / "bore"
                if shipped.is_file():
                    shutil.move(str(shipped), str(dest))
            else:
                download.download(url, dest, timeout=600)
            try:
                dest.chmod(0o755)
            except OSError:
                pass
            got[binary_id] = {"ok": True, "size": dest.stat().st_size}
        except (download.DownloadError, OSError, tarfile.TarError) as exc:
            got[binary_id] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    broken = [k for k, v in got.items() if not v.get("ok")]
    return {"ok": not broken, "binaries": got,
            "error": "; ".join(f"{k}: {got[k]['error']}" for k in broken) if broken else ""}


def _install_plugins(job) -> dict:
    server = paths.server_dir()
    plugins_dir = server / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for plugin_id in ("geyser", "floodgate"):
        plugin = next((p for p in version.PLUGINS if p["id"] == plugin_id), None)
        if not plugin:
            out[plugin_id] = {"ok": False, "error": "unknown plugin"}
            continue
        dest = plugins_dir / plugin["filename"]
        if dest.is_file():
            out[plugin_id] = {"ok": True, "reused": True}
            continue
        try:
            job.update(0.75, f"resolving {plugin['name']}")
            resolved = version.resolve_plugin(plugin, "")
            if not resolved.get("url"):
                out[plugin_id] = {"ok": False, "error": "no download url"}
                continue
            job.update(0.82, f"downloading {plugin['name']}")
            res = download.download(resolved["url"], dest,
                                    expected_size=resolved.get("size") or None,
                                    timeout=900)
            out[plugin_id] = {"ok": True, "size": res["size"]}
        except download.DownloadError as exc:
            out[plugin_id] = {"ok": False, "error": str(exc)}
    broken = [k for k, v in out.items() if not v.get("ok")]
    return {"ok": not broken, "plugins": out,
            "error": "; ".join(f"{k}: {out[k]['error']}" for k in broken) if broken else ""}


def write_geyser_config(geyser: dict | None = None) -> dict:
    """Write the Geyser config so it matches the playit tunnel contract.

    ``bedrock.port`` is the local port the tunnel forwards to,
    ``broadcast-port`` is the public port playit assigned and that we tell
    Bedrock clients to use. With proxy-protocol v2 enabled in the playit
    dashboard, Geyser sees the real player address.
    """
    geyser = dict(geyser or {})
    cfg_dir = paths.server_dir() / "plugins" / "Geyser-Spigot"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    dest = cfg_dir / "config.yml"
    port = int(geyser.get("port", BEDROCK_PORT))
    broadcast = int(geyser.get("broadcast_port", port))
    if not (1 <= port <= 65535) or not (1 <= broadcast <= 65535):
        return {"ok": False, "error": "ports must be 1-65535"}
    text = (
        "# Geyser configuration - written by mc_tui bootstrap.\n"
        "# See docs/PORT_SETUP.md for the playit tunnel settings this expects.\n"
        "bedrock:\n"
        f"  address: 0.0.0.0\n"
        f"  port: {port}\n"
        f"  transport: {BEDROCK_TRANSPORT}\n"
        f"  clone-remote-port: {'true' if CLONE_REMOTE_PORT else 'false'}\n"
        "java:\n"
        "  address: 127.0.0.1\n"
        f"  port: {JAVA_PORT}\n"
        "  auth-type: offline\n"
        "advanced:\n"
        "  java:\n"
        f"    use-haproxy-protocol: {'true' if JAVA_HAPROXY else 'false'}\n"
        "  bedrock:\n"
        f"    broadcast-port: {broadcast}\n"
        f"    use-haproxy-protocol: {'true' if BEDROCK_HAPROXY else 'false'}\n"
        "config-version: 8\n"
    )
    try:
        config.write_text(dest, text, with_backup=False)
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "path": str(dest)}


def _claim_hint() -> str:
    return ("claim the agent once in a browser (TUNNEL=playit ./start.sh prints "
            "the link), then create a Minecraft-Bedrock UDP tunnel in the playit "
            "dashboard pointing at 127.0.0.1:" + str(BEDROCK_PORT))


def bootstrap(job, spec: dict | None = None) -> dict:
    """Turn an empty checkout into a runnable server. Idempotent, stdlib only."""
    spec = dict(spec or {})
    inv = inventory()
    result = {"steps": [], "ok": True, "todo": []}

    def run(frac: float, label: str, fn):
        job.update(frac, label)
        try:
            out = fn()
            out = out if isinstance(out, dict) else {"ok": True}
        except Exception as exc:  # a step failing must not kill the run
            out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        # version.install_jdk() and friends signal success by returning details
        # and failure by raising - a dict with no verdict and no error succeeded.
        if "ok" not in out and not out.get("error"):
            out["ok"] = True
        out["step"] = label
        result["steps"].append(out)
        if not out.get("ok"):
            result["ok"] = False
            result["error"] = f"{label}: {out.get('error')}"
            return False
        return True

    if not inv["arch"]:
        result["ok"] = False
        result["error"] = f"unsupported architecture {inv['machine']!r}"
        return result

    paths.ensure_dirs()
    if not run(0.02, "folder tree", lambda: {"ok": True, "dirs": [
        str(paths.server_dir()), str(paths.bin_dir()), str(paths.cache_dir())]}):
        return result

    if not inv["jdk"] and not run(0.30, f"Temurin JDK {JDK_MAJOR}",
                                  lambda: version.install_jdk(job, JDK_MAJOR)):
        return result
    if not version.set_active_jdk(_newest_jdk()):
        result["todo"].append("could not link jdk/current - point settings.java at it")

    if not inv["paper_jar"] and not run(0.65, "Paper server jar",
                                        lambda: _download_paper(job, spec.get("paper_version", ""))):
        return result

    if not run(0.80, "tunnel clients", lambda: _download_tunnels(job)):
        result["todo"].append("tunnel client download failed - bore/playit optional, "
                              "the server still starts LAN-only")

    if not inv["eula"] and not run(0.84, "Mojang EULA", _accept_eula):
        return result
    if not inv["properties"] and not run(0.88, "server.properties", _write_default_properties):
        return result

    plugins = _install_plugins(job)
    result["steps"].append(dict(plugins, step="Geyser + Floodgate"))
    if plugins.get("ok"):
        geyser = write_geyser_config({"port": BEDROCK_PORT, "broadcast_port": BEDROCK_PORT})
        result["steps"].append(dict(geyser, step="Geyser config"))
        if geyser.get("ok"):
            result["todo"].append(_claim_hint())
    else:
        result["ok"] = False
        result["error"] = f"Geyser + Floodgate: {plugins.get('error')}"

    if result["ok"]:
        job.update(1.0, "bootstrap complete")
        result["todo"].append("start it with ./start.sh (or TUNNEL=playit for Bedrock)")
    return result


def _accept_eula() -> dict:
    try:
        paths.server_dir().mkdir(parents=True, exist_ok=True)
        (paths.server_dir() / "eula.txt").write_text(
            "# accepted by mc_tui bootstrap - https://aka.gg/MinecraftEULA\n"
            "eula=true\n", encoding="utf-8")
        return {"ok": True}
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _newest_jdk() -> str:
    """The newest installed JDK directory name, ignoring the symlink."""
    base = paths.jdk_dir()
    if not base.is_dir():
        return ""
    names = [p.name for p in sorted(base.iterdir())
             if p.is_dir() and (p / "bin" / "java").exists() and p.name != "current"]
    return names[-1] if names else ""
