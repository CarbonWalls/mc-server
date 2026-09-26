from ..core import procs, version
from ..ui import theme as th
from ..ui import widgets as w
from ..ui.wizard import Step


class GameplayStep(Step):
    key = "gameplay"
    title = "gameplay"
    hint = "enter edits a value, arrows move"
    handles_enter = True
    widget = None
    edit = None

    ROWS = [
        ("motd", "message of the day", "text"),
        ("max-players", "max players", "int"),
        ("difficulty", "difficulty peaceful|easy|normal|hard", "choice"),
        ("gamemode", "default gamemode survival|creative|adventure|spectator", "choice"),
        ("pvp", "pvp on/off", "bool"),
        ("white-list", "whitelist on/off", "bool"),
        ("online-mode", "online-mode (premium accounts)", "bool"),
        ("view-distance", "view distance", "int"),
        ("simulation-distance", "simulation distance", "int"),
    ]
    CHOICES = {
        "difficulty": ["peaceful", "easy", "normal", "hard"],
        "gamemode": ["survival", "creative", "adventure", "spectator"],
    }

    def on_enter(self, wiz):
        self.widget = w.ListView([f"{key:<22}{wiz.data.get('props', {}).get(key, '')}"
                                  for key, _d, _k in self.ROWS])
        if "props" not in wiz.data:
            preset = procs.PRESETS[wiz.data.get("perf", "balanced")]
            wiz.data["props"] = {
                "motd": f"A Minecraft Server ({wiz.data.get('name', '')})",
                "max-players": str(preset["max_players"]),
                "difficulty": "normal",
                "gamemode": "survival",
                "pvp": "true",
                "white-list": "false",
                "online-mode": "true",
                "view-distance": str(preset["view"]),
                "simulation-distance": str(preset["simulation"]),
            }
        self._sync(wiz)

    def _sync(self, wiz):
        props = wiz.data.get("props", {})
        self.widget.set_items([f"{key:<22}{props.get(key, '')}"
                               for key, _d, _k in self.ROWS], keep_index=True)

    def render(self, wiz, win, y, x, h, width, theme):
        self.widget.render(win, y, x, h, width, theme, "server.properties")
        if self.edit is not None:
            key, _desc, _kind = self.ROWS[self.widget.index]
            self.edit.render(win, y + h - 2, x, min(width, 50), theme)

    def handle_key(self, wiz, key):
        if self.edit is not None:
            action = self.edit.handle_key(key)
            if action == "submit":
                value = self.edit.value.strip()
                kind = self.ROWS[self.widget.index][2]
                error = self._check(kind, value)
                if error:
                    self.edit.error = error
                    return None
                wiz.data.setdefault("props", {})[self.ROWS[self.widget.index][0]] = value
                self.edit = None
                self._sync(wiz)
            elif key == 27:
                self.edit = None
            return None
        action = self.widget.handle_key(key, height=10)
        if action == "select":
            key_name, _desc, kind = self.ROWS[self.widget.index]
            if kind == "choice":
                options = self.CHOICES[key_name]
                props = wiz.data.setdefault("props", {})
                current = props.get(key_name, options[0])
                index = options.index(current) if current in options else 0
                props[key_name] = options[(index + 1) % len(options)]
                self._sync(wiz)
                return None
            if kind == "bool":
                props = wiz.data.setdefault("props", {})
                props[key_name] = "false" if props.get(key_name) == "true" else "true"
                self._sync(wiz)
                return None
            current = wiz.data.setdefault("props", {}).get(key_name, "")
            self.edit = w.TextEdit(current, label=key_name)
            return None
        return None

    @staticmethod
    def _check(kind, value):
        if kind == "int":
            if not value.isdigit() or int(value) < 1:
                return "positive integer required"
            if int(value) > 1000:
                return "that looks too large"
        if kind == "text" and len(value) > 60:
            return "max 60 characters"
        return ""

    def summary(self, wiz):
        props = wiz.data.get("props", {})
        return [("motd", props.get("motd", "")),
                ("max players", props.get("max-players", "")),
                ("whitelist", props.get("white-list", ""))]


