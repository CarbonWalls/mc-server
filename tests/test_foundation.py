import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui.core import config, jobs, paths

TMP = Path(__file__).resolve().parent / "tmp_foundation"
GEYSER = paths.server_dir() / "plugins" / "Geyser-Spigot" / "config.yml"


def setup():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)


def test_paths():
    assert paths.root().name == "mc-server"
    assert paths.java_bin().exists()
    assert paths.server_dir().is_dir()
    assert paths.log_paths("main")["server_pid"].name == "server.pid"
    assert paths.log_paths("other")["server_pid"].name == "other.pid"
    assert paths.log_paths("other")["server_log"].name == "other.log"
    s = paths.load_settings()
    assert s["xms"] == "512M" and s["server_port"] == 25565
    s["xmx"] = "1G"
    paths.save_settings(s)
    assert paths.load_settings()["xmx"] == "1G"
    s["xmx"] = "768M"
    paths.save_settings(s)
    assert paths.free_bytes() > 0
    env = paths.env_overrides(paths.load_settings())
    assert env["TUNNEL"] in ("bore", "playit", "none")
    print("ok paths")


def test_properties():
    src = paths.server_dir() / "server.properties"
    dst = TMP / "server.properties"
    shutil.copy2(src, dst)
    props = config.read_properties(dst)
    assert props["server-port"] == "25565"
    assert props["level-type"] == "minecraft:normal", props["level-type"]
    assert props["online-mode"] == "true"
    assert "motd" in props
    assert len(props) > 50, len(props)
    props["motd"] = "Test=with:specials"
    props["max-players"] = "20"
    config.write_properties(dst, props)
    again = config.read_properties(dst)
    assert again["motd"] == "Test=with:specials"
    assert again["max-players"] == "20"
    assert again["level-type"] == "minecraft:normal"
    assert (TMP / "server.properties.bak").exists()
    assert config.read_text(dst).startswith("#Minecraft server properties")
    print(f"ok properties ({len(again)} keys)")


def test_yaml():
    text = config.read_text(GEYSER)
    assert config.yaml_get(text, ["bedrock", "port"]) == "44041"
    assert config.yaml_get(text, ["bedrock", "transport"]) == "raknet"
    assert config.yaml_get(text, ["java", "auth-type"]) == "offline"
    assert config.yaml_get(text, ["advanced", "java", "use-haproxy-protocol"]) == "false"
    assert config.yaml_get(text, ["advanced", "bedrock", "broadcast-port"]) == "44041"
    assert config.yaml_get(text, ["motd", "passthrough-motd"]) == "true"
    assert config.yaml_get(text, ["nope", "nope"]) is None
    new, found = config.yaml_set(text, ["bedrock", "port"], "19132")
    assert found
    assert config.yaml_get(new, ["bedrock", "port"]) == "19132"
    assert config.yaml_get(new, ["bedrock", "transport"]) == "raknet"
    assert "Must match the playit UDP tunnel" in new
    key_lines = [ln for ln in new.splitlines() if ln.strip().startswith("use-haproxy-protocol:")]
    assert len(key_lines) == 2, key_lines
    new2, found2 = config.yaml_set(new, ["advanced", "java", "use-haproxy-protocol"], "true")
    assert found2
    assert config.yaml_get(new2, ["advanced", "java", "use-haproxy-protocol"]) == "true"
    assert config.yaml_get(new2, ["advanced", "bedrock", "use-haproxy-protocol"]) == "false"
    assert config.yaml_get(new2, ["config-version"]) == "8"
    assert "saved-user-logins" in new2

    dst = TMP / "config.yml"
    config.write_text(dst, text, with_backup=False)
    res = config.yaml_set_file(dst, ["bedrock", "port"], "25566")
    assert res["found"] and res["changed"] and res["backup"] is not None
    assert config.yaml_get_file(dst, ["bedrock", "port"]) == "25566"
    res2 = config.yaml_set_file(dst, ["bedrock", "port"], "25566")
    assert res2["changed"] is False
    print("ok yaml")


def test_secret():
    raw = config.redact_secret(paths.playit_secret())
    assert "..." in raw and len(raw) < 60, raw
    assert config.secret_present(paths.playit_secret())
    assert config.redact_secret(TMP / "missing") == "(missing)"
    print(f"ok secret redaction -> {raw}")


def test_json_bak():
    p = TMP / "list.json"
    config.write_json(p, [{"uuid": "x", "name": "Notch"}], with_backup=False)
    data = config.read_json(p)
    assert data[0]["name"] == "Notch"
    config.write_json(p, [{"uuid": "y", "name": "Herobrine"}])
    assert (TMP / "list.json.bak").exists()
    assert config.read_json(TMP / "list.json.bak")[0]["name"] == "Notch"
    assert config.read_json(TMP / "absent.json", []) == []
    print("ok json")


def test_jobs():
    runner = jobs.JobRunner()

    def work(job, delay):
        for i in range(3):
            job.update(progress=(i + 1) / 3.0, message=f"step {i}")
            time.sleep(delay)
        return "done"

    def boom(job):
        raise ValueError("nope")

    j1 = runner.run("work", work, 0.02)
    j2 = runner.run("boom", boom)
    time.sleep(0.01)
    assert runner.active()
    got = []
    deadline = time.time() + 3
    while len(got) < 2 and time.time() < deadline:
        got.extend(runner.poll())
        time.sleep(0.02)
    assert len(got) == 2, got
    by_id = {j.id: j for j in got}
    assert by_id[j1.id].ok and by_id[j1.id].result == "done"
    assert by_id[j1.id].progress == 1.0
    assert not by_id[j2.id].ok and "ValueError" in by_id[j2.id].error
    assert "nope" in by_id[j2.id].error
    assert runner.get(j1.id).snapshot()["name"] == "work"
    assert runner.active() == []
    print("ok jobs")


def main():
    try:
        setup()
        test_paths()
        test_properties()
        test_yaml()
        test_secret()
        test_json_bak()
        test_jobs()
        print("PASS foundation")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
