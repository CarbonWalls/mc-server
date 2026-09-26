import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mctui.core import backup, config, instances, logs, paths, players, procs

TMP = Path(__file__).resolve().parent / "tmp_core"
FAKE_INSTANCE = "tuiunit"


def reset():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    for suffix in ("", "-clone", "-renamed"):
        inst = paths.instances_dir() / (FAKE_INSTANCE + suffix)
        if inst.exists():
            shutil.rmtree(inst)
    index = instances.load_index()
    kept = [e for e in index["instances"]
            if not str(e.get("id", "")).startswith(FAKE_INSTANCE)]
    if len(kept) != len(index["instances"]):
        index["instances"] = kept
        instances.save_index(index)


class FakeJob:
    def __init__(self):
        self.updates = []

    def update(self, progress=None, message=None):
        self.updates.append((progress, message))


def test_logs():
    real = paths.logs_dir() / "server.log"
    lines = logs.tail(real, 50)
    assert lines and len(lines) <= 50, len(lines)

    sample = TMP / "sample.log"
    sample.write_text("[12:00:01 INFO]: Steve joined the game\n[12:00:02 INFO]: Alex left the game\n")
    tail = logs.LiveTail(sample, maxlen=50)
    tail.load(keep=10)
    assert len(tail.lines) == 2
    with open(sample, "a") as fh:
        fh.write("[12:00:03 INFO]: Notch joined the game\n")
    added = tail.refresh()
    assert added == 1, added
    assert "Notch" in list(tail.lines)[-1]
    assert tail.refresh() == 0
    with open(sample, "w") as fh:
        fh.write("[13:00:00 INFO]: rebooted\n")
    tail.refresh()
    assert len(tail.lines) == 1 and "rebooted" in tail.lines[0]
    filtered = tail.apply_filter("notch")
    assert filtered == []
    assert tail.apply_filter("rebooted")

    snap = logs.snapshot(sample, TMP / "snaps")
    assert snap["ok"] and Path(snap["path"]).exists()
    assert Path(snap["path"]).read_text().startswith("[13:00:00")
    again = logs.snapshot(sample, TMP / "snaps")
    assert again["ok"] and again["path"] != snap["path"]
    cleared = logs.clear(sample)
    assert cleared["ok"] and sample.read_text() == ""
    assert logs.clear(TMP / "nope.log")["ok"] is False
    assert logs.filter_stream(real, "Paper", limit=5)[:1]

    events_log = TMP / "events.log"
    events_log.write_text(
        "[12:00:01 INFO]: Steve joined the game\n"
        "[12:00:05 INFO]: Steve[/1.2.3.4] logged in with/valid/session\n"
        "[12:01:00 INFO]: Steve lost connection: quit\n"
        "[12:01:01 INFO]: Alex left the game\n"
        "[12:02:00 INFO]: unrelated line\n"
    )
    events = logs.scan_events(events_log)
    kinds = [e["kind"] for e in events]
    assert kinds == ["join", "login", "logout", "leave"], kinds
    assert events[0]["player"] == "Steve" and events[0]["time"] == "12:00:01"
    assert logs.online_set(events) == set()
    partial = [{"kind": "join", "player": "Steve"}, {"kind": "join", "player": "Alex"},
               {"kind": "leave", "player": "Steve"}]
    assert logs.online_set(partial) == {"Alex"}
    assert logs.file_age_line(real) != "missing"
    print(f"ok logs (tail={len(lines)}, events={kinds})")


