import platform
import re
import tarfile
from pathlib import Path

from . import download, paths

GRAPHQL_URL = "https://fill.papermc.io/graphql"
ADOPTIUM_ASSETS = "https://api.adoptium.net/v3/assets/latest/{major}/hotspot"
ADOPTIUM_BINARY = "https://api.adoptium.net/v3/binary/latest/{major}/ga/{os}/{arch}/jdk/hotspot/normal/eclipse"

JAVA_REQUIREMENTS = [
    ("26.1", 25),
    ("1.20", 21),
    ("1.17", 17),
    ("1.16.5", 16),
    ("1.16", 11),
    ("1.12", 11),
    ("1.7.10", 8),
]

PLUGINS = [
    {
        "id": "essentialsx",
        "name": "EssentialsX",
        "desc": "homes, warps, kits, economy, moderation",
        "source": "modrinth",
        "slug": "essentialsx",
        "filename": "EssentialsX.jar",
    },
    {
        "id": "luckperms",
        "name": "LuckPerms",
        "desc": "permissions and groups",
        "source": "modrinth",
        "slug": "luckperms",
        "filename": "LuckPerms.jar",
    },
    {
        "id": "vault",
        "name": "Vault",
        "desc": "economy/permissions API bridge",
        "source": "github",
        "repo": "MilkBowl/Vault",
        "tag": "1.7.3",
        "asset": "Vault.jar",
        "filename": "Vault.jar",
    },
    {
        "id": "viaversion",
        "name": "ViaVersion",
        "desc": "let older Java clients join newer servers",
        "source": "modrinth",
        "slug": "viaversion",
        "filename": "ViaVersion.jar",
    },
    {
        "id": "geyser",
        "name": "Geyser-Spigot",
        "desc": "Bedrock Edition cross-play (required for phone/console players)",
        "source": "modrinth",
        "slug": "geyser",
        "filename": "Geyser-Spigot.jar",
    },
    {
        "id": "floodgate",
        "name": "Floodgate",
        "desc": "Bedrock players join without a Java account",
        "source": "geysermc",
        "project": "floodgate",
        "filename": "Floodgate-Spigot.jar",
    },
]


def min_java_for(version_key: str) -> int:
    key = str(version_key).strip()
    if key.startswith("26."):
        return 25
    match = re.match(r"^1\.(\d+)(?:\.(\d+))?", key)
    if not match:
        return 25
    minor = int(match.group(1))
    patch = int(match.group(2) or 0)
    if minor >= 20:
        return 21
    if minor >= 17:
        return 17
    if minor == 16:
        return 16 if patch >= 5 else 11
    if minor >= 12:
        return 11
    if minor == 11:
        return 8
    return 8


def _gql(query: str) -> dict:
    import json

    payload = json.dumps({"query": query}).encode()
    data = download.fetch_json(
        GRAPHQL_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        timeout=40,
    )
    if data.get("errors"):
        raise download.DownloadError("; ".join(e.get("message", "error") for e in data["errors"]))
    return data.get("data", {})


VERSIONS_QUERY = (
    '{ project(key: "paper") { versions(first: {limit}, orderBy: {direction: DESC}) { edges { node { key '
    'builds(filterBy: { channels: [STABLE] }, first: 1, orderBy: { direction: DESC }) { edges { node { '
    'number createdAt channel download(key: "server:default") { name url size checksums { sha256 } } } } } '
    '} } } } }'
)

BUILDS_QUERY = (
    '{ project(key: "paper") { version(key: "{key}") { key builds(first: {limit}, '
    'orderBy: {direction: DESC}) { edges { node { number createdAt channel '
    'download(key: "server:default") { name url size checksums { sha256 } } } } } } } }'
)


def _build_node(node: dict) -> dict:
    dl = node.get("download") or {}
    checksums = dl.get("checksums") or {}
    return {
        "number": node.get("number"),
        "channel": node.get("channel"),
        "created_at": node.get("createdAt"),
        "name": dl.get("name", ""),
        "url": dl.get("url", ""),
        "size": dl.get("size") or 0,
        "sha256": checksums.get("sha256", ""),
    }