class NetworkStep(Step):
    key = "network"
    title = "network"
    hint = "tunnel + ports. bedrock needs Geyser (port 44041)"
    handles_enter = True
    widget = None
    edit = None

    ROWS = [
        ("tunnel", "tunnel: bore|playit|none", "choice"),
        ("server-port", "java edition port", "int"),
        ("bedrock", "install Geyser + Floodgate (bedrock)", "bool"),
        ("bedrock-port", "bedrock port", "int"),
    ]
    TUNNELS = ["bore", "playit", "none"]

    def on_enter(self, wiz):
        if "net" not in wiz.data:
            wiz.data["net"] = {
                "tunnel": wiz.ctx.settings.get("tunnel", "bore"),
                "server-port": str(wiz.ctx.settings.get("server_port", 25565)),
                "bedrock": "true",
                "bedrock-port": str(wiz.ctx.settings.get("bedrock_port", 44041)),
            }
        self.widget = w.ListView([])
        self._sync(wiz)

    def _sync(self, wiz):
        net = wiz.data.get("net", {})
        labels = []
        for key, desc, _kind in self.ROWS:
            value = net.get(key, "")
            if key == "bedrock":
                value = "yes" if value == "true" else "no"
            labels.append(f"{desc:<48}{value}")
        self.widget.set_items(labels, keep_index=True)

    def render(self, wiz, win, y, x, h, width, theme):
        self.widget.render(win, y, x, h, width, theme, "network")
        if self.edit is not None:
            self.edit.render(win, y + h - 2, x, min(width, 40), theme)

    def handle_key(self, wiz, key):
        net = wiz.data.setdefault("net", {})
        if self.edit is not None:
            action = self.edit.handle_key(key)
            if action == "submit":
                value = self.edit.value.strip()
                if not value.isdigit() or not (1 <= int(value) <= 65535):
                    self.edit.error = "port must be 1-65535"
                    return None
                net[self.ROWS[self.widget.index][0]] = value
                self.edit = None
                self._sync(wiz)
            elif key == 27:
                self.edit = None
            return None
        action = self.widget.handle_key(key, height=6)
        if action == "select":
            key_name, _desc, kind = self.ROWS[self.widget.index]
            if key_name == "tunnel":
                index = self.TUNNELS.index(net.get("tunnel", "bore")) \
                    if net.get("tunnel") in self.TUNNELS else 0
                net["tunnel"] = self.TUNNELS[(index + 1) % len(self.TUNNELS)]
                self._sync(wiz)
            elif key_name == "bedrock":
                net["bedrock"] = "false" if net.get("bedrock") == "true" else "true"
                self._sync(wiz)
            else:
                self.edit = w.TextEdit(net.get(key_name, ""), label=key_name)
            return None
        return None

    def summary(self, wiz):
        net = wiz.data.get("net", {})
        return [("tunnel", net.get("tunnel", "")),
                ("java port", net.get("server-port", "")),
                ("bedrock", "yes" if net.get("bedrock") == "true" else "no"),
                ("bedrock port", net.get("bedrock-port", ""))]


class PluginsStep(Step):
    key = "plugins"
    title = "plugins"
    hint = "space/⏎ toggles. resolution needs network"
    handles_enter = True
    widget = None

    def on_enter(self, wiz):
        selected = set(wiz.data.get("plugins", ["essentialsx", "luckperms", "vault"]))
        self.selected = selected
        self.widget = w.ListView(self._labels())
        if not wiz.data.get("specs_ready"):
            wiz.set_info("resolving plugin downloads...")
            wanted = set(wiz.data.get("plugins", []))
            net = wiz.data.get("net", {})
            if net.get("bedrock") == "true":
                wanted |= {"geyser", "floodgate"}

            def job_fn(job, wanted_ids, game_version):
                job.update(0.2, "resolving plugin downloads")
                return version.resolve_all_plugins(game_version, wanted=wanted_ids)

            def done(job):
                result = job.result if isinstance(job.result, list) else []
                wiz.data["specs"] = result
                wiz.data["specs_ready"] = True
                if not job.ok:
                    wiz.set_error(f"plugin resolution failed: {job.error}")
                elif any(e.get("error") for e in result):
                    wiz.set_info("some plugins could not be resolved (see review)")
                else:
                    wiz.set_info(f"{len(result)} plugin downloads resolved")

            wiz.ctx.run_job("resolve plugins", job_fn, wanted,
                            str(wiz.data.get("version_key", "")), on_done=done)

    def _labels(self):
        from ..core.version import PLUGINS
        out = []
        for plugin in PLUGINS:
            mark = "[x]" if plugin["id"] in self.selected else "[ ]"
            out.append(f"{mark} {plugin['name']:<14}{plugin['desc']}")
        return out

    def render(self, wiz, win, y, x, h, width, theme):
        self.widget.render(win, y, x, max(3, h - 1), width, theme, "plugin catalog")
        status = "resolved" if wiz.data.get("specs_ready") else "resolving (network)..."
        th.safe_addstr(win, y + h - 1, x, status, theme.dim)

    def handle_key(self, wiz, key):
        if key == ord(" "):
            from ..core.version import PLUGINS
            plugin = PLUGINS[self.widget.index]
            if plugin["id"] in self.selected:
                self.selected.discard(plugin["id"])
            else:
                self.selected.add(plugin["id"])
            wiz.data["plugins"] = sorted(self.selected)
            self.widget.set_items(self._labels(), keep_index=True)
            return None
        action = self.widget.handle_key(key, height=10)
        if action == "select":
            from ..core.version import PLUGINS
            plugin = PLUGINS[self.widget.index]
            if plugin["id"] in self.selected:
                self.selected.discard(plugin["id"])
            else:
                self.selected.add(plugin["id"])
            wiz.data["plugins"] = sorted(self.selected)
            self.widget.set_items(self._labels(), keep_index=True)
            return None
        return None

    def validate(self, wiz):
        wanted = set(wiz.data.get("plugins", []))
        net = wiz.data.get("net", {})
        if net.get("bedrock") == "true":
            wanted |= {"geyser", "floodgate"}
        if wanted and not wiz.data.get("specs_ready"):
            return "plugin resolution still running - wait a moment and press → again"
        return ""

    def summary(self, wiz):
        return [("plugins", ", ".join(wiz.data.get("plugins", [])) or "none")]


class ReviewStep(Step):
    key = "review"
    title = "review"
    hint = "everything below is written to instances/<id>"
    widget = None

    def on_enter(self, wiz):
        self.widget = None
        wiz.set_info("press → to start the build")

    def render(self, wiz, win, y, x, h, width, theme):
        rows = wiz.summary()
        for i, (label, value) in enumerate(rows[: h]):
            th.safe_addstr(win, y + i, x, th.trunc(f"{label:<18}", 20), theme.dim)
            th.safe_addstr(win, y + i, x + 20, th.trunc(str(value), width - 22), theme.plain)

    def handle_key(self, wiz, key):
        return None

    def summary(self, wiz):
        return []