def test_backup():
    source = TMP / FAKE_INSTANCE
    (source / "world").mkdir(parents=True)
    (source / "paper.jar").write_bytes(b"x" * 50000)
    (source / "world" / "level.dat").write_bytes(b"y" * 10000)
    (source / "server.properties").write_text("motd=hi\n")
    dest = TMP / "backups"
    job = FakeJob()
    made = backup.create(job, FAKE_INSTANCE, source, dest_dir=dest)
    assert made["ok"], made
    assert Path(made["path"]).exists() and made["size"] > 0
    assert any("archiving" in str(u[1]) for u in job.updates)
    assert job.updates[-1][0] == 1.0

    with_backups_dir = paths.backups_dir()
    with_backups_dir.mkdir(exist_ok=True)
    shutil.copy2(made["path"], with_backups_dir / made["name"])
    listing = backup.list_backups()
    assert any(b["name"] == made["name"] for b in listing), listing
    mine = [b for b in backup.list_backups(FAKE_INSTANCE) if b["name"] == made["name"]]
    assert mine and mine[0]["instance"] == FAKE_INSTANCE, mine
    assert mine[0]["stamp"], mine[0]

    target = TMP / "restored"
    job2 = FakeJob()
    restored = backup.restore(job2, made["path"], target)
    assert restored["ok"], restored
    assert (target / "paper.jar").stat().st_size == 50000
    assert (target / "world" / "level.dat").exists()
    assert not (target / "server.properties").read_text().startswith("...")

    (target / "paper.jar").write_bytes(b"changed")
    job3 = FakeJob()
    restored2 = backup.restore(job3, made["path"], target)
    assert restored2["ok"] and restored2["previous"]
    assert (target / "paper.jar").stat().st_size == 50000
    prev = Path(restored2["previous"])
    assert prev.exists() and (prev / "paper.jar").read_bytes() == b"changed"
    removed = backup.purge_previous(target, keep=1)
    assert removed == 0
    assert prev.exists()

    copy_path = with_backups_dir / made["name"]
    assert backup.delete(copy_path)["ok"]
    assert not copy_path.exists()
    outside = TMP / "outside.tar.gz"
    outside.write_bytes(b"x")
    assert not backup.delete(outside)["ok"]
    space = backup.check_space(1024)
    assert "free" in space["message"]
    assert backup.estimate(source) >= 60000
    print(f"ok backup (create/restore/double-restore/delete, size={made['size']})")


def test_instances_index():
    index = instances.load_index()
    assert index["instances"][0]["id"] == "main"
    assert instances.get_instance("main")["path"] == "server"
    assert instances.path_of("main") == paths.server_dir()
    assert instances.validate_name("") != ""
    assert instances.validate_name("bad name") != ""
    assert instances.validate_name("main") != ""
    assert instances.validate_name("9lives") == ""
    assert instances.validate_name(FAKE_INSTANCE) == ""
    inst = {
        "id": FAKE_INSTANCE, "name": "Unit Test", "path": f"instances/{FAKE_INSTANCE}",
        "created": "2026-01-01 00:00:00", "paper_version": "26.2", "note": "test",
    }
    instances.add_instance(inst)
    assert instances.get_instance(FAKE_INSTANCE)["name"] == "Unit Test"
    assert instances.validate_name(FAKE_INSTANCE) != ""
    assert instances.update_instance(FAKE_INSTANCE, note="changed")
    assert instances.get_instance(FAKE_INSTANCE)["note"] == "changed"
    assert not instances.update_instance("nope", note="x")
    summary = dict(instances.summary(instances.get_instance("main")))
    assert summary["exists"] == "yes" and summary["path"] == "server"
    print(f"ok instances index (main + {len(instances.load_index()['instances'])} entries)")


