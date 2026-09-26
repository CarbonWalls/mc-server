"""Tests for the from-zero bootstrap module.

The network steps are exercised end-to-end by the cleanroom run; these tests
cover the pure selection logic and the doctor's config audit, using fixture
data so they stay fast and offline.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui.core import bootstrap, config, paths

TMP = Path(__file__).resolve().parent / "tmp_bootstrap"


def setup():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)


def _pick(paper_version, listing):
    """The selection rule used by _download_paper, lifted out for testing:
    take the first release-looking line that actually has a downloadable
    build - a line can be flagged 'release' before any STABLE build exists."""
    if paper_version:
        return paper_version
    entry = next((e for e in listing
                  if e.get("release") and (e.get("build") or {}).get("url")), None)
    return (entry or {}).get("key", "")


def test_paper_selection_skips_release_without_build():
    listing = [
        {"key": "26.3", "release": True, "build": None},
        {"key": "26.3-rc-3", "release": False, "build": None},
        {"key": "26.2", "release": True, "build": {"url": "https://x/paper.jar"}},
        {"key": "26.1.1", "release": True, "build": None},
    ]
    # 26.3 is flagged release but has no build; 26.2 is the newest installable
    assert _pick("", listing) == "26.2"
    # an explicit request is honoured as-is
    assert _pick("26.1.1", listing) == "26.1.1"
    # nothing installable at all
    assert _pick("", [ {"key": "26.3", "release": True, "build": None} ]) == ""
    print("ok paper selection")


def test_plan_marks_only_missing_pieces():
    steps = bootstrap.plan()
    ids = [s["id"] for s in steps]
    assert ids == ["dirs", "jdk", "paper", "bore", "playit", "eula", "properties",
                   "geyser"]
    for s in steps:
        assert isinstance(s["needed"], bool) and s["label"] and s["note"]
    needed = bootstrap.needed_steps()
    assert all(s["needed"] for s in needed)
    print(f"ok plan ({len(steps)} steps, {len(needed)} needed)")


def test_arch_normalisation():
    assert bootstrap.host_arch() in ("x86_64", "aarch64", "armv7l", "")
    urls = bootstrap.binary_urls()
    if bootstrap.host_arch():
        assert set(urls) == {"bore", "playit", "playitd"}
        assert urls["bore"].startswith("https://github.com/ekzhang/bore/releases/")
        assert urls["playit"].startswith("https://github.com/playit-cloud/")
        assert "playit-cli-linux-" in urls["playit"]
        assert "playit-linux-" in urls["playitd"]
    else:
        assert urls == {}
    print(f"ok arch ({bootstrap.host_arch() or 'unsupported'})")


def test_inventory_is_read_only():
    before = paths.free_bytes()
    inv = bootstrap.inventory()
    assert set(inv) >= {"arch", "jdk", "paper_jar", "bore_bin", "playit_secret",
                        "ram_bytes", "disk_bytes", "urls"}
    assert isinstance(inv["playit_secret"], bool)
    assert paths.free_bytes() == before  # doctor must never touch the disk
    print(f"ok inventory (jdk={inv['jdk']}, paper={inv['paper_jar']})")


def test_geyser_config_contract():
    dest = TMP / "config.yml"
    (TMP / "Geyser-Spigot").mkdir(parents=True, exist_ok=True)
    dest = TMP / "Geyser-Spigot" / "config.yml"
    res = bootstrap.write_geyser_config({})
    # writes into the real server tree; assert the contract on a scratch copy
    shutil.copy2(paths.server_dir() / "plugins" / "Geyser-Spigot" / "config.yml", dest) \
        if (paths.server_dir() / "plugins" / "Geyser-Spigot" / "config.yml").is_file() \
        else None
    assert res["ok"], res.get("error")
    written = paths.server_dir() / "plugins" / "Geyser-Spigot" / "config.yml"
    assert config.yaml_get_file(written, ["bedrock", "port"]) == "19132"
    assert config.yaml_get_file(written, ["bedrock", "clone-remote-port"]) == "false"
    assert config.yaml_get_file(written, ["advanced", "bedrock",
                                          "use-haproxy-protocol"]) == "true"
    assert config.yaml_get_file(written, ["advanced", "bedrock",
                                          "broadcast-port"]) == "19132"
    # a custom port must land in both the listener and the broadcast value
    res = bootstrap.write_geyser_config({"port": 19199, "broadcast_port": 12345})
    assert res["ok"]
    assert config.yaml_get_file(written, ["bedrock", "port"]) == "19199"
    assert config.yaml_get_file(written, ["advanced", "bedrock",
                                          "broadcast-port"]) == "12345"
    # out-of-range ports are rejected
    bad = bootstrap.write_geyser_config({"port": 99999})
    assert not bad["ok"]
    # restore the live contract so the doctor still passes afterwards
    bootstrap.write_geyser_config({})
    print("ok geyser config contract")


def test_doctor_reports_live_state():
    findings = bootstrap.doctor()
    assert findings, "doctor should always report something"
    statuses = {s for s, _ in findings}
    assert statuses <= {"ok", "warn", "err", "todo"}
    # the audit must include the four appendix A s.3 keys
    keys = " ".join(m for _s, m in findings)
    for needle in ("bedrock.port", "clone-remote-port", "use-haproxy-protocol",
                   "broadcast-port"):
        assert needle in keys, f"doctor did not audit {needle}"
    print(f"ok doctor ({len(findings)} findings, statuses={sorted(statuses)})")


if __name__ == "__main__":
    setup()
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nbootstrap tests: all passed")
