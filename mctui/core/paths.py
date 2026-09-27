import json
import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("MCTUI_ROOT") or Path(__file__).resolve().parents[2]).resolve()

SETTINGS_FILE = "tui_settings.json"
MAIN_INSTANCE_ID = "main"
DEFAULT_SETTINGS = {
    "xms": "512M",
    "xmx": "768M",
    "server_port": 25565,
    "tunnel": "bore",
    "active_instance": MAIN_INSTANCE_ID,
    "java": "",
    "bedrock_port": 19132,
}


def root() -> Path:
    return PROJECT_ROOT


def sub(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def server_dir() -> Path:
    return sub("server")


def logs_dir() -> Path:
    return sub("logs")


def data_dir() -> Path:
    return sub("data")


def bin_dir() -> Path:
    return sub("bin")


def jdk_dir() -> Path:
    return sub("jdk")


def java_bin(version: str = "") -> Path:
    if version:
        return jdk_dir() / version / "bin" / "java"
    return jdk_dir() / "current" / "bin" / "java"


def jcmd_bin(version: str = "") -> Path:
    if version:
        return jdk_dir() / version / "bin" / "jcmd"
    return jdk_dir() / "current" / "bin" / "jcmd"


def cache_dir() -> Path:
    return sub("cache")


def backups_dir() -> Path:
    return sub("backups")


def instances_dir() -> Path:
    return sub("instances")


def active_link() -> Path:
    return instances_dir() / "active"


def settings_path() -> Path:
    return data_dir() / SETTINGS_FILE


def playit_socket() -> Path:
    return data_dir() / "playit.sock"


def playit_secret() -> Path:
    return data_dir() / "playit.toml"


def resolve_path(stored) -> Path:
    """The ONE place a stored instance location becomes an absolute path.

    Relative paths resolve against the project root; absolute paths are used
    as given, so a server can live anywhere on disk. ``..`` segments are
    normalised so a relative location cannot escape the root by spelling.
    An empty stored value means "the project root itself".
    """
    if not stored:
        return PROJECT_ROOT
    p = Path(str(stored))
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return Path(os.path.normpath(str(p)))


def instance_path(instance_id: str, index: dict | None = None) -> Path:
    if instance_id == MAIN_INSTANCE_ID:
        return server_dir()
    if index:
        for inst in index.get("instances", []):
            if inst.get("id") == instance_id:
                stored = inst.get("path")
                return resolve_path(stored) if stored else resolve_path(f"instances/{instance_id}")
    # an unknown id falls back to the documented default location
    return resolve_path(f"instances/{instance_id}")


def log_paths(instance_id: str) -> dict:
    if instance_id == MAIN_INSTANCE_ID:
        name = "server"
    else:
        name = instance_id
    d = logs_dir()
    return {
        "server_log": d / f"{name}.log",
        "server_pid": d / f"{name}.pid",
        "paper_log": server_dir() / "logs" / "latest.log"
        if instance_id == MAIN_INSTANCE_ID
        else instance_path(instance_id) / "logs" / "latest.log",
        "playitd_pid": d / "playitd.pid",
        "playitd_log": d / "playitd.log",
        "playitd_verbose_log": d / "playitd-verbose.log",
        "tunnel_pid": d / "tunnel.pid",
        "tunnel_log": d / "tunnel.log",
        "bore_log": d / "bore.log",
        "snapshots": d / "snapshots",
    }


def known_log_files() -> list:
    out = []
    d = logs_dir()
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix in (".log", ".out"):
                out.append(p)
    return out


def ensure_dirs() -> None:
    for p in (logs_dir(), data_dir(), bin_dir(), cache_dir(), backups_dir(), instances_dir()):
        p.mkdir(parents=True, exist_ok=True)
    log_paths(MAIN_INSTANCE_ID)["snapshots"].mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    path = settings_path()
    merged = dict(DEFAULT_SETTINGS)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for k, v in data.items():
                if k in DEFAULT_SETTINGS:
                    merged[k] = v
    except (OSError, ValueError):
        pass
    return merged


def save_settings(settings: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def env_overrides(settings: dict) -> dict:
    env = dict(os.environ)
    env["XMS"] = str(settings.get("xms", "512M"))
    env["XMX"] = str(settings.get("xmx", "768M"))
    env["SERVER_PORT"] = str(settings.get("server_port", 25565))
    env["TUNNEL"] = str(settings.get("tunnel", "bore"))
    return env


def relative(path) -> str:
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def free_bytes(path=None) -> int:
    target = Path(path) if path else PROJECT_ROOT
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        st = os.statvfs(target)
        return st.f_bavail * st.f_frsize
    except OSError:
        return 0