def test_offline_uuid():
    expected = players.offline_uuid("Notch")
    assert len(expected) == 36 and expected.count("-") == 4
    java = paths.java_bin()
    src = TMP / "OfflineUuid.java"
    src.write_text(
        "import java.util.*;\n"
        "public class OfflineUuid {\n"
        "  public static void main(String[] a) {\n"
        "    for (String n : new String[]{\"Notch\", \"Steve\", \"_Test_1\", \"T0\", \"T1\", \"T4\"}) {\n"
        "      byte[] b = (\"OfflinePlayer:\" + n).getBytes(java.nio.charset.StandardCharsets.UTF_8);\n"
        "      UUID u = UUID.nameUUIDFromBytes(b);\n"
        "      System.out.println(n + \"=\" + u);\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    out = subprocess.run([str(java), str(src)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[:500]
    for line in out.stdout.strip().splitlines():
        name, value = line.split("=", 1)
        assert players.offline_uuid(name) == value, (name, value, players.offline_uuid(name))
    src.unlink()
    print(f"ok offline uuid matches java UUID.nameUUIDFromBytes ({len(out.stdout.strip().splitlines())} names)")


def test_player_lists():
    inst = paths.instances_dir() / FAKE_INSTANCE
    inst.mkdir(parents=True, exist_ok=True)
    res = players.add_entry(FAKE_INSTANCE, "whitelist", "Steve")
    assert res["ok"], res
    assert res["backup"] == "", res
    assert players.names(players.read_list(FAKE_INSTANCE, "whitelist")) == ["Steve"]
    assert not players.add_entry(FAKE_INSTANCE, "whitelist", "steve")["ok"]
    assert not players.add_entry(FAKE_INSTANCE, "whitelist", "  ")["ok"]
    second = players.add_entry(FAKE_INSTANCE, "whitelist", "Notch")
    assert second["ok"] and second["backup"] and Path(second["backup"]).exists(), second
    assert sorted(players.names(players.read_list(FAKE_INSTANCE, "whitelist"))) == ["Notch", "Steve"]
    res_ops = players.add_entry(FAKE_INSTANCE, "ops", "Alex", level=4)
    assert res_ops["ok"]
    entries = players.read_list(FAKE_INSTANCE, "ops")
    assert entries[0]["level"] == 4 and entries[0]["bypassesPlayerLimit"] is False
    res_ban = players.add_entry(FAKE_INSTANCE, "bans", "Griefer", reason="no griefing")
    assert res_ban["ok"]
    ban = players.read_list(FAKE_INSTANCE, "bans")[0]
    assert ban["reason"] == "no griefing" and ban["expires"] == "forever"
    assert players.add_entry(FAKE_INSTANCE, "ip_bans", "10.0.0.5")["ok"]
    assert players.read_list(FAKE_INSTANCE, "ip_bans")[0]["ip"] == "10.0.0.5"
    lines = players.entry_lines(players.read_list(FAKE_INSTANCE, "ops"), "ops")
    assert "Alex" in lines[0]
    assert players.remove_entry(FAKE_INSTANCE, "whitelist", "Steve")["ok"]
    assert players.remove_entry(FAKE_INSTANCE, "whitelist", "notch")["ok"]
    assert players.read_list(FAKE_INSTANCE, "whitelist") == []
    assert not players.remove_entry(FAKE_INSTANCE, "whitelist", "Steve")["ok"]
    (inst / "server.properties").write_text("motd=x\nwhite-list=true\nonline-mode=true\nmax-players=12\n")
    log = paths.log_paths(FAKE_INSTANCE)["server_log"]
    log.write_text("[12:00:01 INFO]: Steve joined the game\n")
    status = players.status(FAKE_INSTANCE)
    assert status["online"] == ["Steve"]
    assert status["whitelist_enabled"] and status["online_mode"]
    assert status["max_players"] == "12"
    assert "Steve" in status["recent_players"]
    print(f"ok player lists ({len(players.read_list(FAKE_INSTANCE, 'ops'))} ops, online={status['online']})")


def drop_index_entry(instance_id: str):
    index = instances.load_index()
    index["instances"] = [e for e in index["instances"] if e.get("id") != instance_id]
    instances.save_index(index)


def test_build_instance():
    drop_index_entry(FAKE_INSTANCE)
    inst_dir = paths.instances_dir() / FAKE_INSTANCE
    if inst_dir.exists():
        shutil.rmtree(inst_dir)
    jar = TMP / "fake-paper.jar"
    jar.write_bytes(os.urandom(2048))
    sha = hashlib.sha256(jar.read_bytes()).hexdigest()
    props = {
        "motd": "unit test",
        "server-port": "25577",
        "max-players": "8",
        "level-name": "world",
        "online-mode": "false",
        "difficulty": "easy",
        "gamemode": "survival",
        "view-distance": "6",
        "simulation-distance": "4",
        "white-list": "true",
    }
    spec = {
        "id": FAKE_INSTANCE,
        "name": "Unit Test",
        "motd": "unit test",
        "paper": {"url": jar.as_uri(), "sha256": sha, "size": jar.stat().st_size,
                  "version": "26.2", "number": 129},
        "properties": props,
        "plugins": [],
        "plugin_specs": [],
        "geyser": {"install": False},
        "tunnel": "none",
        "perf": {"preset": "balanced", "xms": "512M", "xmx": "768M"},
        "server_port": 25577,
    }
    job = FakeJob()
    result = instances.build_instance(job, spec)
    assert result["ok"], result
    target = paths.instances_dir() / FAKE_INSTANCE
    assert (target / "paper.jar").exists()
    assert (target / "eula.txt").read_text().strip() == "eula=true"
    written = config.read_properties(target / "server.properties")
    assert written["motd"] == "unit test" and written["server-port"] == "25577"
    assert instances.get_instance(FAKE_INSTANCE)["path"] == f"instances/{FAKE_INSTANCE}"
    assert job.updates[-1][0] == 1.0
    assert result["plugins"] == []
    print(f"ok build_instance ({len(job.updates)} progress steps)")


def test_clone_rename_delete():
    target = paths.instances_dir() / FAKE_INSTANCE
    assert target.exists()
    clone_id = FAKE_INSTANCE + "-clone"
    clone_dir = paths.instances_dir() / clone_id
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    cloned = instances.clone(FAKE_INSTANCE, clone_id)
    assert cloned["ok"], cloned
    assert (clone_dir / "paper.jar").exists()
    assert instances.get_instance(clone_id)["note"].startswith("clone of")
    assert not instances.clone("main", "main")["ok"]

    renamed = instances.rename(clone_id, FAKE_INSTANCE + "-renamed")
    assert renamed["ok"], renamed
    assert not clone_dir.exists()
    assert (paths.instances_dir() / (FAKE_INSTANCE + "-renamed")).exists()
    assert instances.get_instance(FAKE_INSTANCE + "-renamed")
    assert not instances.rename("main", "something")["ok"]

    active_before = instances.active_id()
    activated = instances.set_active(FAKE_INSTANCE)
    assert activated["ok"], activated
    assert instances.active_id() == FAKE_INSTANCE
    assert paths.active_link().is_symlink()
    assert Path(os.readlink(paths.active_link())) == target
    assert instances.set_active("does-not-exist")["ok"] is False

    deleted = instances.delete(FAKE_INSTANCE + "-renamed", make_backup=True)
    assert deleted["ok"], deleted
    assert not (paths.instances_dir() / (FAKE_INSTANCE + "-renamed")).exists()
    assert instances.get_instance(FAKE_INSTANCE + "-renamed") is None
    assert deleted["backup"] and Path(deleted["backup"]).exists()
    Path(deleted["backup"]).unlink()

    deleted2 = instances.delete(FAKE_INSTANCE, make_backup=False)
    assert deleted2["ok"], deleted2
    assert not target.exists()
    assert not instances.delete("main")["ok"]

    instances.set_active(active_before)
    assert instances.active_id() == active_before
    print("ok clone/rename/delete/activate")


def test_paper_version_change_guard():
    target = paths.instances_dir() / FAKE_INSTANCE
    if target.exists():
        shutil.rmtree(target)
    instances.add_instance({
        "id": FAKE_INSTANCE, "name": "Unit Test", "path": f"instances/{FAKE_INSTANCE}",
        "created": "2026-01-01 00:00:00", "paper_version": "26.2", "note": "test",
    })
    job = FakeJob()
    res = instances.change_paper_version(job, FAKE_INSTANCE, {"url": "https://example.invalid/x.jar"})
    assert not res["ok"] and "does not exist" in res["error"], res
    index = instances.load_index()
    index["instances"] = [e for e in index["instances"] if e.get("id") != FAKE_INSTANCE]
    instances.save_index(index)
    print("ok paper change guards")


def cleanup():
    shutil.rmtree(TMP, ignore_errors=True)
    inst = paths.instances_dir() / FAKE_INSTANCE
    if inst.exists():
        shutil.rmtree(inst, ignore_errors=True)
    for suffix in ("-clone", "-renamed"):
        p = paths.instances_dir() / (FAKE_INSTANCE + suffix)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    index = instances.load_index()
    index["instances"] = [e for e in index["instances"] if e.get("id") == "main"]
    instances.save_index(index)
    for name in (f"{FAKE_INSTANCE}.log", f"{FAKE_INSTANCE}.pid"):
        p = paths.logs_dir() / name
        if p.exists():
            p.unlink()
    for stray in paths.backups_dir().glob(f"{FAKE_INSTANCE}-*.tar.gz"):
        stray.unlink()
    if paths.active_link().is_symlink() or paths.active_link().exists():
        instances.set_active("main")
    settings = paths.load_settings()
    settings["active_instance"] = "main"
    paths.save_settings(settings)


def main():
    reset()
    try:
        test_logs()
        test_backup()
        test_instances_index()
        test_offline_uuid()
        test_player_lists()
        test_build_instance()
        test_clone_rename_delete()
        test_paper_version_change_guard()
    finally:
        cleanup()
    print("PASS core-more")


if __name__ == "__main__":
    main()