def paper_versions(limit: int = 20) -> list:
    query = VERSIONS_QUERY.replace("{limit}", str(limit))
    data = _gql(query)
    out = []
    for edge in data["project"]["versions"]["edges"]:
        node = edge["node"]
        builds = ((node.get("builds") or {}).get("edges") or [])
        entry = {
            "key": node.get("key", ""),
            "build": _build_node(builds[0]["node"]) if builds else None,
        }
        entry["min_java"] = min_java_for(entry["key"])
        entry["release"] = _looks_release(entry["key"])
        out.append(entry)
    return out


def paper_builds(version_key: str, limit: int = 15) -> list:
    query = BUILDS_QUERY.replace("{key}", version_key).replace("{limit}", str(limit))
    data = _gql(query)
    version = data.get("project", {}).get("version") or {}
    edges = ((version.get("builds") or {}).get("edges") or [])
    out = []
    for edge in edges:
        entry = _build_node(edge["node"])
        entry["min_java"] = min_java_for(version_key)
        out.append(entry)
    return out


def _looks_release(key: str) -> bool:
    lowered = key.lower()
    return not any(tag in lowered for tag in ("rc", "pre", "snapshot", "exp"))


def bundled_java_major() -> int | None:
    from . import procs

    return procs.java_major()


def temurin_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    if machine.startswith("arm"):
        return "arm"
    return machine


def temurin_asset(major: int, timeout: int = 30) -> dict | None:
    url = ADOPTIUM_ASSETS.format(major=int(major))
    params = f"?architecture={temurin_arch()}&image_type=jdk&os=linux"
    try:
        data = download.fetch_json(url + params, timeout=timeout)
    except download.DownloadError:
        return None
    for item in data if isinstance(data, list) else []:
        binary = item.get("binary") or {}
        package = binary.get("package") or {}
        if not package.get("link"):
            continue
        return {
            "major": int(major),
            "version": (item.get("version") or {}).get("semver", str(major)),
            "name": package.get("name", ""),
            "size": package.get("size", 0),
            "sha256": package.get("checksum", ""),
            "url": package.get("link", ""),
            "archive_name": package.get("name", ""),
        }
    return None


def installed_jdks() -> list:
    out = []
    base = paths.jdk_dir()
    if not base.is_dir():
        return out
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and (entry / "bin" / "java").exists():
            out.append({"name": entry.name, "path": str(entry)})
    link = base / "current"
    if link.is_symlink():
        out.append({"name": "current", "path": str(link.resolve()), "symlink": True})
    return out


def install_jdk(job, major: int, cache: Path | None = None) -> dict:
    asset = temurin_asset(major)
    if not asset or not asset["url"]:
        raise download.DownloadError(f"no Temurin JDK {major} build for {temurin_arch()} on linux")
    cache_dir = cache or paths.cache_dir()
    archive = cache_dir / f"jdk{major}.tar.gz"
    expected = asset["sha256"]
    if archive.exists() and expected:
        actual = download.sha256_file(archive)
        if actual.lower() == expected.lower():
            job.update(0.35, f"reusing cached {archive.name}")
        else:
            archive.unlink()
    if not archive.exists():
        def progress(done, total):
            if total:
                job.update(0.05 + 0.55 * (done / total), f"downloading JDK {major}: {done // 1048576} MB")

        download.download(asset["url"], archive, sha256=expected,
                          expected_size=asset["size"], on_progress=progress, timeout=900)
    job.update(0.65, "extracting JDK")
    dest = paths.jdk_dir()
    dest.mkdir(parents=True, exist_ok=True)
    top = ""
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        if members:
            top = members[0].name.split("/")[0]
        for member in members:
            parts = Path(member.name).parts
            if member.name.startswith("/") or ".." in parts or not parts:
                continue
            tar.extract(member, path=dest, filter="data")
    java = None
    if top:
        candidate = dest / top / "bin" / "java"
        if candidate.exists():
            java = candidate
    if java is None:
        java = _find_java(dest, asset["archive_name"])
    job.update(1.0, f"installed {asset['version']}")
    return {
        "version": asset["version"],
        "major": major,
        "java": str(java) if java else "",
        "archive": str(archive),
        "path": str(java.parent.parent) if java else "",
    }


