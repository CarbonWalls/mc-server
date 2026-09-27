from ..core import instances, procs, version
from ..ui import theme as th
from ..ui import widgets as w
from ..ui.wizard import Step


class NameStep(Step):
    key = "name"
    title = "instance id"
    hint = "letters, digits, - or _ (max 32). this becomes the folder name"
    handles_enter = True

    def on_enter(self, wiz):
        if self.widget is None:
            self.widget = w.TextEdit(str(wiz.data.get("name", "")), label="id",
                                     validator=instances.validate_name)

    def render(self, wiz, win, y, x, h, width, theme):
        self.widget.render(win, y, x, width, theme)
        th.safe_addstr(win, y + 3, x,
                       "the active instance is not renamed; start.sh keeps using main",
                       theme.dim)

    def handle_key(self, wiz, key):
        if self.widget.handle_key(key) == "submit":
            wiz.data["name"] = self.widget.value.strip()
            wiz.data.setdefault("display", wiz.data["name"])
            return "next"
        return None

    def validate(self, wiz):
        return instances.validate_name(str(wiz.data.get("name", "")))

    def summary(self, wiz):
        return [("instance id", wiz.data.get("name", ""))]

    widget = None


class LocationStep(Step):
    """Where the server folder lives. Defaults to instances/<id>; any writable
    folder is accepted, inside or outside the project tree."""
    key = "location"
    title = "location"
    hint = "where the server folder goes. enter edits; blank = instances/<id>"
    handles_enter = True
    widget = None

    def on_enter(self, wiz):
        default = str(wiz.data.get("location", "")) or \
            f"instances/{wiz.data.get('name', '')}"
        name = str(wiz.data.get("name", ""))
        self.widget = w.TextEdit(default, label="folder",
                                 validator=lambda v: instances.validate_path(v, name))

    def render(self, wiz, win, y, x, h, width, theme):
        self.widget.render(win, y, x, width, theme)
        lines = [
            "relative paths are inside this project, absolute paths anywhere,",
            "e.g. /mnt/games/minecraft. the folder is created if missing.",
        ]
        for i, line in enumerate(lines):
            th.safe_addstr(win, y + 3 + i, x, th.trunc(line, width), theme.dim)

    def handle_key(self, wiz, key):
        if self.widget.handle_key(key) == "submit":
            wiz.data["location"] = self.widget.value.strip()
            return "next"
        return None

    def validate(self, wiz):
        return instances.validate_path(str(wiz.data.get("location", "")),
                                       str(wiz.data.get("name", "")))

    def summary(self, wiz):
        return [("location", wiz.data.get("location", "")
                 or f"instances/{wiz.data.get('name', '')}")]


class VersionStep(Step):
    key = "paper"
    title = "paper version"
    hint = "releases first; pre-releases are marked. needs network on first load"
    handles_enter = True
    widget = None

    def on_enter(self, wiz):
        self.widget = w.ListView([])
        self.loaded = wiz.data.get("versions")
        if self.loaded:
            self.widget.set_items(self._labels(self.loaded), keep_index=False)
            return
        wiz.set_info("fetching paper versions...")

        def job_fn(job):
            job.update(0.05, "querying papermc")
            return version.paper_versions(limit=25, job=job)

        def done(job):
            result = job.result or []
            wiz.data["versions"] = result
            self.loaded = result
            if self.widget is not None:
                self.widget.set_items(self._labels(result), keep_index=False)
            if result:
                wiz.set_info(f"{len(result)} versions loaded")
            else:
                wiz.set_error("could not fetch versions (network?) - press r/← and retry")

        wiz.ctx.run_job("paper versions", job_fn, on_done=done)

    @staticmethod
    def _labels(entries):
        labels = []
        for entry in entries:
            tag = "" if entry.get("release") else "   (pre/snapshot)"
            java = f"   java>={entry['min_java']}" if entry.get("min_java") else ""
            labels.append(f"{entry.get('key')}{tag}{java}")
        return labels or ["(loading...)"]

    def render(self, wiz, win, y, x, h, width, theme):
        if not self.loaded:
            th.safe_addstr(win, y, x, "loading versions...", theme.dim)
            if wiz.data.get("versions"):
                self.loaded = wiz.data["versions"]
                self.widget.set_items(self._labels(self.loaded), keep_index=False)
            return
        self.widget.render(win, y, x, h, width, theme, "paper versions")

    def handle_key(self, wiz, key):
        if not self.loaded:
            return None
        action = self.widget.handle_key(key, height=10)
        if action == "select":
            entry = self.loaded[self.widget.index]
            wiz.data["version_key"] = entry.get("key")
            wiz.data["default_build"] = entry.get("build")
            wiz.data["min_java"] = entry.get("min_java")
            return "next"
        return None

    def validate(self, wiz):
        if not wiz.data.get("version_key"):
            return "pick a version (⏎)"
        return ""

    def summary(self, wiz):
        return [("paper version", wiz.data.get("version_key", ""))]


