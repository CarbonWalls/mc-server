import io
import shutil
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui.core import download, version

TMP = Path(__file__).resolve().parent / "tmp_version"


def test_min_java():
    cases = {
        "26.2": 25,
        "26.1": 25,
        "26.3-rc-3": 25,
        "1.21.11": 21,
        "1.20.6": 21,
        "1.20": 21,
        "1.19.4": 17,
        "1.18.2": 17,
        "1.17.1": 17,
        "1.16.5": 16,
        "1.16.4": 11,
        "1.16.1": 11,
        "1.12.2": 11,
        "1.11.2": 8,
        "1.7.10": 8,
    }
    for key, expected in cases.items():
        got = version.min_java_for(key)
        assert got == expected, (key, got, expected)
    print(f"ok min java table ({len(cases)} cases)")


def test_paper_versions():
    versions = version.paper_versions(limit=15)
    assert versions, versions
    keys = [v["key"] for v in versions]
    assert "26.2" in keys, keys
    latest = next(v for v in versions if v["key"] == "26.2")
    assert latest["build"] and latest["build"]["number"] == 129, latest
    assert latest["build"]["sha256"], latest
    assert latest["build"]["size"] == 64522678, latest["build"]
    assert latest["min_java"] == 25
    assert latest["release"] is True
    rc = next(v for v in versions if "rc" in v["key"])
    assert rc["release"] is False
    print(f"ok paper versions ({len(keys)}: {', '.join(keys[:6])}...)")


def test_paper_builds():
    builds = version.paper_builds("1.21.11", limit=5)
    assert builds, builds
    assert builds[0]["number"] == 132, builds[0]
    assert builds[0]["sha256"] and builds[0]["url"].startswith("https://")
    assert builds[0]["min_java"] == 21
    numbers = [b["number"] for b in builds]
    assert numbers == sorted(numbers, reverse=True), numbers
    print(f"ok paper builds ({len(builds)} builds for 1.21.11, latest {builds[0]['number']})")


def test_adoptium():
    asset = version.temurin_asset(21)
    assert asset and asset["url"].startswith("https://"), asset
    assert len(asset["sha256"]) == 64, asset
    assert asset["size"] > 100_000_000, asset
    assert "aarch64" in asset["name"] or "x64" in asset["name"] or "x86" in asset["name"], asset["name"]
    arch = version.temurin_arch()
    assert arch in ("x64", "aarch64", "arm"), arch
    assert version.installed_jdks()
    print(f"ok adoptium ({asset['version']} {asset['name'][:40]}... {asset['size']} bytes)")


def test_plugins():
    resolved = version.resolve_all_plugins(game_version="26.2")
    by_id = {p["id"]: p for p in resolved}
    assert len(resolved) == len(version.PLUGINS), resolved
    for pid in ("essentialsx", "luckperms", "viaversion", "geyser", "floodgate", "vault"):
        entry = by_id[pid]
        assert "error" not in entry, (pid, entry.get("error"))
        assert entry["url"].startswith("https://"), entry
        assert entry["size"] > 0, entry
        assert entry["filename"].endswith(".jar")
    assert "cdn.modrinth.com" in by_id["luckperms"]["url"]
    assert "download.geysermc.org" in by_id["floodgate"]["url"]
    # exact sizes are not pinned: upstream re-releases these jars, so only
    # assert they resolve to a plausible full-size jar
    assert by_id["floodgate"]["size"] > 5_000_000, by_id["floodgate"]["size"]
    assert by_id["geyser"]["size"] > 40_000_000, by_id["geyser"]["size"]
    assert "github.com" in by_id["vault"]["url"]
    assert by_id["luckperms"]["sha512"]
    print("ok plugin resolution: " + ", ".join(f"{p['id']}={p['version']}" for p in resolved))


def test_detect_version():
    found = version.detect_paper_version(paths_server())
    assert found == "26.2", found
    print(f"ok detect paper version ({found})")


def paths_server():
    from mctui.core import paths

    return paths.server_dir()


def test_install_jdk_extract():
    if TMP.exists():
        shutil.rmtree(TMP)
    (TMP / "jdk").mkdir(parents=True)
    archive = TMP / "jdk99.tar.gz"
    src = TMP / "jdk-99.0.1+9"
    (src / "bin").mkdir(parents=True)
    (src / "bin" / "java").write_text("#!/bin/sh\necho fake\n")
    (src / "bin" / "java").chmod(0o755)
    (src / "release").write_text('JAVA_VERSION="99.0.1"\n')
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src, arcname="jdk-99.0.1+9")

    sha = download.sha256_file(archive)
    size = archive.stat().st_size
    url = archive.as_uri()

    original_asset = version.temurin_asset
    version.temurin_asset = lambda major, timeout=30: {
        "major": major,
        "version": "99.0.1+9",
        "name": archive.name,
        "size": size,
        "sha256": sha,
        "url": url,
        "archive_name": archive.name,
    }

    class FakeJob:
        def __init__(self):
            self.updates = []

        def update(self, progress=None, message=None):
            self.updates.append((progress, message))

    try:
        job = FakeJob()
        result = version.install_jdk(job, 99, cache=TMP)
        assert result["version"] == "99.0.1+9", result
        assert Path(result["java"]).exists(), result
        assert Path(result["path"]).name.startswith("jdk-99"), result
        assert job.updates and job.updates[-1][0] == 1.0
        job2 = FakeJob()
        result2 = version.install_jdk(job2, 99, cache=TMP)
        assert result2["java"] == result["java"]
        assert any("reusing cached" in str(u[1]) for u in job2.updates), job2.updates
    finally:
        version.temurin_asset = original_asset
        shutil.rmtree(TMP, ignore_errors=True)
        for leftover in ("jdk-99.0.1+9", "bin", "release"):
            target = paths_jdk() / leftover
            if target.exists():
                shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink()
    print("ok jdk install/extract (synthetic archive, cache reuse)")


def paths_jdk():
    from mctui.core import paths

    return paths.jdk_dir()


def test_set_active_jdk():
    import os

    from mctui.core import paths

    link = paths.jdk_dir() / "current"
    original = os.readlink(link) if link.is_symlink() else None
    fake = TMP / "jdk-fake"
    (fake / "bin").mkdir(parents=True, exist_ok=True)
    (fake / "bin" / "java").write_text("x")
    try:
        assert version.set_active_jdk(fake) is True
        assert link.is_symlink() and Path(os.readlink(link)) == fake
    finally:
        if original:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(original)
        shutil.rmtree(TMP, ignore_errors=True)
    assert Path(os.readlink(link)) == Path(original)
    print("ok set_active_jdk (restored)")


def main():
    test_min_java()
    test_detect_version()
    test_paper_versions()
    test_paper_builds()
    test_adoptium()
    test_plugins()
    test_install_jdk_extract()
    test_set_active_jdk()
    print("PASS version")


if __name__ == "__main__":
    main()