def _find_java(dest: Path, archive_name: str) -> Path | None:
    stem = archive_name or ""
    for suffix in (".tar.gz", ".tgz", ".zip"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if stem:
        candidate = dest / stem / "bin" / "java"
        if candidate.exists():
            return candidate
    for entry in sorted(dest.iterdir()):
        if entry.name == "current":
            continue
        if entry.is_dir() and (entry / "bin" / "java").exists():
            return entry / "bin" / "java"
    return None


def set_active_jdk(directory) -> bool:
    link = paths.jdk_dir() / "current"
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(Path(directory))
        return True
    except OSError:
        return False


def detect_paper_version(instance_dir) -> str:
    history = Path(instance_dir) / ".paper" / "version_history.json"
    try:
        import json

        data = json.loads(history.read_text())
        current = data.get("currentVersion", "")
        match = re.search(r"MC:\s*([0-9.]+)", current) or re.search(r"(\d+\.\d+(?:\.\d+)?)", current)
        if match:
            return match.group(1)
    except (OSError, ValueError):
        pass
    return ""


def resolve_plugin(plugin: dict, game_version: str = "") -> dict:
    result = dict(plugin)
    if plugin["source"] == "modrinth":
        return _resolve_modrinth(result, plugin["slug"], game_version)
    if plugin["source"] == "github":
        return _resolve_github(result, plugin["repo"], plugin["tag"], plugin["asset"])
    if plugin["source"] == "geysermc":
        return _resolve_geysermc(result, plugin["project"])
    raise download.DownloadError(f"unknown source for {plugin['name']}")


def _resolve_modrinth(out: dict, slug: str, game_version: str = "") -> dict:
    url = f"https://api.modrinth.com/v2/project/{slug}/version?loaders=%5B%22paper%22%5D&limit=10"
    versions = download.fetch_json(url, timeout=30)
    if not isinstance(versions, list) or not versions:
        url = f"https://api.modrinth.com/v2/project/{slug}/version?limit=10"
        versions = download.fetch_json(url, timeout=30)
    if not versions:
        raise download.DownloadError(f"no builds found on Modrinth for {slug}")
    chosen = None
    if game_version:
        for entry in versions:
            if game_version in (entry.get("game_versions") or []):
                chosen = entry
                break
    if chosen is None:
        chosen = versions[0]
    files = chosen.get("files") or []
    if not files:
        raise download.DownloadError(f"no files for {slug}")
    primary = next((f for f in files if f.get("primary")), files[0])
    hashes = primary.get("hashes") or {}
    out.update({
        "url": primary.get("url", ""),
        "size": primary.get("size", 0),
        "sha512": hashes.get("sha512", ""),
        "sha1": hashes.get("sha1", ""),
        "version": chosen.get("version_number", ""),
        "game_versions": chosen.get("game_versions", []),
        "checksum_note": "sha512 (Modrinth)",
    })
    return out


def _resolve_github(out: dict, repo: str, tag: str, asset: str) -> dict:
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    data = download.fetch_json(url, timeout=30)
    for item in data.get("assets", []):
        if item.get("name") == asset:
            out.update({
                "url": item.get("browser_download_url", ""),
                "size": item.get("size", 0),
                "sha512": "",
                "sha1": "",
                "version": tag,
                "checksum_note": "no checksum published (GitHub) - size checked only",
            })
            return out
    raise download.DownloadError(f"asset {asset} not found in {repo} {tag}")


def _resolve_geysermc(out: dict, project: str) -> dict:
    url = f"https://download.geysermc.org/v2/projects/{project}/versions/latest/builds/latest/downloads/spigot"
    head = download.probe_head(url, timeout=30)
    if not head.get("ok"):
        raise download.DownloadError(f"{project} download not reachable (HTTP {head.get('status')})")
    out.update({
        "url": url,
        "size": head.get("size") or 0,
        "sha512": "",
        "sha1": "",
        "version": "latest",
        "checksum_note": "no checksum published (geysermc.org) - size checked only",
    })
    return out


def resolve_all_plugins(game_version: str = "", wanted=None) -> list:
    results = []
    for plugin in PLUGINS:
        if wanted is not None and plugin["id"] not in wanted:
            continue
        try:
            results.append(resolve_plugin(plugin, game_version))
        except download.DownloadError as exc:
            entry = dict(plugin)
            entry["error"] = str(exc)
            results.append(entry)
    return results