class BuildStep(Step):
    key = "build"
    title = "paper build"
    hint = "latest build of the chosen version is preselected"
    handles_enter = True
    widget = None

    def on_enter(self, wiz):
        self.widget = w.ListView([])
        self.builds = []
        key = wiz.data.get("version_key", "")
        default = wiz.data.get("default_build")
        if default:
            self.builds = [default]
            wiz.data["builds"] = self.builds
            wiz.data.setdefault("build", default)
            self.widget.set_items(self._labels(self.builds), keep_index=False)
            wiz.set_info(f"build {default.get('number')} preselected (latest for {key})")
            return
        wiz.set_info(f"fetching builds for {key}...")

        def job_fn(job):
            job.update(0.05, f"querying builds for {key}")
            return version.paper_builds(key, limit=15, job=job)

        def done(job):
            result = job.result or []
            wiz.data["builds"] = result
            self.builds = result
            if self.widget is not None:
                self.widget.set_items(self._labels(result), keep_index=False)
            if result:
                wiz.set_info(f"{len(result)} builds loaded")
            else:
                wiz.set_error("no builds returned for that version")

        wiz.ctx.run_job("paper builds", job_fn, on_done=done)

    @staticmethod
    def _labels(entries):
        return [f"build {e.get('number')}  {e.get('channel', '')}  "
                f"{str(e.get('createdAt', ''))[:19]}  "
                f"{procs.format_bytes(e.get('size', 0))}" for e in entries] or ["(none)"]

    def render(self, wiz, win, y, x, h, width, theme):
        if wiz.data.get("builds") and not self.builds:
            self.builds = wiz.data["builds"]
            self.widget.set_items(self._labels(self.builds), keep_index=False)
        if not self.builds:
            th.safe_addstr(win, y, x, "loading builds...", theme.dim)
            return
        self.widget.render(win, y, x, h, width, theme, "builds")

    def handle_key(self, wiz, key):
        if not self.builds:
            return None
        action = self.widget.handle_key(key, height=10)
        if action == "select":
            wiz.data["build"] = self.builds[self.widget.index]
            return "next"
        return None

    def validate(self, wiz):
        if not wiz.data.get("build") and self.builds:
            wiz.data["build"] = self.builds[0]
        if not wiz.data.get("build"):
            return "no build available for that version"
        return ""

    def summary(self, wiz):
        build = wiz.data.get("build") or {}
        return [("build", str(build.get("number", "?")))]


class PerfStep(Step):
    key = "perf"
    title = "memory preset"
    hint = "heap + view distance + max players for this device"
    handles_enter = True
    widget = None

    def on_enter(self, wiz):
        self.widget = w.ListView(list(procs.PRESETS.keys()))
        keys = list(procs.PRESETS.keys())
        current = wiz.data.get("perf", "balanced")
        self.widget.index = max(0, keys.index(current)) if current in keys else 1

    def render(self, wiz, win, y, x, h, width, theme):
        self.widget.render(win, y, x, min(h, 6), width, theme, "presets")
        key = list(procs.PRESETS.keys())[self.widget.index]
        preset = procs.PRESETS[key]
        lines = [
            f"label        {preset['label']}",
            f"xms / xmx    {preset['xms']} / {preset['xmx']}",
            f"view dist    {preset['view']}   simulation {preset['simulation']}",
            f"max players  {preset['max_players']}",
        ]
        for i, line in enumerate(lines):
            th.safe_addstr(win, y + min(h, 6) + 1 + i, x, line, theme.plain)

    def handle_key(self, wiz, key):
        action = self.widget.handle_key(key, height=4)
        if action in ("up", "down"):
            wiz.data["perf"] = list(procs.PRESETS.keys())[self.widget.index]
            return None
        if action == "select":
            wiz.data["perf"] = list(procs.PRESETS.keys())[self.widget.index]
            return "next"
        return None

    def validate(self, wiz):
        wiz.data.setdefault("perf", "balanced")
        preset = procs.PRESETS[wiz.data["perf"]]
        wiz.data["xms"] = preset["xms"]
        wiz.data["xmx"] = preset["xmx"]
        return ""

    def summary(self, wiz):
        preset = procs.PRESETS.get(wiz.data.get("perf", "balanced"), {})
        return [("preset", preset.get("label", "?")),
                ("heap", f"{preset.get('xms')} / {preset.get('xmx')}")]
