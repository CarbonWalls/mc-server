"""Isolated MCTUI_ROOT harness for the test suite.

Import this module BEFORE ``mctui.core`` so ``paths.PROJECT_ROOT`` resolves to
a throwaway tree instead of the live checkout. Usage, at the top of a test
file::

    import mctui_test_env
    ROOT = mctui_test_env.activate()
    from mctui.core import paths

Nothing downstream can then read or write the real project tree: every path in
mctui derives from ``paths.PROJECT_ROOT``, which honours MCTUI_ROOT at import
time, and child processes inherit the same variable.

The live checkout is consulted in exactly one place, and read only: to find a
JVM for the tests that must compile and run Java. That JVM is exposed to the
isolated tree as a ``<root>/jdk/current`` symlink, never copied.

``seed()`` writes a plausible "already set up" tree (the state
``--bootstrap`` leaves behind) so the suite is independent of the machine it
runs on.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

SETTINGS = {
    "active_instance": "main",
    "bedrock_port": 19132,
    "java": "",
    "server_port": 25565,
    "tunnel": "bore",
    "xms": "512M",
    "xmx": "768M",
}

# Fixture only: a synthetic placeholder, never a real claim secret. A genuine
# playit secret must never live in the repository.
PLAYIT_SECRET = "0" * 64

# The 75 keys Paper 26.2 writes, snapshotted once as fixture data. Asserting
# against the live server.properties would couple the suite to this machine.
PROPERTIES = {
    "accepts-transfers": "false",
    "allow-flight": "false",
    "allow-nether": "true",
    "broadcast-console-to-ops": "true",
    "broadcast-rcon-to-ops": "true",
    "bug-report-link": "",
    "chat-spam-threshold-seconds": "10",
    "command-spam-threshold-seconds": "10",
    "debug": "false",
    "difficulty": "normal",
    "enable-code-of-conduct": "false",
    "enable-jmx-monitoring": "false",
    "enable-query": "false",
    "enable-rcon": "false",
    "enable-status": "true",
    "enforce-secure-profile": "false",
    "enforce-whitelist": "false",
    "entity-broadcast-range-percentage": "100",
    "force-gamemode": "false",
    "function-permission-level": "2",
    "gamemode": "survival",
    "generate-structures": "true",
    "generator-settings": "{}",
    "hardcore": "false",
    "hide-online-players": "false",
    "initial-disabled-packs": "",
    "initial-enabled-packs": "vanilla",
    "level-name": "world",
    "level-seed": "",
    "level-type": "minecraft:normal",
    "log-ips": "true",
    "management-server-allowed-origins": "",
    "management-server-enabled": "false",
    "management-server-host": "localhost",
    "management-server-port": "0",
    "management-server-secret": "test-fixture-not-a-real-secret",
    "management-server-tls-enabled": "true",
    "management-server-tls-keystore": "",
    "management-server-tls-keystore-password": "",
    "max-chained-neighbor-updates": "1000000",
    "max-players": "12",
    "max-tick-time": "60000",
    "max-world-size": "100000",
    "motd": "§a§lCross-Platform Server §7- Java + Bedrock",
    "network-compression-threshold": "256",
    "online-mode": "false",
    "op-permission-level": "4",
    "pause-when-empty-seconds": "-1",
    "player-idle-timeout": "15",
    "prevent-proxy-connections": "false",
    "pvp": "true",
    "query.port": "25565",
    "rate-limit": "0",
    "rcon.password": "",
    "rcon.port": "25575",
    "region-file-compression": "deflate",
    "require-resource-pack": "false",
    "resource-pack": "",
    "resource-pack-id": "",
    "resource-pack-prompt": "",
    "resource-pack-sha1": "",
    "server-ip": "",
    "server-port": "25565",
    "simulation-distance": "6",
    "spawn-animals": "true",
    "spawn-monsters": "true",
    "spawn-npcs": "true",
    "spawn-protection": "16",
    "status-heartbeat-interval": "0",
    "sync-chunk-writes": "false",
    "text-filtering-config": "",
    "text-filtering-version": "0",
    "use-native-transport": "true",
    "view-distance": "7",
    "white-list": "false",
}

GEYSER_CONFIG = """# Geyser configuration - test fixture
bedrock:
  address: 0.0.0.0
  port: 19132
  transport: raknet
  clone-remote-port: false
java:
  address: 127.0.0.1
  port: 25565
  auth-type: offline
advanced:
  java:
    use-haproxy-protocol: false
  bedrock:
    broadcast-port: 19132
    use-haproxy-protocol: true
config-version: 8
"""

SERVER_LOG = (
    "[12:00:00 INFO]: Starting minecraft server version 26.2\n"
    "[12:00:01 INFO]: Loading properties\n"
    "[12:00:02 INFO]: This server is running Paper version git-Paper-129\n"
    "[12:00:30 INFO]: Done (8.432s)! For help, type \"help\"\n"
)


def _usable_jdk_home() -> Path | None:
    """A real JDK home (containing bin/java) for tests that must run java."""
    bundled = PROJECT / "jdk" / "current"
    try:
        if (bundled / "bin" / "java").is_file():
            return bundled.resolve()
    except OSError:
        pass
    exe = shutil.which("java")
    if exe:
        home = Path(exe).resolve().parent.parent
        if (home / "bin" / "java").is_file():
            return home
    return None


def java_available() -> bool:
    return _usable_jdk_home() is not None


def activate(root=None) -> Path:
    """Create a fresh isolated root (or select an explicit one) as MCTUI_ROOT
    for this process and every child it spawns."""
    if root is None:
        root = os.environ.get("MCTUI_ROOT") or tempfile.mkdtemp(prefix="mctui-test-")
    root = Path(root)
    os.environ["MCTUI_ROOT"] = str(root)
    for path in (str(HERE), str(PROJECT)):
        if path not in sys.path:
            sys.path.insert(0, path)
    return root


def seed(root=None, jdk: bool = True) -> Path:
    """Populate the isolated root with the state a finished bootstrap leaves
    behind. Idempotent; returns the root."""
    root = Path(root or os.environ["MCTUI_ROOT"])
    os.environ["MCTUI_ROOT"] = str(root)
    from mctui.core import bootstrap, config, paths

    paths.ensure_dirs()
    settings = dict(SETTINGS)
    settings["active_instance"] = "main"
    paths.save_settings(settings)
    (paths.data_dir() / "playit.toml").write_text(PLAYIT_SECRET, encoding="utf-8")

    server = paths.server_dir()
    server.mkdir(parents=True, exist_ok=True)
    (server / "server.properties").write_text(
        config.properties_text(PROPERTIES), encoding="utf-8")
    (server / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (server / ".paper").mkdir(exist_ok=True)
    (server / ".paper" / "version_history.json").write_text(
        '{"currentVersion":"26.2-129-9240f58 (MC: 26.2)"}', encoding="utf-8")
    geyser_dir = server / "plugins" / "Geyser-Spigot"
    geyser_dir.mkdir(parents=True, exist_ok=True)
    (geyser_dir / "config.yml").write_text(GEYSER_CONFIG, encoding="utf-8")

    logs = paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "server.log").write_text(SERVER_LOG, encoding="utf-8")

    # tunnel binaries: executable stubs so the start_playitd "already running"
    # guard is reachable without downloading 15 MB of real agents
    for name in ("playitd", "playit", "bore-bin"):
        exe = paths.bin_dir() / name
        if not exe.exists():
            try:
                exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                exe.chmod(0o755)
            except OSError:
                pass

    index = {
        "version": 1,
        "instances": [
            {
                "id": "main",
                "name": "Main Server",
                "path": "server",
                "created": "2026-09-25 10:52:24",
                "paper_version": "26.2",
                "note": "original instance (this folder's server/ directory)",
                "builtin": True,
            }
        ],
    }
    config.write_json(paths.instances_dir() / "index.json", index, with_backup=False)

    if jdk:
        link_jdk(root)
    return root


def link_jdk(root=None) -> bool:
    """Expose a real JVM to the isolated tree as jdk/current. Returns False
    when no JVM is obtainable (tests that need one then skip)."""
    root = Path(root or os.environ["MCTUI_ROOT"])
    home = _usable_jdk_home()
    link = root / "jdk" / "current"
    if home is None:
        return False
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(home)
    except OSError:
        return False
    return (link / "bin" / "java").is_file()


def discard(root=None) -> None:
    """Remove the isolated tree."""
    root = Path(root or os.environ.get("MCTUI_ROOT") or "")
    if str(root) and root.is_dir() and "mctui-test" in root.name:
        shutil.rmtree(root, ignore_errors=True)
