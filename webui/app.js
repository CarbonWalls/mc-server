"use strict";
/* ==========================================================================
   0. SMALL HELPERS
   ========================================================================== */
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function fmtBytes(b) {
  if (b == null || isNaN(b)) return "—";
  if (b === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const i = Math.min(Math.floor(Math.log(Math.abs(b)) / Math.log(1024)), units.length - 1);
  const v = b / Math.pow(1024, i);
  return (i === 0 ? v : v.toFixed(v < 10 ? 1 : 0)) + " " + units[i];
}

function fmtUptime(sec) {
  if (!sec && sec !== 0) return "—";
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (d) return d + "d " + h + "h";
  if (h) return h + "h " + m + "m";
  if (m) return m + "m " + s + "s";
  return s + "s";
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit"
  });
}

function fmtRel(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  if (diff < 2592000) return Math.floor(diff / 86400) + "d ago";
  return fmtDate(iso);
}

function pluralise(n, one, many) {
  return n + " " + (n === 1 ? one : many);
}

/* ==========================================================================
   1. ICONS (hand-written inline SVG)
   ========================================================================== */
const SVG_OPEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
                 'stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" ' +
                 'aria-hidden="true">';

function icon(paths) { return SVG_OPEN + paths + "</svg>"; }

const ICONS = {
  dashboard: icon('<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>'),
  console:   icon('<rect x="2.5" y="4" width="19" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/>'),
  players:   icon('<path d="M16 20v-1.8a3.6 3.6 0 0 0-3.6-3.6H6.6A3.6 3.6 0 0 0 3 18.2V20"/><circle cx="9.5" cy="8" r="3.4"/><path d="M21 20v-1.8a3.6 3.6 0 0 0-2.7-3.48"/><path d="M15.5 4.6a3.6 3.6 0 0 1 0 6.9"/>'),
  backups:   icon('<path d="M20.5 13.5V18a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-4.5"/><path d="M16.5 8 12 3.5 7.5 8"/><path d="M12 3.5V15"/>'),
  plus:      icon('<path d="M12 5v14M5 12h14"/>'),
  settings:  icon('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.3a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 8.9 4.6a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V10a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09A1.7 1.7 0 0 0 19.4 15z"/>'),
  play:      icon('<path d="M6.5 4.5v15l13-7.5-13-7.5z"/>'),
  stop:      icon('<rect x="6" y="6" width="12" height="12" rx="1.5"/>'),
  kill:      icon('<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>'),
  copy:      icon('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
  trash:     icon('<path d="M3.5 6h17M9 6V4.5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 4.5V6"/><path d="M18.5 6l-.9 13.1a2 2 0 0 1-2 1.9h-7.2a2 2 0 0 1-2-1.9L5.5 6"/><path d="M10 10.5v6M14 10.5v6"/>'),
  refresh:   icon('<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 4v5h-5"/>'),
  x:         icon('<path d="M18 6 6 18M6 6l12 12"/>'),
  send:      icon('<path d="M21.5 2.5 10.8 13.2M21.5 2.5 14.7 21.5l-3.9-8.3-8.3-3.9 19-6.8z"/>'),
  warn:      icon('<path d="M10.3 3.9 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
  check:     icon('<path d="M20 6 9 17l-5-5"/>'),
  folder:    icon('<path d="M3 7.5A2 2 0 0 1 5 5.5h4l2 2.5h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
  box:       icon('<path d="M21 8.5 12 3 3 8.5v7L12 21l9-5.5z"/><path d="M3 8.5 12 14l9-5.5M12 14v7"/>'),
  sun:       icon('<circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/>'),
  moon:      icon('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
  power:     icon('<path d="M18.4 6.6a9 9 0 1 1-12.8 0"/><path d="M12 2v10"/>'),
  shield:    icon('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'),
  user:      icon('<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>'),
  link:      icon('<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>'),
  clock:     icon('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  chevronL:  icon('<path d="M15 18l-6-6 6-6"/>'),
  chevronR:  icon('<path d="M9 6l6 6-6 6"/>')
};

/* ==========================================================================
   2. STATE
   ========================================================================== */
const params = new URLSearchParams(location.search);

const state = {
  mock: params.get("mock") === "1",
  screen: "dashboard",
  instance: "main",

  instances: [],
  instancesLoaded: false,
  online: true,            // false when the backend is unreachable

  status: null,
  players: null,
  logs: [],                // lines for the console screen
  backups: null,
  tunnels: null,
  jobs: [],

  wizard: null,            // created lazily
  consoleHistory: [],
  consoleHistoryIndex: -1,

  connectTimer: null       // the Connect screen's claim poll, see navigate()
};

/* ==========================================================================
   3. MOCK DATA (used when ?mock=1)
   ========================================================================== */
const MOCK_LOGS = [
  "[12:00:01 INFO]: Starting minecraft server version 1.21.4",
  "[12:00:01 INFO]: Loading properties",
  "[12:00:02 INFO]: Default game type: SURVIVAL",
  "[12:00:02 INFO]: Generating keypair",
  "[12:00:03 INFO]: Starting Minecraft server on *:25565",
  "[12:00:03 INFO]: Using epoll channel type",
  "[12:00:04 INFO]: Preparing level \"world\"",
  "[12:00:05 INFO]: Preparing start region for dimension minecraft:overworld",
  "[12:00:08 INFO]: Time elapsed: 2841 ms",
  "[12:00:09 INFO]: Preparing spawn area: 0%",
  "[12:00:11 INFO]: Preparing spawn area: 92%",
  "[12:00:11 INFO]: Done (9.412s)! For help, type \"help\"",
  "[12:02:14 INFO]: Steve[/192.168.1.42:51234] logged in with entity id 128",
  "[12:02:14 INFO]: Steve joined the game",
  "[12:03:41 INFO]: Alex[/192.168.1.55:51822] logged in with entity id 204",
  "[12:03:41 INFO]: Alex joined the game",
  "[12:07:02 INFO]: <Steve> anyone got spare iron",
  "[12:07:19 INFO]: <Alex> yeah check the chest by the portal",
  "[12:11:55 WARN]: Can't keep up! Is the server overloaded? Running 2140ms or 42 ticks behind",
  "[12:11:56 INFO]: Steve lost connection: Disconnected",
  "[12:11:56 INFO]: Steve left the game",
  "[12:14:03 INFO]: <Alex> lag spike?",
  "[12:14:31 INFO]: Saving the game (this may take a moment!)",
  "[12:14:31 INFO]: Saved the game",
  "[12:16:02 ERROR]: Could not pass event PlayerMoveEvent to EssentialsX v2.20.1",
  "[12:16:02 INFO]: Alex issued server command: /home",
  "[12:18:44 INFO]: Alex left the game"
];

const MOCK = {
  status: {
    instance: "main",
    name: "Main Server",
    server: { state: "running", pid: 4821, uptime: 14723, rss: 734003200 },
    playitd: { state: "running", pid: 4822 },
    tunnel: { state: "running" },
    disk: { free: 52428800000 },
    java: 'openjdk version "21.0.2" 2024-01-16',
    paper: { version: "1.21.4", build: 129 }
  },
  instances: {
    active: "main",
    instances: [
      {
        id: "main", name: "Main Server", path: "/home/user/mc/main", exists: true,
        paper_version: "1.21.4", build: 129, tunnel: "playit", bedrock_port: null,
        state: "running", created: "2024-01-15T10:30:00Z", note: "Primary survival world",
        xms: "4G", xmx: "4G", java_override: "", server_port: "25565", builtin: true
      },
      {
        id: "creative", name: "Creative World", path: "/home/user/mc/creative", exists: true,
        paper_version: "1.21.4", build: 129, tunnel: "bore", bedrock_port: 19132,
        state: "stopped", created: "2024-02-20T14:20:00Z", note: "Building & redstone",
        xms: "2G", xmx: "2G", java_override: "", server_port: "25566", builtin: false
      },
      {
        id: "modded", name: "Modded Test", path: "/home/user/mc/modded", exists: false,
        paper_version: "1.20.6", build: 91, tunnel: "none", bedrock_port: null,
        state: "missing", created: "2024-03-01T09:00:00Z", note: "",
        xms: "", xmx: "", java_override: "", server_port: "", builtin: false
      }
    ]
  },
  logs: { lines: MOCK_LOGS.slice() },
  players: {
    online: ["Steve"],
    recent: ["Steve", "Alex", "Notch"],
    whitelist: ["Steve", "Alex", "Notch"],
    ops: ["Alex"],
    // TODO: "bans" is not in the API contract — assumed shape shown here.
    bans: [{ name: "Griefer99", reason: "Destroyed spawn", created: "2024-03-12T18:40:00Z" }],
    whitelist_enabled: true,
    online_mode: false,
    max_players: 12
  },
  backups: {
    backups: [
      {
        name: "backup-2024-03-15-120000", instance: "main", size: 1048576000,
        stamp: "2024-03-15T12:00:00Z",
        path: "/home/user/mc/main/backups/backup-2024-03-15-120000.zip"
      },
      {
        name: "backup-2024-03-10-180000", instance: "main", size: 987654321,
        stamp: "2024-03-10T18:00:00Z",
        path: "/home/user/mc/main/backups/backup-2024-03-10-180000.zip"
      },
      {
        name: "backup-2024-03-01-090000", instance: "main", size: 812345678,
        stamp: "2024-03-01T09:00:00Z",
        path: "/home/user/mc/main/backups/backup-2024-03-01-090000.zip"
      }
    ]
  },
  tunnels: {
    tunnels: [{
      host: "laurel-reef.tun.ply.gg", port: "25565",
      destination: "127.0.0.1:25565", proto: "TCP",
      disabled: false, reason: null
    }],
    account: { status: "claimed", login_link: "https://playit.gg/claim/abc123" },
    has_secret: true, claim_url: "", playitd: "running"
  },
  // key is the path minus /api/: what GET /api/paper/versions returns
  "paper/versions": {
    versions: [
      { version: "1.21.4", build: 129, release: true, min_java: 21 },
      { version: "1.21.1", build: 133, release: true, min_java: 21 },
      { version: "1.20.6", build: 151, release: true, min_java: 17 },
      { version: "1.20.4", build: 497, release: true, min_java: 17 }
    ]
  },
  jobs: { jobs: [] }
};

/* ==========================================================================
   4. API LAYER
   ========================================================================== */
const API_BASE = ""; // same origin

function mockKey(path) {
  // "/api/status" -> "status"; "/api/logs?x=1" -> "logs"
  return path.replace(/^\/api\//, "").split("?")[0];
}

async function apiGet(path) {
  if (state.mock) {
    const key = mockKey(path);
    const value = MOCK[key];
    if (value === undefined) return null;
    return JSON.parse(JSON.stringify(value));
  }
  try {
    const res = await fetch(API_BASE + path, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    state.online = true;
    return await res.json();
  } catch (err) {
    state.online = false;
    console.warn("[api] GET " + path + " failed:", err.message);
    return null;
  }
}

async function apiPost(path, body) {
  if (state.mock) {
    return mockPost(path, body || {});
  }
  try {
    const res = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {})
    });
    state.online = true;
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      return { ok: false, error: (data && data.error) || ("Request failed (" + res.status + ")") };
    }
    return data || { ok: true };
  } catch (err) {
    state.online = false;
    console.warn("[api] POST " + path + " failed:", err.message);
    return { ok: false, error: "Cannot reach the backend." };
  }
}

/* --- Mock POST behaviour: keep the fixture internally consistent ---------- */
function mockPost(path, body) {
  const p = path.replace(/^\/api\//, "");
  const ok = { ok: true };

  switch (p) {
    case "server/start":
      MOCK.status.server.state = "running";
      MOCK.status.server.pid = 4821;
      MOCK.status.server.uptime = 0;
      MOCK.status.server.rss = 268435456;
      syncInstanceState(body.instance || state.instance, "running");
      pushMockLog("[12:00:01 INFO]: Starting minecraft server version 1.21.4");
      pushMockLog("[12:00:11 INFO]: Done (9.412s)! For help, type \"help\"");
      return ok;

    case "server/stop":
      MOCK.status.server.state = "stopped";
      MOCK.status.server.pid = null;
      MOCK.status.server.uptime = 0;
      syncInstanceState(body.instance || state.instance, "stopped");
      pushMockLog("[12:19:02 INFO]: Stopping the server");
      pushMockLog("[12:19:04 INFO]: Saving the game (this may take a moment!)");
      pushMockLog("[12:19:05 INFO]: Saved the game");
      return ok;

    case "server/kill":
      MOCK.status.server.state = "stopped";
      MOCK.status.server.pid = null;
      MOCK.status.server.uptime = 0;
      syncInstanceState(body.instance || state.instance, "stopped");
      pushMockLog("[12:19:02 WARN]: Forcing server shutdown (SIGKILL)");
      return ok;

    case "console":
      if (body.command) {
        pushMockLog("[12:19:30 INFO]: " + body.command);
        const cmd = String(body.command).trim();
        if (/^say\s+/i.test(cmd)) {
          pushMockLog("[12:19:30 INFO]: [Server] " + cmd.replace(/^say\s+/i, ""));
        }
        if (/^kick\s+(\S+)/i.test(cmd)) {
          const who = cmd.match(/^kick\s+(\S+)/i)[1];
          MOCK.players.online = MOCK.players.online.filter(n => n !== who);
          pushMockLog("[12:19:30 INFO]: " + who + " left the game");
        }
        if (/^whitelist\s+add\s+(\S+)/i.test(cmd)) {
          const who = cmd.match(/^whitelist\s+add\s+(\S+)/i)[1];
          if (!MOCK.players.whitelist.includes(who)) MOCK.players.whitelist.push(who);
        }
      }
      return ok;

    case "instances/active": {
      const inst = MOCK.instances.instances.find(i => i.id === body.id);
      if (!inst) return { ok: false, error: "No such instance: " + body.id };
      MOCK.instances.active = body.id;
      state.instance = body.id;
      applyMockStatusFor(body.id);
      MOCK.logs.lines = MOCK_LOGS.slice();
      return ok;
    }

    case "instances/create": {
      if (!body.id) return { ok: false, error: "Missing instance id" };
      if (MOCK.instances.instances.some(i => i.id === body.id)) {
        return { ok: false, error: "An instance with that id already exists" };
      }
      MOCK.instances.instances.push({
        id: body.id, name: body.name || body.id, path: body.path,
        exists: true, paper_version: body.version || "1.21.4", build: body.build || 129,
        tunnel: body.tunnel || "playit", bedrock_port: body.geyser ? 19132 : null,
        state: "stopped", created: new Date().toISOString(), note: ""
      });
      MOCK.jobs.jobs = [{
        id: "job-1", name: "create " + body.id, progress: 0,
        message: "preparing files", done: false, ok: false, error: ""
      }];
      simulateJob("create " + body.id);
      return { ok: true, job: "job-1" };
    }

    case "instances/delete": {
      const idx = MOCK.instances.instances.findIndex(i => i.id === body.id);
      if (idx === -1) return { ok: false, error: "No such instance" };
      MOCK.instances.instances.splice(idx, 1);
      if (MOCK.instances.active === body.id) {
        MOCK.instances.active = MOCK.instances.instances[0] ? MOCK.instances.instances[0].id : "";
      }
      return ok;
    }

    case "instances/rename": {
      const inst = MOCK.instances.instances.find(i => i.id === body.id);
      if (!inst) return { ok: false, error: "No such instance" };
      if (!body.new_id) return { ok: false, error: "Missing new_id" };
      if (MOCK.instances.instances.some(i => i.id === body.new_id)) {
        return { ok: false, error: "Id already in use" };
      }
      if (MOCK.instances.active === inst.id) MOCK.instances.active = body.new_id;
      inst.id = body.new_id;
      return ok;
    }

    case "instances/clone": {
      const src = MOCK.instances.instances.find(i => i.id === body.id);
      if (!src) return { ok: false, error: "No such instance" };
      if (!body.new_id) return { ok: false, error: "Missing new_id" };
      if (MOCK.instances.instances.some(i => i.id === body.new_id)) {
        return { ok: false, error: "Id already in use" };
      }
      const copy = JSON.parse(JSON.stringify(src));
      copy.id = body.new_id;
      copy.name = src.name + " (copy)";
      copy.state = "stopped";
      copy.created = new Date().toISOString();
      MOCK.instances.instances.push(copy);
      return ok;
    }

    case "players/whitelist/add": {
      if (!body.name) return { ok: false, error: "Missing name" };
      if (!MOCK.players.whitelist.includes(body.name)) MOCK.players.whitelist.push(body.name);
      pushMockLog("[12:20:00 INFO]: Added " + body.name + " to the whitelist");
      return ok;
    }
    case "players/whitelist/remove":
      MOCK.players.whitelist = MOCK.players.whitelist.filter(n => n !== body.name);
      pushMockLog("[12:20:00 INFO]: Removed " + body.name + " from the whitelist");
      return ok;

    case "players/op/add":
      if (!MOCK.players.ops.includes(body.name)) MOCK.players.ops.push(body.name);
      pushMockLog("[12:20:00 INFO]: Made " + body.name + " a server operator");
      return ok;
    case "players/op/remove":
      MOCK.players.ops = MOCK.players.ops.filter(n => n !== body.name);
      pushMockLog("[12:20:00 INFO]: Removed " + body.name + " as server operator");
      return ok;

    case "players/kick":
      if (!MOCK.players.online.includes(body.name)) {
        return { ok: false, error: body.name + " is not online" };
      }
      MOCK.players.online = MOCK.players.online.filter(n => n !== body.name);
      pushMockLog("[12:20:00 INFO]: Kicked " + body.name +
        (body.reason ? ": " + body.reason : ""));
      return ok;

    case "players/ban":
      if (!body.name) return { ok: false, error: "Missing name" };
      MOCK.players.online = MOCK.players.online.filter(n => n !== body.name);
      MOCK.players.whitelist = MOCK.players.whitelist.filter(n => n !== body.name);
      if (!MOCK.players.bans) MOCK.players.bans = [];
      MOCK.players.bans.push({
        name: body.name,
        reason: body.reason || "Banned by an operator",
        created: new Date().toISOString()
      });
      pushMockLog("[12:20:00 INFO]: Banned " + body.name +
        (body.reason ? ": " + body.reason : ""));
      return ok;

    case "backups/create": {
      const stamp = new Date();
      const name = "backup-" +
        stamp.toISOString().slice(0, 10) + "-" +
        String(stamp.getHours()).padStart(2, "0") +
        String(stamp.getMinutes()).padStart(2, "0") +
        String(stamp.getSeconds()).padStart(2, "0");
      MOCK.backups.backups.unshift({
        name, instance: body.instance || state.instance,
        size: 1048576000 + Math.floor(Math.random() * 50000000),
        stamp: stamp.toISOString(),
        path: "/home/user/mc/" + (body.instance || state.instance) + "/backups/" + name + ".zip"
      });
      simulateJob("creating backup");
      return { ok: true, path: MOCK.backups.backups[0].path };
    }

    case "backups/restore":
      simulateJob("restoring backup");
      return ok;

    case "backups/delete":
      MOCK.backups.backups = MOCK.backups.backups.filter(b => b.name !== body.name);
      return ok;

    case "instances/settings": {
      const target = MOCK.instances.instances.find(
        i => i.id === (body.instance || state.instance));
      if (!target) return { ok: false, error: "No such instance" };
      if (body.memory) { target.xms = body.memory; target.xmx = body.memory; }
      if (body["server-port"]) target.server_port = body["server-port"];
      if (body.bedrock_port) target.bedrock_port = parseInt(body.bedrock_port, 10);
      if (body.tunnel) target.tunnel = body.tunnel;
      if (body.java) target.java_override = body.java;
      return ok;
    }

    case "instances/paper-version": {
      const target = MOCK.instances.instances.find(
        i => i.id === (body.instance || state.instance));
      if (!target) return { ok: false, error: "No such instance" };
      simulateJob("installing paper " + (body.version || ""));
      setTimeout(() => {
        target.paper_version = body.version || target.paper_version;
        target.build = body.build || target.build;
        if (state.screen === "servers") renderScreen();
      }, 1600);
      return ok;
    }

    case "instances/tunnel-port": {
      const target = MOCK.instances.instances.find(
        i => i.id === (body.instance || state.instance));
      const port = parseInt(body.port, 10);
      if (!target || !(port > 0 && port < 65536)) {
        return { ok: false, error: "invalid port" };
      }
      const changed = target.bedrock_port !== port;
      target.bedrock_port = port;
      const udp = MOCK.tunnels.tunnels.find(t => t.proto === "UDP");
      if (udp) udp.port = String(port);
      return { ok: true, changed };
    }

    case "playit/start":
      MOCK.status.playitd = { state: "running", pid: 4242 };
      MOCK.tunnels = {
        tunnels: [],
        account: { status: "unclaimed", login_link: "" },
        has_secret: false,
        claim_url: "https://playit.gg/claim/mock-demo-code",
        playitd: "running"
      };
      // simulate the user finishing the one-time browser claim
      clearTimeout(mockPlayitClaimTimer);
      mockPlayitClaimTimer = setTimeout(() => {
        MOCK.tunnels = {
          tunnels: [
            { host: "laurel-reef.tun.ply.gg", port: "25565",
              destination: "127.0.0.1:25565", proto: "TCP", disabled: false, reason: null },
            { host: "laurel-reef.tun.ply.gg", port: "6695",
              destination: "127.0.0.1:19132", proto: "UDP", disabled: false, reason: null }
          ],
          account: { status: "claimed", login_link: "" },
          has_secret: true, claim_url: "", playitd: "running"
        };
        if (state.screen === "connect") {
          toast("Agent claimed — now create the two tunnels", "ok", 6000);
          renderScreen();
        }
      }, 6000);
      return ok;

    case "playit/stop":
      clearTimeout(mockPlayitClaimTimer);
      MOCK.status.playitd = { state: "stopped", pid: null };
      MOCK.tunnels = { tunnels: [], account: null, has_secret: false,
                       claim_url: "", playitd: "stopped" };
      return ok;

    default:
      // Unknown mock endpoint — succeed quietly so the UI stays usable.
      return ok;
  }
}

function syncInstanceState(id, newState) {
  const inst = MOCK.instances.instances.find(i => i.id === id);
  if (inst) inst.state = newState;
}

function applyMockStatusFor(id) {
  const inst = MOCK.instances.instances.find(i => i.id === id);
  if (!inst) return;
  MOCK.status.instance = inst.id;
  MOCK.status.name = inst.name;
  MOCK.status.paper = { version: inst.paper_version, build: inst.build };
  if (inst.state === "running") {
    MOCK.status.server = { state: "running", pid: 4821, uptime: 14723, rss: 734003200 };
    MOCK.status.tunnel = { state: inst.tunnel === "none" ? "stopped" : "running" };
    MOCK.status.playitd = { state: inst.tunnel === "playit" ? "running" : "stopped" };
  } else {
    MOCK.status.server = { state: inst.state, pid: null, uptime: 0, rss: 0 };
    MOCK.status.tunnel = { state: "stopped" };
  }
}

function pushMockLog(line) {
  MOCK.logs.lines.push(line);
  if (MOCK.logs.lines.length > 400) MOCK.logs.lines.shift();
}

let mockJobTimer = null;
let mockPlayitClaimTimer = null;
function simulateJob(label) {
  if (mockJobTimer) clearInterval(mockJobTimer);
  let p = 0;
  MOCK.jobs.jobs = [{
    id: "job-" + Date.now(), name: label, progress: 0,
    message: label, done: false, ok: false, error: ""
  }];
  renderJobBar();
  mockJobTimer = setInterval(() => {
    p += 0.06 + Math.random() * 0.1;
    if (p >= 1) {
      p = 1;
      clearInterval(mockJobTimer);
      mockJobTimer = null;
      MOCK.jobs.jobs = [];
      setTimeout(renderJobBar, 500);
      toast(label + " — done", "ok");
      return;
    }
    MOCK.jobs.jobs[0].progress = p;
    MOCK.jobs.jobs[0].message = label;
    renderJobBar();
  }, 260);
}

/* ==========================================================================
   5. TOASTS
   ========================================================================== */
const MAX_TOASTS = 4;

function toast(message, kind = "ok", timeout = 4200) {
  const host = $("#toasts");
  // Cap the number of simultaneous toasts
  while (host.children.length >= MAX_TOASTS) host.removeChild(host.firstChild);

  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.setAttribute("role", kind === "error" ? "alert" : "status");

  const msg = document.createElement("div");
  msg.className = "msg";
  msg.textContent = message;
  el.appendChild(msg);

  const close = document.createElement("button");
  close.className = "close";
  close.type = "button";
  close.setAttribute("aria-label", "Dismiss");
  close.innerHTML = ICONS.x;
  close.onclick = () => el.remove();
  el.appendChild(close);

  host.appendChild(el);
  if (timeout > 0) setTimeout(() => el.remove(), timeout);
}

/* ==========================================================================
   6. MODAL / CONFIRM
   ========================================================================== */
let modalResolve = null;

function closeModal(result) {
  const host = $("#modalHost");
  const scrim = host.firstElementChild;
  if (scrim) scrim.remove();
  document.removeEventListener("keydown", modalKeyHandler);
  const resolve = modalResolve;
  modalResolve = null;
  if (resolve) resolve(result);
  // Restore focus to whatever was focused before
  if (lastFocused && document.contains(lastFocused)) {
    try { lastFocused.focus(); } catch (_) {}
  }
}

let lastFocused = null;

function modalKeyHandler(e) {
  if (e.key === "Escape") {
    e.preventDefault();
    closeModal(false);
  }
}

/**
 * Show a modal. Returns a Promise.
 * options: { title, body (HTML string), confirmLabel, cancelLabel,
 *            danger (bool), hideCancel (bool),
 *            confirmValue (() => what the promise resolves with instead of
 * *true* — read from a control you put in `body` while the dialog still
 * *exists) }
 */
function openModal(options) {
  closeModal(false); // dismiss anything already open

  lastFocused = document.activeElement;
  const host = $("#modalHost");
  const scrim = document.createElement("div");
  scrim.className = "modal-scrim";

  const dialog = document.createElement("div");
  dialog.className = "modal";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");

  const titleId = "modal-title-" + Date.now();
  dialog.setAttribute("aria-labelledby", titleId);

  dialog.innerHTML =
    '<h2 id="' + titleId + '">' + esc(options.title || "Confirm") + "</h2>" +
    '<div class="body">' + (options.body || "") + "</div>" +
    '<div class="modal-actions">' +
      (options.hideCancel ? "" :
        '<button class="btn" type="button" data-act="cancel">' +
          esc(options.cancelLabel || "Cancel") +
        "</button>") +
      '<button class="btn ' + (options.danger ? "btn-danger" : "btn-primary") +
        '" type="button" data-act="confirm">' +
        esc(options.confirmLabel || "Confirm") +
      "</button>" +
    "</div>";

  scrim.appendChild(dialog);
  host.appendChild(scrim);

  const cancelBtn = dialog.querySelector('[data-act="cancel"]');
  const confirmBtn = dialog.querySelector('[data-act="confirm"]');

  if (cancelBtn) cancelBtn.onclick = () => closeModal(false);
  confirmBtn.onclick = () => {
    if (options.confirmValue) closeModal(options.confirmValue());
    else closeModal(true);
  };
  scrim.addEventListener("mousedown", (e) => {
    if (e.target === scrim) closeModal(false);
  });

  document.addEventListener("keydown", modalKeyHandler);

  // Focus the safest default: cancel for destructive, confirm otherwise.
  // A field the caller put in the body wins over both.
  const field = dialog.querySelector("input, select, textarea");
  const focusTarget = field || (options.danger && cancelBtn ? cancelBtn : confirmBtn);
  setTimeout(() => {
    try { focusTarget.focus(); } catch (_) {}
    if (field && field.tagName === "INPUT") field.select && field.select();
  }, 20);

  return new Promise((resolve) => { modalResolve = resolve; });
}

function confirmDialog(title, bodyHtml, confirmLabel, danger = true) {
  return openModal({
    title,
    body: bodyHtml,
    confirmLabel: confirmLabel || "Confirm",
    danger
  });
}

/* ==========================================================================
   7. JOB BAR
   ========================================================================== */
function renderJobBar() {
  const bar = $("#jobbar");
  const fill = $("#jobbarFill");
  const msg = $("#jobbarMsg");
  const label = $("#jobbarLabel");
  const pct = $("#jobbarPct");

  const active = (state.jobs || []).filter(j => !j.done);
  if (active.length === 0) {
    bar.hidden = true;
    msg.hidden = true;
    return;
  }

  const job = active[0];
  const progress = Math.max(0, Math.min(1, job.progress || 0));

  bar.hidden = false;
  fill.style.width = (progress * 100).toFixed(1) + "%";

  if (active.length > 1) {
    msg.hidden = false;
    label.textContent = job.message || job.name || "working";
    pct.textContent = Math.round(progress * 100) + "% · +" + (active.length - 1);
  } else {
    msg.hidden = false;
    label.textContent = job.message || job.name || "working";
    pct.textContent = Math.round(progress * 100) + "%";
  }
}

function applyJobs(jobsPayload) {
  const jobs = (jobsPayload && jobsPayload.jobs) || [];
  state.jobs = jobs;

  // A job that finished since we last looked has to tell the user how it
  // went — the progress bar just disappears, so a failed clone or Paper
  // install would otherwise vanish silently.
  for (const job of jobs) {
    const prev = jobSeen[job.id];
    if (prev && !prev.done && job.done) {
      if (job.ok) {
        toast(job.message || job.name || "Done", "ok");
      } else {
        toast((job.name || "Job") + " failed: " + (job.error || "unknown error"),
              "error", 9000);
      }
    }
    jobSeen[job.id] = { done: job.done, ok: job.ok };
  }

  renderJobBar();
}

const jobSeen = {};

/* ==========================================================================
   8. NAVIGATION
   ========================================================================== */
const SCREENS = [
  { id: "dashboard", label: "Dashboard", icon: ICONS.dashboard },
  { id: "servers",   label: "Servers",    icon: ICONS.folder },
  { id: "console",   label: "Console",   icon: ICONS.console },
  { id: "players",   label: "Players",   icon: ICONS.players },
  { id: "backups",   label: "Backups",   icon: ICONS.backups },
  { id: "create",    label: "Create server", icon: ICONS.plus },
  { id: "connect",   label: "Connect playit", icon: ICONS.link },
  { id: "settings",  label: "Settings",  icon: ICONS.settings }
];

const TITLES = {
  dashboard: "Dashboard",
  servers: "Servers",
  console: "Console",
  players: "Players",
  backups: "Backups",
  create: "Create server",
  connect: "Connect playit.gg",
  settings: "Settings"
};

function renderNav() {
  const nav = $("#mainNav");
  nav.innerHTML = SCREENS.map(s =>
    '<button class="nav-item" type="button" data-screen="' + s.id + '"' +
      (state.screen === s.id ? ' aria-current="page"' : "") + ">" +
      '<span aria-hidden="true">' + s.icon + "</span>" +
      '<span class="label">' + esc(s.label) + "</span>" +
    "</button>"
  ).join("");

  $$("#mainNav .nav-item").forEach(btn => {
    btn.onclick = () => navigate(btn.dataset.screen);
  });
}

function renderInstanceNav() {
  const nav = $("#instanceNav");
  const list = state.instances || [];
  const heading = $("#instancesHeading");

  if (list.length === 0) {
    heading.hidden = true;
    nav.innerHTML = "";
    return;
  }
  heading.hidden = false;

  nav.innerHTML = list.map(inst => {
    const isActive = inst.id === state.instance;
    const stateClass = instanceStateClass(inst);
    return '<button class="nav-item" type="button" data-instance="' + esc(inst.id) + '"' +
      (isActive ? ' aria-current="true"' : "") + ">" +
      '<span class="dot ' + esc(stateClass) + '" aria-hidden="true"></span>' +
      '<span class="label">' + esc(inst.name || inst.id) + "</span>" +
    "</button>";
  }).join("");

  $$("#instanceNav .nav-item").forEach(btn => {
    btn.onclick = () => switchInstance(btn.dataset.instance);
  });
}

function navigate(screen) {
  if (!TITLES[screen]) screen = "dashboard";
  state.screen = screen;
  // the connect screen polls the agent; every other screen stops that
  if (state.connectTimer) {
    clearInterval(state.connectTimer);
    state.connectTimer = null;
  }
  closeSidebar();
  renderNav();
  renderScreen();
  $("#content").scrollTop = 0;
  window.scrollTo({ top: 0, behavior: "auto" });
}

function setTitle(text, actionsHtml) {
  $("#pageTitle").textContent = text;
  $("#pageActions").innerHTML = actionsHtml || "";
}

function renderScreen() {
  const content = $("#content");
  const screen = state.screen;

  setTitle(TITLES[screen] || "Dashboard", "");

  switch (screen) {
    case "dashboard": renderDashboard(content); break;
    case "servers":   renderServers(content);   break;
    case "console":   renderConsole(content);   break;
    case "players":   renderPlayers(content);   break;
    case "backups":   renderBackups(content);   break;
    case "create":    renderCreate(content);    break;
    case "connect":   renderConnect(content);   break;
    case "settings":  renderSettings(content);  break;
    default:          renderDashboard(content);
  }
}

async function switchInstance(id) {
  if (id === state.instance) return;
  const res = await apiPost("/api/instances/active", { id });
  if (res && res.ok) {
    state.instance = id;
    state.logs = [];
    state.status = null;
    state.players = null;
    renderInstanceNav();
    renderScreen();
  } else {
    toast((res && res.error) || "Could not switch instance", "error");
  }
}

/* ==========================================================================
   9. OFFLINE BANNER HELPER
   ========================================================================== */
function offlineBanner() {
  if (state.mock || state.online) return "";
  return '<div class="offline-banner" role="status">' + ICONS.warn +
    "<span>Can't reach the backend. Showing what we have. " +
    "Make sure the manager is running, or open this page with " +
    "<code>?mock=1</code> to preview the UI.</span></div>";
}

/* ==========================================================================
   10. LOG RENDERING
   ========================================================================== */
function classifyLogLine(line) {
  const s = String(line);
  if (/\b(ERROR|SEVERE|FATAL)\b/.test(s)) return "error";
  if (/\b(WARN|WARNING)\b/.test(s)) return "warn";
  return "";
}

function logLinesHtml(lines) {
  if (!lines || lines.length === 0) {
    return '<div class="log-empty">No log output yet.</div>';
  }
  return lines.map(line => {
    const cls = classifyLogLine(line);
    return '<div class="log-line' + (cls ? " " + cls : "") + '">' +
      esc(line) + "</div>";
  }).join("");
}

function isScrolledToBottom(el, slack = 48) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= slack;
}

/* ==========================================================================
   10b. SCREEN — SERVERS (every instance, per-row actions)
   ========================================================================== */
const TUNNEL_LABELS = {
  playit: "playit.gg", bore: "bore.pub", none: "None"
};

const STATE_LABELS = {
  running: "Running", stopped: "Stopped", stale: "Stale", missing: "Missing"
};

function instanceStateLabel(inst) {
  if (inst.exists === false) return "Missing";
  // 'missing' from the backend means there is no pid file at all, which for
  // a folder that exists is simply 'not running'
  if (inst.state === "missing") return "Stopped";
  return STATE_LABELS[inst.state] || "Stopped";
}

function instanceStateClass(inst) {
  if (inst.exists === false) return "missing";
  if (inst.state === "missing") return "stopped";
  return inst.state || "stopped";
}

/** Is this instance the one the sidebar / dashboard currently point at? */
function isActiveInstance(id) {
  return id === state.instance;
}

async function refreshInstanceList() {
  const list = await apiGet("/api/instances");
  if (list && list.instances) {
    state.instances = list.instances;
    if (list.active) state.instance = list.active;
    renderInstanceNav();
  }
  return list;
}

async function activateInstance(id) {
  if (isActiveInstance(id)) return;
  const res = await apiPost("/api/instances/active", { id });
  if (res && res.ok) {
    state.instance = id;
    state.status = null;
    await refreshInstanceList();
    renderInstanceNav();
    renderScreen();
    toast("Switched to " + id, "ok");
  } else {
    toast((res && res.error) || "Could not switch server", "error");
  }
}

async function startInstance(id) {
  const res = await apiPost("/api/server/start", { instance: id });
  if (res && res.ok) {
    toast("Starting " + id + "…", "info");
    if (isActiveInstance(id) && state.status && state.status.server) {
      state.status.server.state = "running";
    }
    setTimeout(renderScreen, 500);
  } else {
    toast((res && res.error) || "Could not start " + id, "error");
  }
}

async function stopInstance(id, force) {
  const verb = force ? "Force kill" : "Stop";
  const body = force
    ? "<p>This sends <code>SIGKILL</code> to the server process. " +
      "The world <strong>will not be saved</strong> and any players online " +
      "will be disconnected immediately.</p>"
    : "<p>The server will save the world and shut down cleanly. " +
      "All players will be disconnected.</p>";

  const ok = await confirmDialog(verb + " server", body,
                                 force ? "Force kill" : "Stop server", true);
  if (!ok) return;

  const endpoint = force ? "/api/server/kill" : "/api/server/stop";
  const res = await apiPost(endpoint, { instance: id });
  if (res && res.ok) {
    toast(force ? "Killing " + id + "…" : "Stopping " + id + "…", "info");
    if (isActiveInstance(id) && state.status && state.status.server) {
      state.status.server.state = force ? "stopped" : "stale";
    }
    setTimeout(renderScreen, 600);
  } else {
    toast((res && res.error) || "Could not stop " + id, "error");
  }
}

async function renameInstance(id) {
  const value = await openModal({
    title: "Rename server",
    confirmLabel: "Rename",
    body:
      "<p>Renames <code>" + esc(id) + "</code>. The folder on disk is not " +
      "moved, and the server must be stopped.</p>" +
      '<div class="field" style="margin-top:12px">' +
        '<label class="field-label" for="modalInput">New id</label>' +
        '<input class="input" id="modalInput" type="text" spellcheck="false" ' +
          'autocapitalize="off" value="' + esc(id) + '">' +
      "</div>",
    confirmValue: () => {
      const el = $("#modalInput");
      return el ? el.value.trim() : "";
    }
  });
  if (!value) return;
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(value)) {
    toast("Ids must be lowercase letters, numbers, dashes or underscores", "error");
    return renameInstance(id);
  }
  if (value === id) { toast("That is already this server's id", "info"); return; }

  const res = await apiPost("/api/instances/rename", { id, new_id: value });
  if (res && res.ok) {
    toast("Renamed to " + value, "ok");
    await refreshInstanceList();
    renderScreen();
  } else {
    toast((res && res.error) || "Rename failed", "error");
  }
}

async function cloneInstance(id) {
  const value = await openModal({
    title: "Clone server",
    confirmLabel: "Clone",
    body:
      "<p>Copies <code>" + esc(id) + "</code> to a new id, including its " +
      "world, plugins and settings.</p>" +
      '<div class="field" style="margin-top:12px">' +
        '<label class="field-label" for="modalInput">New id</label>' +
        '<input class="input" id="modalInput" type="text" spellcheck="false" ' +
          'autocapitalize="off" value="' + esc(id) + '-copy">' +
      "</div>",
    confirmValue: () => {
      const el = $("#modalInput");
      return el ? el.value.trim() : "";
    }
  });
  if (!value) return;
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(value)) {
    toast("Ids must be lowercase letters, numbers, dashes or underscores", "error");
    return cloneInstance(id);
  }

  const res = await apiPost("/api/instances/clone", { id, new_id: value });
  if (res && res.ok) {
    toast("Cloning to " + value + "…", "info");
    setTimeout(async () => {
      await refreshInstanceList();
      renderScreen();
    }, 800);
  } else {
    toast((res && res.error) || "Clone failed", "error");
  }
}

async function changePaperInstance(id) {
  const data = await apiGet("/api/paper/versions");
  const versions = (data && data.versions) || [];
  if (!versions.length) {
    toast((data && data.error) || "Could not list Paper versions (network?)", "error", 6000);
    return;
  }

  const inst = (state.instances || []).find(i => i.id === id) || {};
  const current = inst.paper_version
    ? "Currently " + esc(inst.paper_version) + " build " + esc(inst.build) + "."
    : "";

  const value = await openModal({
    title: "Change Paper version",
    confirmLabel: "Install",
    body:
      "<p>Replaces <code>paper.jar</code> for <code>" + esc(id) + "</code>. " +
      "The current jar is backed up first, and the server must be stopped.</p>" +
      (current ? "<p>" + current + "</p>" : "") +
      '<div class="field" style="margin-top:12px">' +
        '<label class="field-label" for="paperVersionSelect">Paper version</label>' +
        '<select class="input" id="paperVersionSelect">' +
          versions.map(v =>
            '<option value="' + esc(v.version) + '" data-build="' + esc(v.build) + '">' +
              esc(v.version) + " · build " + esc(v.build) +
              (v.release ? "" : " (snapshot)") +
            "</option>"
          ).join("") +
        "</select>" +
        '<div class="field-hint">Needs a restart, and the newest versions ' +
          "need a newer Java.</div>" +
      "</div>",
    confirmValue: () => {
      const el = $("#paperVersionSelect");
      if (!el) return "";
      return JSON.stringify({ version: el.value,
                              build: el.options[el.selectedIndex].dataset.build });
    }
  });
  if (!value) return;

  let parsed;
  try { parsed = JSON.parse(value); } catch (_) { return; }

  const res = await apiPost("/api/instances/paper-version", {
    instance: id, version: parsed.version, build: parseInt(parsed.build, 10) || 0
  });
  if (res && res.ok) {
    toast("Installing Paper " + parsed.version + "…", "info");
  } else {
    toast((res && res.error) || "Could not change the Paper version", "error");
  }
}

async function deleteInstance(id) {
  const value = await openModal({
    title: "Delete server",
    danger: true,
    confirmLabel: "Delete server",
    body:
      "<p>You are about to delete <code>" + esc(id) + "</code>.</p>" +
      "<p>The world folder on disk is removed. Take a backup first if " +
      "anyone has built anything.</p>" +
      "<label class='check' style='margin-top:12px'>" +
        "<input type='checkbox' id='deleteBackup' checked>" +
        "<span class='check-body'>" +
          "<span class='check-title'>Take a backup first</span>" +
          "<span class='check-desc'>Recommended. Written before anything is removed.</span>" +
        "</span>" +
      "</label>",
    // read the checkbox while the dialog is still in the DOM, so the request
    // matches what the user picked instead of always assuming "yes"
    confirmValue: () => {
      const el = $("#deleteBackup");
      return { confirmed: true, backup: el ? el.checked : true };
    }
  });
  if (!value || !value.confirmed) return;

  const res = await apiPost("/api/instances/delete", {
    id, make_backup: !!value.backup
  });
  if (res && res.ok) {
    toast("Deleted " + id, "ok");
    await refreshInstanceList();
    state.instance = (state.instances[0] && state.instances[0].id) || "";
    renderInstanceNav();
    renderScreen();
  } else {
    toast((res && res.error) || "Delete failed", "error");
  }
}

async function renderServers(container) {
  const listing = await apiGet("/api/instances");
  if (!listing) {
    container.innerHTML = offlineBanner() +
      '<div class="card"><div class="empty">' +
      "Could not list servers. Is the manager running?" +
      "</div></div>";
    return;
  }
  state.instances = listing.instances || [];
  if (listing.active) state.instance = listing.active;
  renderInstanceNav();

  const rows = state.instances;

  container.innerHTML = offlineBanner() + `
    <section class="card" aria-labelledby="servers-h">
      <div class="card-h">
        <span id="servers-h">Servers <span class="pill">${rows.length}</span></span>
        <button class="btn btn-primary btn-sm" id="createServerBtn" type="button">
          ${ICONS.plus}<span>Create server</span>
        </button>
      </div>

      ${rows.length === 0 ? "" : `
      <div class="table-wrap">
        <table class="servers-table">
          <thead>
            <tr>
              <th scope="col">Server</th>
              <th scope="col" class="c-path">Path</th>
              <th scope="col" class="c-paper">Paper</th>
              <th scope="col" class="c-tunnel">Tunnel</th>
              <th scope="col" class="c-bedrock">Bedrock</th>
              <th scope="col">State</th>
              <th scope="col" class="c-created">Created</th>
              <th scope="col" style="text-align:right">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map(inst => {
              const cls = instanceStateClass(inst);
              const running = inst.state === "running" && inst.exists !== false;
              return `<tr>
                <td>
                  <strong>${esc(inst.name || inst.id)}</strong>
                  ${isActiveInstance(inst.id)
                    ? ' <span class="pill ok">active</span>'
                    : ""}
                  <div class="small muted">${esc(inst.id)}${inst.note ? " — " + esc(inst.note) : ""}</div>
                </td>
                <td class="mono small c-path" title="${esc(inst.path)}">
                  ${esc(inst.path)}
                  ${inst.exists === false
                    ? ' <span class="pill danger">folder missing</span>' : ""}
                </td>
                <td class="tabular c-paper">${esc(inst.paper_version || "—")}
                  <span class="faint small">${inst.build ? "· build " + esc(inst.build) : ""}</span></td>
                <td class="c-tunnel">${esc(TUNNEL_LABELS[inst.tunnel] || inst.tunnel || "none")}</td>
                <td class="tabular c-bedrock">${inst.bedrock_port ? esc(inst.bedrock_port) : '<span class="faint">—</span>'}</td>
                <td>
                  <span class="dot ${esc(cls)}" aria-hidden="true" style="margin-right:6px"></span>
                  ${esc(instanceStateLabel(inst))}
                </td>
                <td class="small c-created">${esc(fmtDate(inst.created))}</td>
                <td class="actions actions-wrap">
                  ${isActiveInstance(inst.id) ? "" : `
                    <button class="btn btn-sm" type="button" data-activate="${esc(inst.id)}">Activate</button>`}
                  ${running
                    ? `<button class="btn btn-sm btn-danger" type="button" data-stop="${esc(inst.id)}">Stop</button>`
                    : `<button class="btn btn-sm btn-success" type="button" data-start="${esc(inst.id)}">Start</button>`}
                  ${inst.builtin
                    ? `<span class="small faint" title="The built-in server folder; rename and delete are refused">built-in</span>`
                    : `<button class="btn btn-sm btn-ghost" type="button" data-rename="${esc(inst.id)}">Rename</button>
                       <button class="btn btn-sm btn-danger" type="button" data-delete="${esc(inst.id)}">Delete</button>`}
                  <button class="btn btn-sm btn-ghost" type="button" data-clone="${esc(inst.id)}">Clone</button>
                  <button class="btn btn-sm btn-ghost" type="button" data-paper="${esc(inst.id)}">Paper…</button>
                </td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>`}

      ${rows.length === 0 ? `
        <div class="empty" style="padding:18px 0">
          No servers yet. Create one and it will show up here with its status,
          tunnel and controls.
        </div>
      ` : ""}
    </section>
  `;

  const createBtn = $("#createServerBtn");
  if (createBtn) createBtn.onclick = () => navigate("create");

  const wire = (attr, fn) => {
    $$("[" + attr + "]", container).forEach(btn => {
      // data-activate -> dataset.activate (every key here is a single word)
      btn.onclick = () => fn(btn.dataset[attr.slice("data-".length)]);
    });
  };
  wire("data-activate", activateInstance);
  wire("data-start", (id) => startInstance(id));
  wire("data-stop", (id) => stopInstance(id, false));
  wire("data-rename", renameInstance);
  wire("data-clone", cloneInstance);
  wire("data-paper", changePaperInstance);
  wire("data-delete", deleteInstance);
}

/* ==========================================================================
   11. SCREEN — DASHBOARD
   ========================================================================== */
async function renderDashboard(container) {
  // Fetch everything in parallel
  const [status, instances, logs, tunnels] = await Promise.all([
    apiGet("/api/status"),
    apiGet("/api/instances"),
    apiGet("/api/logs?instance=" + encodeURIComponent(state.instance) + "&lines=14"),
    apiGet("/api/tunnels")
  ]);

  if (instances && instances.instances) {
    state.instances = instances.instances;
    if (instances.active) state.instance = instances.active;
    state.instancesLoaded = true;
    renderInstanceNav();
  }
  state.status = status;
  state.tunnels = tunnels;

  if (!status) {
    container.innerHTML = offlineBanner() +
      '<div class="card"><div class="empty">' +
      "No server status available. The manager may still be starting up." +
      "</div></div>";
    return;
  }

  const srv = status.server || { state: "stopped" };
  const running = srv.state === "running";
  const tunnelInfo = (tunnels && tunnels.tunnels && tunnels.tunnels[0]) || null;
  const tunnelDisabled = tunnelInfo && tunnelInfo.disabled;
  const shareAddress = tunnelInfo && !tunnelDisabled
    ? tunnelInfo.host + ":" + tunnelInfo.port
    : null;

  const otherInstances = (state.instances || []).filter(i => i.id !== state.instance);

  container.innerHTML = offlineBanner() + `
    <div class="grid">

      <!-- ============ Server status ============ -->
      <section class="card" aria-labelledby="dash-status-h">
        <div class="card-h"><span id="dash-status-h">Server</span>
          <span class="pill ${running ? "ok" : "danger"}" id="statePill">
            ${running ? "Running" : esc((srv.state || "stopped").toUpperCase())}
          </span>
        </div>

        <div class="status-row" style="margin-bottom:12px">
          <span class="dot ${esc(srv.state)}" aria-hidden="true"></span>
          <span id="dashStateText">${running ? "Online" : "Offline"}</span>
          <span class="muted small tabular" id="dashUptime">
            ${running ? "· up " + fmtUptime(srv.uptime) : ""}
          </span>
        </div>

        <div style="display:flex;flex-direction:column;gap:8px">
          ${running ? `
            <button class="btn btn-danger btn-lg btn-block" id="stopBtn" type="button">
              ${ICONS.stop}<span>Stop server</span>
            </button>
            <button class="btn btn-block" id="killBtn" type="button">
              ${ICONS.kill}<span>Force kill</span>
            </button>
          ` : `
            <button class="btn btn-success btn-lg btn-block" id="startBtn" type="button">
              ${ICONS.play}<span>Start server</span>
            </button>
          `}
        </div>

        ${running ? `
          <dl class="kv" style="margin-top:14px">
            <dt>Memory</dt><dd class="tabular" id="dashRss">${fmtBytes(srv.rss)}</dd>
            <dt>PID</dt><dd class="tabular">${srv.pid == null ? "—" : esc(srv.pid)}</dd>
          </dl>
        ` : ""}
      </section>

      <!-- ============ Share address ============ -->
      <section class="card" aria-labelledby="dash-share-h">
        <div class="card-h"><span id="dash-share-h">Invite friends</span>
          ${tunnelInfo ? '<span class="pill ' + (tunnelDisabled ? "warn" : (shareAddress ? "ok" : "")) + '">' +
            (tunnelDisabled ? "disabled" : (shareAddress ? "tunnel up" : "no tunnel")) + "</span>" : ""}
        </div>

        ${shareAddress ? `
          <div class="address" id="shareAddress">
            <code>${esc(shareAddress)}</code>
            <button class="icon-btn" id="copyAddress" type="button" aria-label="Copy address">
              ${ICONS.copy}
            </button>
          </div>
          <p class="small muted" style="margin-top:9px">
            Share this with friends. No port forwarding needed — the tunnel
            handles it.
          </p>
        ` : tunnelInfo && tunnelDisabled ? `
          <div class="empty" style="padding:12px 0 6px">
            Tunnel is disabled${tunnelInfo.reason ? ": " + esc(tunnelInfo.reason) : "."}
          </div>
        ` : `
          <div class="empty" style="padding:12px 0 6px">
            No public tunnel for this instance.
          </div>
          <button class="btn btn-block" style="margin-top:8px" id="connectBtn" type="button">
            ${ICONS.link}<span>Connect playit.gg</span>
          </button>
          <p class="small faint" style="margin-top:7px">
            A tunnel gives this server a public address with no port forwarding.
          </p>
        `}

        ${tunnelInfo ? `
          <dl class="kv" style="margin-top:14px">
            <dt>Proto</dt><dd>${esc(tunnelInfo.proto || "TCP")}</dd>
            <dt>Destination</dt><dd class="mono">${esc(tunnelInfo.destination || "—")}</dd>
            <dt>Tunnel</dt>
            <dd>
              <span class="dot ${status.tunnel && status.tunnel.state === "running" ? "running" : "stopped"}"
                    aria-hidden="true" style="margin-right:6px"></span>
              ${status.tunnel ? esc(status.tunnel.state) : "unknown"}
            </dd>
          </dl>
        ` : ""}
      </section>

      <!-- ============ System ============ -->
      <section class="card" aria-labelledby="dash-sys-h">
        <div class="card-h"><span id="dash-sys-h">System</span></div>
        <dl class="kv">
          <dt>Instance</dt><dd>${esc(status.name || status.instance || "—")}</dd>
          <dt>Paper</dt><dd>${status.paper ? esc(status.paper.version) + " · build " + esc(status.paper.build) : "—"}</dd>
          <dt>Java</dt><dd class="mono">${esc(status.java || "—")}</dd>
          <dt>Disk free</dt><dd class="tabular" id="dashDisk">${status.disk ? fmtBytes(status.disk.free) : "—"}</dd>
          ${status.playitd ? `
            <dt>playitd</dt>
            <dd>
              <span class="dot ${status.playitd.state === "running" ? "running" : "stopped"}"
                    aria-hidden="true" style="margin-right:6px"></span>
              ${esc(status.playitd.state)}
            </dd>
          ` : ""}
        </dl>
      </section>

      <!-- ============ Log tail ============ -->
      <section class="card span-all" aria-labelledby="dash-log-h">
        <div class="card-h">
          <span id="dash-log-h">Recent log</span>
          <button class="btn btn-sm btn-ghost" id="openConsole" type="button">Open console</button>
        </div>
        <div class="log" id="dashLog">${logLinesHtml(logs && logs.lines)}</div>
      </section>

      <!-- ============ Other instances ============ -->
      ${otherInstances.length ? `
        <section class="card span-all" aria-labelledby="dash-inst-h">
          <div class="card-h"><span id="dash-inst-h">Other instances</span></div>
          <div class="tag-row">
            ${otherInstances.map(i => {
              const st = instanceStateClass(i);
              return '<button class="btn btn-sm" type="button" data-instance="' + esc(i.id) + '">' +
                '<span class="dot ' + esc(st) + '" aria-hidden="true"></span>' +
                esc(i.name || i.id) +
              "</button>";
            }).join("")}
          </div>
        </section>
      ` : ""}

    </div>
  `;

  const logEl = $("#dashLog");
  if (logEl) logEl.scrollTop = logEl.scrollHeight;

  /* ---- Event wiring ---- */
  const startBtn = $("#startBtn");
  if (startBtn) startBtn.onclick = startServer;

  const stopBtn = $("#stopBtn");
  if (stopBtn) stopBtn.onclick = () => stopServer(false);

  const killBtn = $("#killBtn");
  if (killBtn) killBtn.onclick = () => stopServer(true);

  const copyBtn = $("#copyAddress");
  if (copyBtn) {
    copyBtn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(shareAddress);
        toast("Address copied to clipboard", "ok");
      } catch (_) {
        // Clipboard API can fail on file:// — fall back to a prompt-free select
        const range = document.createRange();
        range.selectNodeContents($("#shareAddress code"));
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        toast("Address selected — press Ctrl/Cmd+C", "info", 6000);
      }
    };
  }

  const openConsole = $("#openConsole");
  if (openConsole) openConsole.onclick = () => navigate("console");

  const connectBtn = $("#connectBtn");
  if (connectBtn) connectBtn.onclick = () => navigate("connect");

  $$("[data-instance]", container).forEach(btn => {
    btn.onclick = () => switchInstance(btn.dataset.instance);
  });
}

/* Live-update the dashboard without re-rendering (avoids flicker) */
function updateDashboardLive(status) {
  const srv = status.server || {};
  const uptimeEl = $("#dashUptime");
  if (uptimeEl) {
    uptimeEl.textContent = srv.state === "running" ? "· up " + fmtUptime(srv.uptime) : "";
  }
  const rssEl = $("#dashRss");
  if (rssEl && srv.rss != null) rssEl.textContent = fmtBytes(srv.rss);

  const diskEl = $("#dashDisk");
  if (diskEl && status.disk) diskEl.textContent = fmtBytes(status.disk.free);
}

async function startServer() {
  return startInstance(state.instance);
}

async function stopServer(force) {
  return stopInstance(state.instance, force);
}

/* ==========================================================================
   12. SCREEN — CONSOLE
   ========================================================================== */
async function renderConsole(container) {
  const logs = await apiGet(
    "/api/logs?instance=" + encodeURIComponent(state.instance) + "&lines=200"
  );
  const lines = (logs && logs.lines) || [];
  state.logs = lines.slice();

  container.innerHTML = offlineBanner() + `
    <section class="card" aria-labelledby="console-h">
      <div class="card-h">
        <span id="console-h">Console — ${esc(state.instance)}</span>
        <span class="row" style="gap:6px">
          <span class="faint small tabular" id="consoleCount">${lines.length} lines</span>
          <button class="btn btn-sm btn-ghost" id="clearView" type="button">Clear view</button>
        </span>
      </div>

      <div class="log tall" id="consoleLog" role="log" aria-live="polite"
           aria-relevant="additions">${logLinesHtml(lines)}</div>

      <form class="row" id="consoleForm" style="margin-top:12px;gap:8px" autocomplete="off">
        <label class="sr-only" for="consoleInput" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">Command</label>
        <input class="input" id="consoleInput" type="text"
               placeholder="Type a command and press Enter  (↑ / ↓ for history)"
               spellcheck="false" autocapitalize="off" autocorrect="off"
               style="flex:1;font-family:var(--mono);font-size:12.5px">
        <button class="btn btn-primary" type="submit" id="consoleSend">
          ${ICONS.send}<span>Send</span>
        </button>
      </form>
      <p class="small faint" style="margin-top:7px">
        Commands go straight to the server's stdin. Try
        <code class="mono">list</code>, <code class="mono">say hi</code>,
        or <code class="mono">whitelist add Steve</code>.
      </p>
    </section>
  `;

  const logEl = $("#consoleLog");
  const input = $("#consoleInput");
  const form = $("#consoleForm");

  logEl.scrollTop = logEl.scrollHeight;

  state.consoleHistory = state.consoleHistory || [];
  state.consoleHistoryIndex = -1;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const cmd = input.value.trim();
    if (!cmd) return;

    // History (most recent first)
    if (state.consoleHistory[0] !== cmd) state.consoleHistory.unshift(cmd);
    if (state.consoleHistory.length > 100) state.consoleHistory.pop();
    state.consoleHistoryIndex = -1;
    input.value = "";

    // Optimistic echo so the UI feels instant
    appendConsoleLine("[console] > " + cmd, "pending");

    const res = await apiPost("/api/console", {
      command: cmd,
      instance: state.instance
    });

    if (res && res.ok) {
      // Real output arrives over SSE; nothing more to do.
    } else {
      appendConsoleLine("[console] ! " + ((res && res.error) || "command failed"), "error");
      toast((res && res.error) || "Command failed", "error");
    }
  });

  input.addEventListener("keydown", (e) => {
    const hist = state.consoleHistory;
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (hist.length === 0) return;
      state.consoleHistoryIndex = Math.min(
        hist.length - 1,
        (state.consoleHistoryIndex < 0 ? -1 : state.consoleHistoryIndex) + 1
      );
      input.value = hist[state.consoleHistoryIndex] || "";
      // Put the caret at the end
      requestAnimationFrame(() => {
        input.selectionStart = input.selectionEnd = input.value.length;
      });
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (state.consoleHistoryIndex <= 0) {
        state.consoleHistoryIndex = -1;
        input.value = "";
        return;
      }
      state.consoleHistoryIndex--;
      input.value = hist[state.consoleHistoryIndex] || "";
      requestAnimationFrame(() => {
        input.selectionStart = input.selectionEnd = input.value.length;
      });
    }
  });

  const clearBtn = $("#clearView");
  if (clearBtn) {
    clearBtn.onclick = () => {
      // Only clears the local view — the server keeps its own log file.
      const el = $("#consoleLog");
      el.innerHTML = '<div class="log-empty">View cleared. New output will appear here.</div>';
      updateConsoleCount();
      toast("Console view cleared (server log untouched)", "info");
    };
  }

  // Focus the input so the user can start typing immediately
  input.focus();
}

function appendConsoleLine(text, kind) {
  const el = $("#consoleLog");
  if (!el) return;
  const empty = el.querySelector(".log-empty");
  if (empty) empty.remove();

  const stick = isScrolledToBottom(el);
  const div = document.createElement("div");
  div.className = "log-line" + (kind ? " " + kind : "");
  div.textContent = text;
  el.appendChild(div);

  // Keep the DOM from growing without bound
  while (el.children.length > 1200) el.removeChild(el.firstChild);

  if (stick) el.scrollTop = el.scrollHeight;
  updateConsoleCount();
}

function updateConsoleCount() {
  const el = $("#consoleLog");
  const counter = $("#consoleCount");
  if (el && counter) counter.textContent = el.children.length + " lines";
}

/* ==========================================================================
   13. SCREEN — PLAYERS
   ========================================================================== */
async function renderPlayers(container) {
  const players = await apiGet(
    "/api/players?instance=" + encodeURIComponent(state.instance)
  );

  if (!players) {
    container.innerHTML = offlineBanner() +
      '<div class="card"><div class="empty">' +
      "Could not load player data. Is the server running?" +
      "</div></div>";
    return;
  }

  state.players = players;

  const online = players.online || [];
  const whitelist = players.whitelist || [];
  const ops = players.ops || [];
  // TODO: GET /api/players does not return bans in the current contract.
  // Assumed shape: [ { name, reason, created } ]
  const bans = players.bans || [];
  const recent = (players.recent || []).filter(n => !online.includes(n));

  const whitelistEnabled = players.whitelist_enabled !== false;

  container.innerHTML = offlineBanner() + `
    <div class="grid">

      <!-- ===== Online ===== -->
      <section class="card" aria-labelledby="online-h">
        <div class="card-h">
          <span id="online-h">Online now</span>
          <span class="pill ${online.length ? "ok" : ""}">
            ${online.length} / ${esc(players.max_players == null ? "?" : players.max_players)}
          </span>
        </div>

        ${online.length === 0 ? `
          <div class="empty">Nobody is online right now.</div>
        ` : `
          <div class="tag-row">
            ${online.map(name => `
              <span class="tag">
                <span class="name">${esc(name)}</span>
                <button type="button" data-kick="${esc(name)}"
                        aria-label="Kick ${esc(name)}" title="Kick">${ICONS.x}</button>
              </span>
            `).join("")}
          </div>
        `}

        <div class="divider"></div>

        <form class="row" id="kickForm" style="gap:6px" autocomplete="off">
          <input class="input" id="kickName" type="text" placeholder="Player name"
                 style="flex:1" spellcheck="false">
          <button class="btn btn-sm" type="submit">Kick</button>
        </form>
        <p class="small faint" style="margin-top:6px">
          Kicking disconnects a player. They can rejoin unless you ban them.
        </p>
      </section>

      <!-- ===== Whitelist ===== -->
      <section class="card" aria-labelledby="wl-h">
        <div class="card-h">
          <span id="wl-h">Whitelist</span>
          <span class="pill ${whitelistEnabled ? "ok" : "warn"}">
            ${whitelistEnabled ? "enforced" : "OFF"}
          </span>
        </div>

        ${!whitelistEnabled ? `
          <p class="small" style="color:var(--warn);margin-bottom:10px">
            ${ICONS.warn.replace("<svg", '<svg style="width:13px;height:13px;vertical-align:-2px;margin-right:4px"')}
            Anyone can join. Turn the whitelist on from the console with
            <code class="mono">whitelist on</code>.
          </p>
        ` : ""}

        ${whitelist.length === 0 ? `
          <div class="empty">The whitelist is empty.</div>
        ` : `
          <div class="tag-row">
            ${whitelist.map(name => `
              <span class="tag">
                <span class="name">${esc(name)}</span>
                <button type="button" data-wl-remove="${esc(name)}"
                        aria-label="Remove ${esc(name)} from whitelist"
                        title="Remove from whitelist">${ICONS.x}</button>
              </span>
            `).join("")}
          </div>
        `}

        <form class="row" id="wlForm" style="gap:6px;margin-top:12px" autocomplete="off">
          <input class="input" id="wlName" type="text" placeholder="Add player by name"
                 style="flex:1" spellcheck="false">
          <button class="btn btn-primary btn-sm" type="submit">Add</button>
        </form>
      </section>

      <!-- ===== Ops ===== -->
      <section class="card" aria-labelledby="ops-h">
        <div class="card-h"><span id="ops-h">Operators</span>
          <span class="pill">${ops.length}</span>
        </div>

        ${ops.length === 0 ? `
          <div class="empty">No operators. Nobody can run admin commands in game.</div>
        ` : `
          <div class="tag-row">
            ${ops.map(name => `
              <span class="tag">
                <span class="name">${esc(name)}</span>
                <button type="button" data-op-remove="${esc(name)}"
                        aria-label="De-op ${esc(name)}" title="Remove operator">${ICONS.x}</button>
              </span>
            `).join("")}
          </div>
        `}

        <form class="row" id="opForm" style="gap:6px;margin-top:12px" autocomplete="off">
          <input class="input" id="opName" type="text" placeholder="Make player an operator"
                 style="flex:1" spellcheck="false">
          <button class="btn btn-primary btn-sm" type="submit">Op</button>
        </form>
        <p class="small faint" style="margin-top:6px">
          Operators can run any command in game, including <code class="mono">/ban</code>.
        </p>
      </section>

      <!-- ===== Bans ===== -->
      <section class="card" aria-labelledby="bans-h">
        <div class="card-h"><span id="bans-h">Bans</span>
          <span class="pill ${bans.length ? "danger" : ""}">${bans.length}</span>
        </div>

        ${bans.length === 0 ? `
          <div class="empty">No banned players.</div>
        ` : `
          <div class="tag-row">
            ${bans.map(b => `
              <span class="tag" title="${esc(b.reason || "")}">
                <span class="name">${esc(typeof b === "string" ? b : b.name)}</span>
              </span>
            `).join("")}
          </div>
        `}

        <form class="row" id="banForm" style="gap:6px;margin-top:12px" autocomplete="off">
          <input class="input" id="banName" type="text" placeholder="Ban player by name"
                 style="flex:1" spellcheck="false">
          <input class="input" id="banReason" type="text" placeholder="Reason (optional)"
                 style="flex:1" spellcheck="false">
          <button class="btn btn-danger btn-sm" type="submit">Ban</button>
        </form>
        <p class="small faint" style="margin-top:6px">
          Banning removes the player from the whitelist and blocks them from rejoining.
        </p>
      </section>

      <!-- ===== Recent ===== -->
      <section class="card span-all" aria-labelledby="recent-h">
        <div class="card-h"><span id="recent-h">Recently seen</span></div>
        ${recent.length === 0 ? `
          <div class="empty">Nobody else has played here yet.</div>
        ` : `
          <div class="tag-row">
            ${recent.map(name => `
              <span class="tag">
                <span class="name">${esc(name)}</span>
                <button type="button" data-wl-add="${esc(name)}"
                        aria-label="Add ${esc(name)} to whitelist"
                        title="Add to whitelist" style="color:var(--ok)">
                  ${ICONS.check}
                </button>
              </span>
            `).join("")}
          </div>
        `}
      </section>

    </div>
  `;

  /* ---------- Wiring ---------- */

  async function withRefresh(promise, okMsg) {
    const res = await promise;
    if (res && res.ok) {
      if (okMsg) toast(okMsg, "ok");
      renderScreen();
    } else {
      toast((res && res.error) || "Action failed", "error");
    }
  }

  // Kick from a tag
  $$("[data-kick]", container).forEach(btn => {
    btn.onclick = () => kickPlayer(btn.dataset.kick);
  });

  // Kick form
  const kickForm = $("#kickForm");
  if (kickForm) {
    kickForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = $("#kickName").value.trim();
      if (!name) return;
      kickPlayer(name);
    });
  }

  // Whitelist add form
  const wlForm = $("#wlForm");
  if (wlForm) {
    wlForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = $("#wlName").value.trim();
      if (!name) return;
      withRefresh(
        apiPost("/api/players/whitelist/add", { instance: state.instance, name }),
        name + " added to whitelist"
      );
    });
  }

  // Whitelist remove buttons
  $$("[data-wl-remove]", container).forEach(btn => {
    btn.onclick = async () => {
      const name = btn.dataset.wlRemove;
      const ok = await confirmDialog(
        "Remove from whitelist",
        "<p><strong>" + esc(name) + "</strong> will no longer be allowed to join " +
        "while the whitelist is on. They are not banned.</p>",
        "Remove"
      );
      if (!ok) return;
      withRefresh(
        apiPost("/api/players/whitelist/remove", { instance: state.instance, name }),
        name + " removed from whitelist"
      );
    };
  });

  // Quick "add to whitelist" from the recent list
  $$("[data-wl-add]", container).forEach(btn => {
    btn.onclick = () => {
      const name = btn.dataset.wlAdd;
      withRefresh(
        apiPost("/api/players/whitelist/add", { instance: state.instance, name }),
        name + " added to whitelist"
      );
    };
  });

  // Op add form
  const opForm = $("#opForm");
  if (opForm) {
    opForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const name = $("#opName").value.trim();
      if (!name) return;
      withRefresh(
        apiPost("/api/players/op/add", { instance: state.instance, name }),
        name + " is now an operator"
      );
    });
  }

  // De-op buttons
  $$("[data-op-remove]", container).forEach(btn => {
    btn.onclick = async () => {
      const name = btn.dataset.opRemove;
      const ok = await confirmDialog(
        "Remove operator",
        "<p><strong>" + esc(name) + "</strong> will lose access to admin commands " +
        "in game.</p>",
        "De-op"
      );
      if (!ok) return;
      withRefresh(
        apiPost("/api/players/op/remove", { instance: state.instance, name }),
        name + " is no longer an operator"
      );
    };
  });

  // Ban form
  const banForm = $("#banForm");
  if (banForm) {
    banForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = $("#banName").value.trim();
      const reason = $("#banReason").value.trim();
      if (!name) return;

      const ok = await confirmDialog(
        "Ban player",
        "<p><strong>" + esc(name) + "</strong> will be kicked if online, removed " +
        "from the whitelist, and blocked from rejoining.</p>" +
        (reason ? "<p>Reason: <strong>" + esc(reason) + "</strong></p>" : ""),
        "Ban player"
      );
      if (!ok) return;

      withRefresh(
        apiPost("/api/players/ban", { instance: state.instance, name, reason }),
        name + " banned"
      );
    });
  }
}

async function kickPlayer(name) {
  const reason = window.prompt("Reason for kicking " + name + "? (optional)", "");
  if (reason === null) return; // user cancelled

  const ok = await confirmDialog(
    "Kick player",
    "<p><strong>" + esc(name) + "</strong> will be disconnected immediately. " +
    "They can rejoin unless you ban them.</p>" +
    (reason ? "<p>Reason: <strong>" + esc(reason) + "</strong></p>" : ""),
    "Kick"
  );
  if (!ok) return;

  const res = await apiPost("/api/players/kick", {
    instance: state.instance, name, reason: reason || ""
  });
  if (res && res.ok) {
    toast(name + " kicked", "ok");
    renderScreen();
  } else {
    toast((res && res.error) || "Could not kick " + name, "error");
  }
}

/* ==========================================================================
   14. SCREEN — BACKUPS
   ========================================================================== */
async function renderBackups(container) {
  const data = await apiGet(
    "/api/backups?instance=" + encodeURIComponent(state.instance)
  );
  const backups = (data && data.backups) || [];
  state.backups = backups;

  const totalSize = backups.reduce((sum, b) => sum + (b.size || 0), 0);

  container.innerHTML = offlineBanner() + `
    <section class="card" aria-labelledby="backups-h">
      <div class="card-h">
        <span id="backups-h">Backups — ${esc(state.instance)}</span>
        <span class="row" style="gap:6px">
          <span class="faint small tabular">
            ${pluralise(backups.length, "backup", "backups")} · ${fmtBytes(totalSize)}
          </span>
          <button class="btn btn-primary btn-sm" id="createBackup" type="button">
            ${ICONS.plus}<span>Create backup</span>
          </button>
        </span>
      </div>

      ${backups.length === 0 ? `
        <div class="empty">
          No backups yet. Create one before you install plugins or update Paper —
          it makes rolling back painless.
        </div>
      ` : `
        <div class="table-wrap">
          <table class="backups-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col" class="c-size">Size</th>
                <th scope="col" class="c-created">Created</th>
                <th scope="col" style="text-align:right">Actions</th>
              </tr>
            </thead>
            <tbody>
              ${backups.map(b => `
                <tr>
                  <td class="mono">${esc(b.name)}</td>
                  <td class="tabular c-size">${fmtBytes(b.size)}</td>
                  <td class="c-created">
                    ${esc(fmtDate(b.stamp))}
                    <span class="faint small"> · ${esc(fmtRel(b.stamp))}</span>
                  </td>
                  <td class="actions">
                    <button class="btn btn-sm" type="button"
                            data-restore="${esc(b.name)}">Restore</button>
                    <button class="btn btn-sm btn-danger" type="button"
                            data-delete="${esc(b.name)}">Delete</button>
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `}
    </section>
  `;

  const createBtn = $("#createBackup");
  if (createBtn) {
    createBtn.onclick = async () => {
      createBtn.setAttribute("aria-disabled", "true");
      const res = await apiPost("/api/backups/create", { instance: state.instance });
      createBtn.removeAttribute("aria-disabled");
      if (res && res.ok) {
        toast("Backup started — watch the progress bar", "info");
        setTimeout(renderScreen, 600);
      } else {
        toast((res && res.error) || "Could not create a backup", "error");
      }
    };
  }

  $$("[data-restore]", container).forEach(btn => {
    btn.onclick = async () => {
      const name = btn.dataset.restore;
      const ok = await confirmDialog(
        "Restore backup",
        "<p>This will <strong>overwrite the current world</strong> with the " +
        "contents of <code>" + esc(name) + "</code>.</p>" +
        "<p>Anything built or changed since that backup was taken will be lost. " +
        "The server must be stopped first.</p>",
        "Restore backup"
      );
      if (!ok) return;

      const res = await apiPost("/api/backups/restore", {
        name, instance: state.instance
      });
      if (res && res.ok) {
        toast("Restore started — watch the progress bar", "info");
        setTimeout(renderScreen, 600);
      } else {
        toast((res && res.error) || "Could not restore the backup", "error");
      }
    };
  });

  $$("[data-delete]", container).forEach(btn => {
    btn.onclick = async () => {
      const name = btn.dataset.delete;
      const ok = await confirmDialog(
        "Delete backup",
        "<p><code>" + esc(name) + "</code> will be permanently deleted.</p>" +
        "<p>This cannot be undone.</p>",
        "Delete permanently"
      );
      if (!ok) return;

      const res = await apiPost("/api/backups/delete", { name });
      if (res && res.ok) {
        toast("Backup deleted", "ok");
        renderScreen();
      } else {
        toast((res && res.error) || "Could not delete the backup", "error");
      }
    };
  });
}

/* ==========================================================================
   15. SCREEN — CREATE SERVER (wizard)
   ========================================================================== */
const PLUGIN_CATALOGUE = [
  { id: "essentialsx", name: "EssentialsX", desc: "Homes, warps, kits, economy basics" },
  { id: "luckperms",   name: "LuckPerms",   desc: "Ranks and permissions" },
  { id: "worldedit",   name: "WorldEdit",   desc: "In-game building and terraforming" },
  { id: "vault",       name: "Vault",       desc: "Bridge for economy and permission plugins" },
  { id: "viaversion",  name: "ViaVersion",  desc: "Let newer clients join an older server" },
  { id: "chunky",      name: "Chunky",      desc: "Pre-generate the world to avoid lag" },
  { id: "coreprotect", name: "CoreProtect", desc: "Log and roll back block changes" },
  { id: "geyser",      name: "Geyser",      desc: "Bedrock / phone / console support" }
];

const PAPER_VERSIONS = [
  { value: "1.21.4", build: 129, label: "1.21.4 — latest" },
  { value: "1.21.1", build: 133, label: "1.21.1" },
  { value: "1.20.6", build: 151, label: "1.20.6" },
  { value: "1.20.4", build: 497, label: "1.20.4" },
  { value: "1.19.4", build: 550, label: "1.19.4 — legacy" }
];

const MEMORY_PRESETS = ["1G", "2G", "4G", "6G", "8G", "12G", "16G"];

const WIZARD_STEPS = [
  { id: "basics",   label: "Basics" },
  { id: "location", label: "Location" },
  { id: "software", label: "Software" },
  { id: "gameplay", label: "Gameplay" },
  { id: "network",  label: "Network & plugins" },
  { id: "review",   label: "Review" }
];

function freshWizard() {
  return {
    step: 0,
    id: "",
    name: "",
    path: "",
    version: "1.21.4",
    build: 129,
    memory: "4G",
    gameplay: {
      online_mode: false,
      whitelist: true,
      pvp: true,
      hardcore: false,
      command_blocks: false,
      allow_flight: false,
      spawn_protection: true
    },
    tunnel: "playit",
    bedrock: false,
    plugins: []
  };
}

function renderCreate(container) {
  if (!state.wizard) state.wizard = freshWizard();
  const w = state.wizard;

  // Guard against an out-of-range step (e.g. after a reset)
  if (w.step < 0) w.step = 0;
  if (w.step >= WIZARD_STEPS.length) w.step = WIZARD_STEPS.length - 1;

  container.innerHTML = offlineBanner() + `
    <section class="card" aria-labelledby="create-h">
      <div class="card-h"><span id="create-h">Create a new server</span></div>

      <div class="steps" role="tablist" aria-label="Wizard steps">
        ${WIZARD_STEPS.map((s, i) => `
          <button class="step ${i === w.step ? "active" : ""} ${i < w.step ? "done" : ""}"
                  type="button" role="tab"
                  aria-selected="${i === w.step}"
                  data-step="${i}">
            ${i < w.step ? "✓ " : ""}${esc(s.label)}
          </button>
        `).join("")}
      </div>

      <div id="wizardBody"></div>

      <div class="wizard-nav">
        <button class="btn" type="button" id="wizBack"
                ${w.step === 0 ? "disabled" : ""}>
          ${ICONS.chevronL}<span>Back</span>
        </button>
        <div class="right">
          <button class="btn btn-ghost" type="button" id="wizCancel">Cancel</button>
          <button class="btn btn-primary" type="button" id="wizNext">
            ${w.step === WIZARD_STEPS.length - 1
              ? "Create server"
              : 'Next<span style="opacity:.7">' + " " + esc(WIZARD_STEPS[w.step + 1].label) + "</span>"}
            ${ICONS.chevronR}
          </button>
        </div>
      </div>
    </section>
  `;

  renderWizardStep();
  wireWizard();
}

function renderWizardStep() {
  const w = state.wizard;
  const body = $("#wizardBody");
  if (!body) return;
  const stepId = WIZARD_STEPS[w.step].id;

  switch (stepId) {
    case "basics":
      body.innerHTML = `
        <div class="field">
          <label class="field-label" for="wizId">Server id</label>
          <input class="input" id="wizId" type="text" spellcheck="false"
                 autocapitalize="off" autocorrect="off"
                 placeholder="survival" value="${esc(w.id)}">
          <div class="field-hint" id="wizIdHint">
            Short, lowercase, no spaces — used for the folder name and URLs.
            Letters, numbers, dashes and underscores only.
          </div>
        </div>
        <div class="field">
          <label class="field-label" for="wizName">Display name</label>
          <input class="input" id="wizName" type="text"
                 placeholder="Survival world" value="${esc(w.name)}">
          <div class="field-hint">What you'll see in the sidebar.</div>
        </div>
      `;
      break;

    case "location":
      body.innerHTML = `
        <div class="field">
          <label class="field-label" for="wizPath">Install path</label>
          <input class="input" id="wizPath" type="text" spellcheck="false"
                 autocapitalize="off" autocorrect="off"
                 placeholder="/home/you/minecraft/survival" value="${esc(w.path)}">
          <div class="field-hint" id="wizPathHint">
            Absolute path where the server, world and plugins will live.
            On Windows use something like <code class="mono">C:\\mc\\survival</code>.
          </div>
        </div>
      `;
      break;

    case "software":
      body.innerHTML = `
        <div class="field">
          <label class="field-label" for="wizVersion">Paper version</label>
          <select class="input" id="wizVersion">
            ${PAPER_VERSIONS.map(v =>
              '<option value="' + esc(v.value) + '"' +
              (v.value === w.version ? " selected" : "") + ">" +
              esc(v.label) + "</option>"
            ).join("")}
          </select>
          <div class="field-hint">
            Paper is a fast, plugin-friendly Minecraft server. Plugins usually
            support the current version and one or two behind it.
          </div>
        </div>
        <div class="field">
          <label class="field-label" for="wizMemory">Memory</label>
          <select class="input" id="wizMemory">
            ${MEMORY_PRESETS.map(m =>
              '<option value="' + m + '"' + (m === w.memory ? " selected" : "") + ">" +
              m.replace("G", " GB") +
              (m === "4G" ? " — good default" : "") +
              "</option>"
            ).join("")}
          </select>
          <div class="field-hint">
            How much RAM the Java process may use. 4 GB is plenty for a handful of
            friends; go higher if you plan to install lots of plugins or run
            many players.
          </div>
        </div>
      `;
      break;

    case "gameplay": {
      const g = w.gameplay;
      const toggles = [
        { key: "online_mode",        title: "Verify accounts with Mojang",
          desc: "Turn off to let cracked / offline clients join. Reduces security." },
        { key: "whitelist",          title: "Whitelist only",
          desc: "Only players you approve can join." },
        { key: "pvp",                title: "Player vs player",
          desc: "Allow players to damage each other." },
        { key: "hardcore",           title: "Hardcore mode",
          desc: "Players are banned on death. Difficult to undo." },
        { key: "command_blocks",     title: "Command blocks",
          desc: "Required for many adventure maps and datapacks." },
        { key: "allow_flight",       title: "Allow flight",
          desc: "Let players fly in survival. Often used for building." },
        { key: "spawn_protection",   title: "Spawn protection",
          desc: "Stop players from breaking blocks near the world spawn." }
      ];
      body.innerHTML = `
        <div class="stack">
          ${toggles.map(t => `
            <label class="check">
              <input type="checkbox" data-toggle="${t.key}" ${g[t.key] ? "checked" : ""}>
              <span class="check-body">
                <span class="check-title">${esc(t.title)}</span>
                <span class="check-desc">${esc(t.desc)}</span>
              </span>
            </label>
          `).join("")}
        </div>
      `;
      break;
    }

    case "network":
      body.innerHTML = `
        <div class="field">
          <label class="field-label" for="wizTunnel">Public tunnel</label>
          <select class="input" id="wizTunnel">
            <option value="playit" ${w.tunnel === "playit" ? "selected" : ""}>
              playit.gg — recommended, works everywhere
            </option>
            <option value="bore" ${w.tunnel === "bore" ? "selected" : ""}>
              bore.pub — simpler, no account
            </option>
            <option value="none" ${w.tunnel === "none" ? "selected" : ""}>
              None — LAN / manual port forwarding only
            </option>
          </select>
          <div class="field-hint">
            A tunnel gives you a public address without touching your router.
          </div>
        </div>

        <div class="field">
          <label class="check">
            <input type="checkbox" id="wizBedrock" ${w.bedrock ? "checked" : ""}>
            <span class="check-body">
              <span class="check-title">Enable Bedrock / console support</span>
              <span class="check-desc">
                Installs Geyser + Floodgate so phones, tablets and consoles
                (running Bedrock Edition) can join the same world as Java players.
              </span>
            </span>
          </label>
        </div>

        <div class="field">
          <span class="field-label">Plugins</span>
          <div class="stack">
            ${PLUGIN_CATALOGUE.map(p => `
              <label class="check">
                <input type="checkbox" data-plugin="${p.id}"
                       ${w.plugins.includes(p.id) ? "checked" : ""}
                       ${p.id === "geyser" && w.bedrock ? "checked disabled" : ""}>
                <span class="check-body">
                  <span class="check-title">${esc(p.name)}</span>
                  <span class="check-desc">${esc(p.desc)}</span>
                </span>
              </label>
            `).join("")}
          </div>
          <div class="field-hint">
            You can add or remove plugins later — nothing here is permanent.
          </div>
        </div>
      `;
      break;

    case "review": {
      const versionLabel = (PAPER_VERSIONS.find(v => v.value === w.version) || {}).label || w.version;
      const tunnelLabel = { playit: "playit.gg", bore: "bore.pub", none: "None" }[w.tunnel] || w.tunnel;
      const pluginNames = w.plugins
        .map(id => (PLUGIN_CATALOGUE.find(p => p.id === id) || {}).name || id);

      const g = w.gameplay;
      const onNames = Object.keys(g).filter(k => g[k]);

      body.innerHTML = `
        <h3 style="margin-bottom:12px">Everything look right?</h3>
        <dl class="review-list">
          <div class="review-item">
            <dt>Id</dt><dd class="mono">${esc(w.id || "—")}</dd>
          </div>
          <div class="review-item">
            <dt>Name</dt><dd>${esc(w.name || "—")}</dd>
          </div>
          <div class="review-item">
            <dt>Install path</dt><dd class="mono">${esc(w.path || "—")}</dd>
          </div>
          <div class="review-item">
            <dt>Paper</dt><dd>${esc(versionLabel)} (build ${esc(w.build)})</dd>
          </div>
          <div class="review-item">
            <dt>Memory</dt><dd>${esc(w.memory.replace("G", " GB"))}</dd>
          </div>
          <div class="review-item">
            <dt>Tunnel</dt><dd>${esc(tunnelLabel)}</dd>
          </div>
          <div class="review-item">
            <dt>Bedrock</dt><dd>${w.bedrock ? "Enabled (Geyser)" : "Not enabled"}</dd>
          </div>
          <div class="review-item">
            <dt>Gameplay</dt>
            <dd>${onNames.length
                  ? esc(onNames.map(k => k.replace(/_/g, " ")).join(", "))
                  : "<span class=\"faint\">Defaults</span>"}</dd>
          </div>
          <div class="review-item">
            <dt>Plugins</dt>
            <dd>${pluginNames.length
                  ? esc(pluginNames.join(", "))
                  : "<span class=\"faint\">None</span>"}</dd>
          </div>
        </dl>
        <p class="small muted" style="margin-top:14px">
          The server files will be downloaded into the install path above. This can
          take a minute on a slow connection — you can keep using the rest of the
          app while it runs.
        </p>
      `;
      break;
    }
  }
}

function wireWizard() {
  const w = state.wizard;

  // Step tabs (allow jumping back to any completed step)
  $$(".step").forEach(btn => {
    btn.onclick = () => {
      const target = parseInt(btn.dataset.step, 10);
      if (target <= w.step) {
        captureWizardStep();
        w.step = target;
        renderCreate($("#content"));
      }
    };
  });

  const backBtn = $("#wizBack");
  if (backBtn) {
    backBtn.onclick = () => {
      captureWizardStep();
      w.step = Math.max(0, w.step - 1);
      renderCreate($("#content"));
    };
  }

  const nextBtn = $("#wizNext");
  if (nextBtn) {
    nextBtn.onclick = async () => {
      if (!captureWizardStep()) return;
      if (w.step === WIZARD_STEPS.length - 1) {
        await submitWizard();
        return;
      }
      w.step++;
      renderCreate($("#content"));
    };
  }

  const cancelBtn = $("#wizCancel");
  if (cancelBtn) {
    cancelBtn.onclick = async () => {
      const anyProgress = w.id || w.name || w.path || w.plugins.length;
      if (anyProgress) {
        const ok = await confirmDialog(
          "Discard this server?",
          "<p>The details you've entered will be lost.</p>",
          "Discard"
        );
        if (!ok) return;
      }
      state.wizard = freshWizard();
      navigate("dashboard");
    };
  }

  // Live validation for the id and path fields
  const idInput = $("#wizId");
  if (idInput) {
    idInput.addEventListener("input", () => validateWizardId());
    validateWizardId();
  }
  const pathInput = $("#wizPath");
  if (pathInput) {
    pathInput.addEventListener("input", () => validateWizardPath());
    validateWizardPath();
  }

  // Bedrock checkbox keeps the Geyser plugin in sync
  const bedrock = $("#wizBedrock");
  if (bedrock) {
    bedrock.addEventListener("change", () => {
      w.bedrock = bedrock.checked;
      const geyserBox = document.querySelector('[data-plugin="geyser"]');
      if (geyserBox) {
        if (w.bedrock) {
          geyserBox.checked = true;
          geyserBox.disabled = true;
          if (!w.plugins.includes("geyser")) w.plugins.push("geyser");
        } else {
          geyserBox.disabled = false;
        }
      }
    });
  }

  // Plugin checkboxes
  $$("[data-plugin]").forEach(cb => {
    cb.addEventListener("change", () => {
      const id = cb.dataset.plugin;
      if (cb.checked) {
        if (!w.plugins.includes(id)) w.plugins.push(id);
      } else {
        w.plugins = w.plugins.filter(p => p !== id);
      }
    });
  });
}

/** Copy the current step's form values back into state.wizard. Returns false on validation failure. */
function captureWizardStep() {
  const w = state.wizard;
  const stepId = WIZARD_STEPS[w.step].id;

  switch (stepId) {
    case "basics": {
      const idEl = $("#wizId");
      const nameEl = $("#wizName");
      if (idEl) w.id = idEl.value.trim();
      if (nameEl) w.name = nameEl.value.trim();
      if (!validateWizardId(true)) return false;
      if (!w.name) {
        toast("Give the server a display name", "error");
        nameEl && nameEl.focus();
        return false;
      }
      return true;
    }

    case "location": {
      const el = $("#wizPath");
      if (el) w.path = el.value.trim();
      if (!validateWizardPath(true)) return false;
      return true;
    }

    case "software": {
      const v = $("#wizVersion");
      const m = $("#wizMemory");
      if (v) {
        w.version = v.value;
        const found = PAPER_VERSIONS.find(p => p.value === v.value);
        w.build = found ? found.build : 0;
      }
      if (m) w.memory = m.value;
      return true;
    }

    case "gameplay": {
      $$("[data-toggle]").forEach(cb => {
        w.gameplay[cb.dataset.toggle] = cb.checked;
      });
      return true;
    }

    case "network": {
      const t = $("#wizTunnel");
      const b = $("#wizBedrock");
      if (t) w.tunnel = t.value;
      if (b) w.bedrock = b.checked;
      // Plugin checkboxes are kept in sync by their own listeners, but read once
      // more here to be safe.
      const plugins = [];
      $$("[data-plugin]").forEach(cb => {
        if (cb.checked) plugins.push(cb.dataset.plugin);
      });
      w.plugins = plugins;
      return true;
    }

    case "review":
      return true;
  }
  return true;
}

function validateWizardId(commit) {
  const el = $("#wizId");
  const hint = $("#wizIdHint");
  if (!el || !hint) return true;

  const value = el.value.trim();
  const valid = /^[a-z0-9][a-z0-9_-]*$/.test(value);

  if (!value) {
    el.classList.toggle("invalid", !!commit);
    hint.className = "field-hint" + (commit ? " err" : "");
    hint.textContent = commit
      ? "An id is required."
      : "Short, lowercase, no spaces — used for the folder name and URLs. " +
        "Letters, numbers, dashes and underscores only.";
    return !commit;
  }

  if (!valid) {
    el.classList.add("invalid");
    hint.className = "field-hint err";
    hint.textContent =
      "Ids must start with a letter or number and contain only lowercase " +
      "letters, numbers, dashes or underscores.";
    return false;
  }

  const exists = (state.instances || []).some(i => i.id === value);
  if (exists) {
    el.classList.add("invalid");
    hint.className = "field-hint err";
    hint.textContent = "An instance with that id already exists.";
    return false;
  }

  el.classList.remove("invalid");
  hint.className = "field-hint ok";
  hint.textContent = "Looks good.";
  return true;
}

function validateWizardPath(commit) {
  const el = $("#wizPath");
  const hint = $("#wizPathHint");
  if (!el || !hint) return true;

  const value = el.value.trim();
  if (!value) {
    el.classList.toggle("invalid", !!commit);
    hint.className = "field-hint" + (commit ? " err" : "");
    hint.textContent = commit
      ? "An install path is required."
      : "Absolute path where the server, world and plugins will live. " +
        "On Windows use something like C:\\mc\\survival.";
    return !commit;
  }

  // Accept unix absolute paths, home-relative paths, or Windows drive paths.
  const isUnix = value.startsWith("/");
  const isHome = value.startsWith("~/");
  const isWin = /^[A-Za-z]:[\\/]/.test(value);

  if (!isUnix && !isHome && !isWin) {
    el.classList.add("invalid");
    hint.className = "field-hint err";
    hint.textContent =
      "That doesn't look absolute. Start with / on macOS or Linux, " +
      "~/ for your home folder, or a drive letter like C:\\ on Windows.";
    return false;
  }

  if (/\s{2,}/.test(value) || value.endsWith("/") || value.endsWith("\\")) {
    el.classList.add("invalid");
    hint.className = "field-hint err";
    hint.textContent = "Remove trailing slashes and repeated spaces from the path.";
    return false;
  }

  el.classList.remove("invalid");
  hint.className = "field-hint ok";
  hint.textContent = "Path looks valid.";
  return true;
}

async function submitWizard() {
  const w = state.wizard;

  const properties = {
    "online-mode": String(!!w.gameplay.online_mode),
    "white-list": String(!!w.gameplay.whitelist),
    "enforce-whitelist": String(!!w.gameplay.whitelist),
    "pvp": String(!!w.gameplay.pvp),
    "hardcore": String(!!w.gameplay.hardcore),
    "enable-command-block": String(!!w.gameplay.command_blocks),
    "allow-flight": String(!!w.gameplay.allow_flight),
    "spawn-protection": w.gameplay.spawn_protection ? "16" : "0",
    "max-players": "12"
  };

  const payload = {
    id: w.id,
    name: w.name,
    path: w.path,
    version: w.version,
    build: w.build,
    properties,
    geyser: !!w.bedrock,
    tunnel: w.tunnel,
    plugins: w.plugins.slice()
  };

  const btn = $("#wizNext");
  if (btn) btn.setAttribute("aria-disabled", "true");

  const res = await apiPost("/api/instances/create", payload);

  if (btn) btn.removeAttribute("aria-disabled");

  if (res && res.ok) {
    toast("Creating " + w.name + "…", "info");
    state.wizard = freshWizard();

    // Refresh the instance list, then jump to the new instance's dashboard.
    const list = await apiGet("/api/instances");
    if (list && list.instances) {
      state.instances = list.instances;
      if (list.active) state.instance = list.active;
      renderInstanceNav();
    }
    navigate("dashboard");
  } else {
    toast((res && res.error) || "Could not create the server", "error");
  }
}

/* ==========================================================================
   15b. SCREEN — CONNECT PLAYIT.GG (guided setup)
   ========================================================================== */

/*
 * Why Geyser stays on 19132 and broadcast-port points at the tunnel
 * ------------------------------------------------------------------
 * GeyserMC's own guidance is to leave Geyser listening on the default Bedrock
 * port (19132) and set `broadcast-port` to the public port the tunnel
 * assigned, so the UDP tunnel forwards to 19132 locally while Bedrock clients
 * dial the public port. playit's own support page says the opposite — move
 * Geyser onto the playit-assigned port and leave broadcast-port alone.
 *
 * This project follows GeyserMC. Do NOT "fix" it back: pointing the Bedrock
 * tunnel at the public port, or moving Geyser off 19132, breaks the
 * proxy-protocol v2 path and leaves Bedrock players connecting to a port
 * nothing is listening on. The instructions rendered below tell the user the
 * same thing, because playit's page is the one they will find by searching.
 */

function stopConnectPolling() {
  if (state.connectTimer) {
    clearInterval(state.connectTimer);
    state.connectTimer = null;
  }
}

async function startPlayitAgent() {
  const btn = $("#startPlayitBtn");
  if (btn) btn.setAttribute("aria-disabled", "true");
  // first_run lets the daemon generate a secret and print its claim link,
  // which is exactly what `TUNNEL=playit ./start.sh` does on a new machine
  const res = await apiPost("/api/playit/start", { first_run: true });
  if (btn) btn.removeAttribute("aria-disabled");
  if (res && res.ok) {
    toast("playit agent started — waiting for it to print a claim link", "info", 6000);
    setTimeout(renderScreen, 1200);
  } else {
    toast((res && res.error) || "Could not start the agent", "error", 7000);
  }
}

async function stopPlayitAgent() {
  const ok = await confirmDialog(
    "Stop the playit agent",
    "<p>The tunnels close and anyone connected through them is dropped. " +
    "The server itself keeps running, and players on your LAN are " +
    "unaffected.</p>",
    "Stop agent",
    true
  );
  if (!ok) return;
  const res = await apiPost("/api/playit/stop", {});
  if (res && res.ok) {
    toast("playit agent stopped", "ok");
    setTimeout(renderScreen, 500);
  } else {
    toast((res && res.error) || "Could not stop the agent", "error");
  }
}

async function saveBedrockPort() {
  const raw = $("#bedrockPortInput").value.trim();
  const port = parseInt(raw, 10);
  if (!port || port < 1 || port > 65535) {
    toast("Enter a port between 1 and 65535", "error");
    return;
  }
  const res = await apiPost("/api/instances/tunnel-port", {
    instance: state.instance, port
  });
  if (res && res.ok) {
    toast(res.changed
          ? "broadcast-port set to " + port + " — restart the server to serve it"
          : "That port was already recorded",
          "ok", 6000);
    await refreshInstanceList();
    renderScreen();
  } else {
    toast((res && res.error) || "Could not record that port", "error", 7000);
  }
}

async function renderConnect(container) {
  const [status, tunnels] = await Promise.all([
    apiGet("/api/status"),
    apiGet("/api/tunnels")
  ]);
  state.status = status;
  state.tunnels = tunnels;

  const playitd = (status && status.playitd && status.playitd.state) || "stopped";
  const rows = (tunnels && tunnels.tunnels) || [];
  const claimed = !!(tunnels && tunnels.has_secret);
  const claimUrl = (tunnels && tunnels.claim_url)
    || (tunnels && tunnels.account && tunnels.account.login_link) || "";
  const claimCode = claimUrl.split("/claim/")[1] || "";
  const javaRow = rows.find(r => r.proto === "TCP");
  const bedrockRow = rows.find(r => r.proto === "UDP");
  const inst = (state.instances || []).find(i => i.id === state.instance) || {};
  const bedrockPublic = (bedrockRow && bedrockRow.port) || inst.bedrock_port || "";

  // While the agent is up but unclaimed, poll for the claim finishing so this
  // page advances on its own. Also poll when claimed but tunnel-less, so the
  // addresses show up the moment they are created in the playit dashboard.
  // navigate() clears the timer on any other screen.
  stopConnectPolling();
  if (playitd === "running" && (!claimed || rows.length === 0)) {
    let currentClaim = claimUrl;
    state.connectTimer = setInterval(async () => {
      if (state.screen !== "connect") { stopConnectPolling(); return; }
      const t = await apiGet("/api/tunnels");
      if (!t) return;
      state.tunnels = t;
      if (t.has_secret && (t.tunnels || []).length) {
        stopConnectPolling();
        toast("Tunnels are live — you are reachable", "ok", 6000);
        renderScreen();
        return;
      }
      if (t.has_secret) {
        stopConnectPolling();
        toast("Agent claimed — now create the two tunnels", "ok", 6000);
        renderScreen();
        return;
      }
      const link = t.claim_url || (t.account && t.account.login_link) || "";
      if (link && link !== currentClaim) {
        currentClaim = link;
        renderScreen();
      }
    }, 2500);
  }

  container.innerHTML = offlineBanner() + `
    <div class="grid">

      <!-- ===== Where am I? ===== -->
      <section class="card span-all conn-state ${claimed ? "is-ok" : "is-warn"}"
               aria-labelledby="conn-state-h">
        <div class="card-h"><span id="conn-state-h">Connection state</span></div>
        ${!claimed ? `
          <p style="margin-bottom:4px"><strong>Agent not claimed yet.</strong></p>
          <p class="small muted">
            The agent is running but has no secret tied to a playit account.
            Open the claim link below once, and this page moves on by itself.
          </p>
        ` : rows.length === 0 ? `
          <p style="margin-bottom:4px"><strong>Agent claimed ✓ — next: create your two tunnels.</strong></p>
          <p class="small muted">
            The one-time claim is done and never needs repeating, so no claim
            link is shown. What is missing is the tunnels — follow the two steps
            below in the playit dashboard.
          </p>
        ` : `
          <p style="margin-bottom:4px"><strong>Agent claimed ✓ — ${rows.length} tunnel${rows.length === 1 ? "" : "s"} configured.
            You are reachable.</strong></p>
          <p class="small muted">
            Setup is complete; your public addresses are listed below. Nothing
            else to claim or configure.
          </p>
        `}
      </section>

      <!-- ===== The agent ===== -->
      <section class="card" aria-labelledby="conn-agent-h">
        <div class="card-h"><span id="conn-agent-h">The playit agent</span>
          <span class="pill ${playitd === "running" ? "ok" : "danger"}">
            ${playitd === "running" ? "running" : "not running"}
          </span>
        </div>
        ${playitd === "running" ? `
          <p class="small muted" style="margin-bottom:12px">
            The agent is connected to playit. Tunnels you create in the playit
            dashboard appear below.
          </p>
          <button class="btn btn-block" id="stopPlayitBtn" type="button">
            ${ICONS.stop}<span>Stop the agent</span>
          </button>
        ` : `
          <p class="small muted" style="margin-bottom:12px">
            Start the agent to get a public address for this server. Nothing is
            forwarded until you create the tunnels, and the agent only ever
            makes outbound connections.
          </p>
          <button class="btn btn-primary btn-block" id="startPlayitBtn" type="button">
            ${ICONS.play}<span>Start the agent</span>
          </button>
          <p class="small faint" style="margin-top:8px">
            Needs the playit binaries in <code class="mono">bin/</code>. If they
            are missing, run <code class="mono">./setup.sh</code> (or
            <code class="mono">python3 mc_tui.py --bootstrap</code>) first.
          </p>
        `}
      </section>

      ${playitd === "running" && !claimed ? `
      <!-- ===== Claim ===== -->
      <section class="card span-all" aria-labelledby="conn-claim-h">
        <div class="card-h"><span id="conn-claim-h">Claim this agent</span>
          <span class="pill warn">one-time</span>
        </div>
        ${claimUrl ? `
          <p class="small muted">Open this link in any browser and follow the
            prompts to add the agent to your playit account:</p>
          <div class="address" style="margin-top:10px" id="claimAddress">
            <a href="${esc(claimUrl)}" target="_blank" rel="noopener noreferrer"
               style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:inherit">
              <code>${esc(claimUrl)}</code>
            </a>
            <button class="icon-btn" id="copyClaim" type="button" aria-label="Copy claim link">
              ${ICONS.copy}
            </button>
          </div>
          <p class="small" style="margin-top:10px">
            Or enter the code <strong class="mono">${esc(claimCode)}</strong> at
            <code class="mono">playit.gg/claim</code>.
          </p>
        ` : `
          <div class="empty" style="padding:10px 0 4px">
            No claim link yet. It is generated by the bundled
            <code class="mono">playit</code> CLI (not printed by the daemon),
            so this means <code class="mono">bin/playit</code> is missing or
            could not run — run <code class="mono">./setup.sh</code> and try
            again.
          </div>
        `}
        <p class="small faint" style="margin-top:9px">
          This is a browser login on purpose: it ties the agent to your account
          and cannot be automated. Leave this page open — it moves on by itself
          the moment the claim finishes. playit only issues a link while the
          agent is unclaimed, so if you close this page you can get another one
          by restarting the agent.
        </p>
      </section>
      ` : ""}

      ${claimed ? `
      <!-- ===== Create the tunnels ===== -->
      ${rows.length === 0 ? `
      <section class="card span-all" aria-labelledby="conn-tunnels-h">
        <div class="card-h"><span id="conn-tunnels-h">Create the tunnels</span>
          <span class="pill warn">the only step left</span>
        </div>
        <p class="small muted">
          Log in at <a href="https://playit.gg" target="_blank"
            rel="noopener noreferrer">playit.gg</a>, open <strong>Agents</strong>,
          pick this agent, then <strong>Tunnels → Add Tunnel</strong>. You need
          two — playit's free tier cannot mix TCP and UDP on one tunnel.
        </p>
        <div class="stack" style="margin-top:12px">
          <div>
            <h3 style="margin-bottom:5px">Tunnel 1 — Minecraft Java</h3>
            <p class="small muted" style="margin-bottom:4px">
              Type <strong>Minecraft Java</strong>, local port
              <code class="mono">25565</code>, TCP.
            </p>
            <p class="small faint">
              Java players use the playit host; port 25565 is the Minecraft
              default, so a bare host is enough.
            </p>
          </div>
          <div>
            <h3 style="margin-bottom:5px">Tunnel 2 — Minecraft Bedrock</h3>
            <p class="small muted" style="margin-bottom:4px">
              Type <strong>Minecraft Bedrock</strong>, local port
              <code class="mono">19132</code>, UDP, with
              <strong>proxy-protocol-v2</strong> turned <strong>ON</strong>.
            </p>
            <p class="small" style="color:var(--warn);margin-bottom:4px">
              Point it at the <em>local</em> Geyser port 19132 — never at the
              public port playit assigned.
            </p>
          </div>
        </div>
        <div class="divider"></div>
        <h3 style="margin-bottom:6px">Geyser config (written for you)</h3>
        <dl class="kv">
          <dt>bedrock.port</dt><dd class="tabular">19132 <span class="faint small">(leave it)</span></dd>
          <dt>clone-remote-port</dt><dd>false</dd>
          <dt>use-haproxy-protocol</dt><dd>true</dd>
          <dt>broadcast-port</dt>
          <dd class="tabular">
            ${bedrockPublic ? esc(bedrockPublic) + ' <span class="faint small">the public port</span>' : '<span class="faint">the Bedrock tunnel\'s public port</span>'}
          </dd>
        </dl>
        <p class="small faint" style="margin-top:9px">
          ${ICONS.warn.replace("<svg", '<svg style="width:13px;height:13px;vertical-align:-2px;margin-right:4px"')}
          playit's own support page tells you to move Geyser onto the public
          port; GeyserMC says keep 19132 and set broadcast-port instead. This
          project follows GeyserMC — if you change it, Bedrock players end up
          connecting to a port nothing answers.
        </p>
      </section>
      ` : ""}

      <!-- ===== Public addresses ===== -->
      <section class="card span-all" aria-labelledby="conn-addr-h">
        <div class="card-h"><span id="conn-addr-h">Public addresses</span>
          <span class="pill ${rows.length ? "ok" : "warn"}">
            ${rows.length ? rows.length + " tunnel" + (rows.length === 1 ? "" : "s") : "none yet"}
          </span>
        </div>
        ${rows.length === 0 ? `
          <div class="empty" style="padding:10px 0 4px">
            No tunnels yet. Create the two above and their addresses appear
            here within a few seconds.
          </div>
        ` : `
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Edition</th>
                  <th scope="col">Address</th>
                  <th scope="col" class="c-proto">Proto</th>
                  <th scope="col" class="c-dest">Forwards to</th>
                </tr>
              </thead>
              <tbody>
                ${rows.map(r => {
                  const edition = r.proto === "UDP" ? "Bedrock" : "Java";
                  return `<tr>
                    <td>${edition}${r.disabled ? ' <span class="pill warn">disabled</span>' : ""}</td>
                    <td class="mono">
                      ${esc(r.host)}${r.port ? ":" + esc(r.port) : ""}
                    </td>
                    <td class="c-proto">${esc(r.proto)}</td>
                    <td class="mono small c-dest">${esc(r.destination || "—")}</td>
                  </tr>`;
                }).join("")}
              </tbody>
            </table>
          </div>
          <p class="small muted" style="margin-top:10px">
            ${javaRow
              ? "Java players: <strong>Multiplayer → Direct Connect → " +
                esc(javaRow.host) + ":" + esc(javaRow.port) + "</strong>."
              : "No TCP tunnel yet — Java players need tunnel 1."}
            ${bedrockRow
              ? " Bedrock players: <strong>Servers → Add Server → " +
                esc(bedrockRow.host) + ":" + esc(bedrockRow.port) + "</strong>."
              : " Bedrock players need tunnel 2."}
          </p>
        `}
      </section>

      <!-- ===== Record the public Bedrock port ===== -->
      <section class="card span-all" aria-labelledby="conn-port-h">
        <div class="card-h">
          <span id="conn-port-h">Tell the manager the Bedrock port</span>
          ${bedrockRow && bedrockRow.port && String(bedrockRow.port) === String(inst.bedrock_port)
            ? '<span class="pill ok">saved</span>' : ""}
        </div>
        ${bedrockRow && bedrockRow.port && String(bedrockRow.port) === String(inst.bedrock_port) ? `
          <p class="small muted">
            <code class="mono">broadcast-port</code> is already set to
            <strong>${esc(bedrockRow.port)}</strong>, matching the Bedrock tunnel.
            Change it here only if you redo the tunnel.
          </p>
        ` : `
          <p class="small muted">
            Once tunnel 2 exists, playit assigns it a public port. Enter it here
            and the manager writes Geyser's <code class="mono">broadcast-port</code>
            so Bedrock clients are sent to the tunnel instead of the local port.
          </p>
        `}
        <div class="row" style="margin-top:12px;gap:8px">
          <input class="input" id="bedrockPortInput" type="number" min="1" max="65535"
                 placeholder="e.g. 6695" value="${esc(bedrockPublic)}"
                 style="max-width:180px">
          <button class="btn btn-primary" type="button" id="saveBedrockPort">
            ${ICONS.check}<span>Save</span>
          </button>
        </div>
        <p class="small faint" style="margin-top:8px">
          A running server keeps its old broadcast-port until you restart it.
        </p>
      </section>
      ` : ""}

    </div>
  `;

  const startBtn = $("#startPlayitBtn");
  if (startBtn) startBtn.onclick = startPlayitAgent;

  const stopBtn = $("#stopPlayitBtn");
  if (stopBtn) stopBtn.onclick = stopPlayitAgent;

  const copyBtn = $("#copyClaim");
  if (copyBtn) {
    copyBtn.onclick = async () => {
      try {
        await navigator.clipboard.writeText(claimUrl);
        toast("Claim link copied to clipboard", "ok");
      } catch (_) {
        toast("Copy failed — the link is selected, press Ctrl/Cmd+C", "info", 6000);
        const range = document.createRange();
        range.selectNodeContents($("#claimAddress code"));
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
    };
  }

  const saveBtn = $("#saveBedrockPort");
  if (saveBtn) saveBtn.onclick = saveBedrockPort;
}

/* ==========================================================================
   16. SCREEN — SETTINGS
   ========================================================================== */
async function renderSettings(container) {
  const [status, instances, tunnels] = await Promise.all([
    apiGet("/api/status"),
    apiGet("/api/instances"),
    apiGet("/api/tunnels")
  ]);

  if (instances && instances.instances) {
    state.instances = instances.instances;
    renderInstanceNav();
  }
  // the tunnel card below reads state.tunnels; a session that lands on this
  // screen first would otherwise show "No tunnel account information" even
  // when the agent is claimed
  state.tunnels = tunnels;

  const inst = (state.instances || []).find(i => i.id === state.instance) || null;
  const srv = (status && status.server) || {};

  const currentMemory = (inst && (inst.xmx || inst.xms)) || "";
  const currentPort = (inst && inst.server_port) || "25565";
  const currentBedrock = (inst && inst.bedrock_port) || "";
  const currentTunnel = (inst && inst.tunnel) || "none";
  const currentJava = (inst && inst.java_override) || "";

  container.innerHTML = offlineBanner() + `
    <div class="grid">

      <!-- ===== Runtime settings ===== -->
      <section class="card span-all" aria-labelledby="settings-h">
        <div class="card-h">
          <span id="settings-h">Runtime settings — ${esc(state.instance)}</span>
          <span class="pill warn">requires restart</span>
        </div>

        <p class="small muted" style="margin-bottom:14px">
          These values are read when the server process starts. Changing them
          will not affect a running server — you'll need to stop and start it.
        </p>

        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0 16px">
          <div class="field">
            <label class="field-label" for="setMemory">Memory allocation</label>
            <select class="input" id="setMemory">
              ${MEMORY_PRESETS.map(m =>
                '<option value="' + m + '"' +
                (m === currentMemory ? " selected" : "") + ">" +
                m.replace("G", " GB") +
                (m === "4G" && !currentMemory ? " — good default" : "") +
                "</option>"
              ).join("")}
            </select>
            <div class="field-hint">
              <span class="pill warn" style="font-size:10px">requires restart</span>
              ${currentMemory ? "&nbsp;Currently " + esc(currentMemory.replace("G", " GB")) + "." : ""}
            </div>
          </div>

          <div class="field">
            <label class="field-label" for="setServerPort">Server port</label>
            <input class="input" id="setServerPort" type="number" min="1" max="65535"
                   value="${esc(currentPort)}">
            <div class="field-hint">
              <span class="pill warn" style="font-size:10px">requires restart</span>
              &nbsp;The tunnel forwards to this port.
            </div>
          </div>

          <div class="field">
            <label class="field-label" for="setBedrockPort">Bedrock port</label>
            <input class="input" id="setBedrockPort" type="number" min="1" max="65535"
                   value="${currentBedrock ? esc(currentBedrock) : "19132"}"
                   ${currentBedrock ? "" : "disabled"}>
            <div class="field-hint">
              <span class="pill warn" style="font-size:10px">requires restart</span>
              ${currentBedrock
                ? "&nbsp;The public port playit gave the Bedrock tunnel."
                : "&nbsp;Set it from <strong>Connect playit</strong> once the tunnel exists."}
            </div>
          </div>

          <div class="field">
            <label class="field-label" for="setTunnel">Tunnel provider</label>
            <select class="input" id="setTunnel">
              <option value="playit" ${currentTunnel === "playit" ? "selected" : ""}>playit.gg</option>
              <option value="bore" ${currentTunnel === "bore" ? "selected" : ""}>bore.pub</option>
              <option value="none" ${currentTunnel === "none" ? "selected" : ""}>None</option>
            </select>
            <div class="field-hint">
              <span class="pill warn" style="font-size:10px">requires restart</span>
            </div>
          </div>

          <div class="field">
            <label class="field-label" for="setJava">Java path override</label>
            <input class="input" id="setJava" type="text" spellcheck="false"
                   placeholder="(use the bundled JDK)"
                   value="${esc(currentJava)}">
            <div class="field-hint">
              <span class="pill warn" style="font-size:10px">requires restart</span>
              &nbsp;Leave empty to use the JDK the manager downloaded.
            </div>
          </div>
        </div>

        <div class="row" style="margin-top:6px;gap:8px">
          <button class="btn btn-primary" type="button" id="saveSettings">Save settings</button>
          <span class="small faint">
            Changes take effect the next time this server is started.
          </span>
        </div>
      </section>

      <!-- ===== Instance info ===== -->
      <section class="card" aria-labelledby="instinfo-h">
        <div class="card-h"><span id="instinfo-h">Instance</span></div>
        ${inst ? `
          <dl class="kv">
            <dt>Id</dt><dd class="mono">${esc(inst.id)}</dd>
            <dt>Name</dt><dd>${esc(inst.name)}</dd>
            <dt>Path</dt><dd class="mono">${esc(inst.path)}</dd>
            <dt>On disk</dt>
            <dd>${inst.exists === false
                  ? '<span class="pill danger">missing</span>'
                  : '<span class="pill ok">present</span>'}</dd>
            <dt>Paper</dt><dd>${esc(inst.paper_version)} · build ${esc(inst.build)}</dd>
            <dt>Created</dt><dd>${esc(fmtDate(inst.created))}</dd>
            ${inst.note ? "<dt>Note</dt><dd>" + esc(inst.note) + "</dd>" : ""}
          </dl>
        ` : `
          <div class="empty">No instance metadata available.</div>
        `}
      </section>

      <!-- ===== Tunnel account ===== -->
      <section class="card" aria-labelledby="tunnel-h">
        <div class="card-h"><span id="tunnel-h">Tunnel account</span></div>
        ${state.tunnels && state.tunnels.account ? `
          <dl class="kv">
            <dt>Status</dt>
            <dd>${state.tunnels.account.status === "claimed"
                  ? '<span class="pill ok">claimed</span>'
                  : '<span class="pill warn">unclaimed</span>'}</dd>
          </dl>
          ${state.tunnels.account.login_link ? `
            <p class="small muted" style="margin-top:12px">
              Claim your tunnel so the address stops changing between restarts:
            </p>
            <a class="btn btn-sm" style="margin-top:8px"
               href="${esc(state.tunnels.account.login_link)}"
               target="_blank" rel="noopener noreferrer">
              ${ICONS.link}<span>Open claim page</span>
            </a>
          ` : ""}
        ` : `
          <div class="empty">No tunnel account information.</div>
        `}
      </section>

    </div>
  `;

  /* ---------- Wiring ---------- */

  const saveBtn = $("#saveSettings");
  if (saveBtn) {
    saveBtn.onclick = async () => {
      const memory = $("#setMemory");
      const port = $("#setServerPort");
      const bedrock = $("#setBedrockPort");
      const tunnel = $("#setTunnel");
      const java = $("#setJava");

      const portValue = port ? port.value.trim() : "";
      if (portValue && (parseInt(portValue, 10) < 1 || parseInt(portValue, 10) > 65535)) {
        toast("The server port must be between 1 and 65535", "error");
        return;
      }

      saveBtn.setAttribute("aria-disabled", "true");
      // the keys are the ones the backend reads: memory, server-port,
      // bedrock_port, tunnel, java (bedrock_port is only meaningful once a
      // tunnel exists, so a disabled field sends nothing)
      const res = await apiPost("/api/instances/settings", {
        instance: state.instance,
        memory: memory ? memory.value : "",
        "server-port": portValue,
        bedrock_port: bedrock && !bedrock.disabled ? bedrock.value.trim() : "",
        tunnel: tunnel ? tunnel.value : "none",
        java: java ? java.value.trim() : ""
      });
      saveBtn.removeAttribute("aria-disabled");

      if (res && res.ok) {
        if (res.unchanged) {
          toast("Nothing to save — those are already the current values", "info");
        } else {
          toast("Saved. Changes apply the next time this server starts", "ok", 6000);
          await refreshInstanceList();
          renderInstanceNav();
        }
      } else {
        toast((res && res.error) || "Could not save settings", "error");
      }
    };
  }
}

/* ==========================================================================
   17. THEME
   ========================================================================== */
const THEME_KEY = "mcsm-theme";

function currentTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  // Keep the native form controls in sync too
  document.documentElement.style.colorScheme = theme;

  const iconEl = $("#themeIcon");
  const labelEl = $("#themeLabel");
  if (iconEl) iconEl.innerHTML = theme === "dark" ? ICONS.moon : ICONS.sun;
  if (labelEl) labelEl.textContent = theme === "dark" ? "Dark theme" : "Light theme";
}

function initTheme() {
  applyTheme(currentTheme());

  const btn = $("#themeBtn");
  if (!btn) return;

  btn.onclick = () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  };

  // Follow the system when the user hasn't chosen explicitly
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    if (!localStorage.getItem(THEME_KEY)) applyTheme(currentTheme());
  };
  if (mq.addEventListener) mq.addEventListener("change", onChange);
  else if (mq.addListener) mq.addListener(onChange);
}

/* ==========================================================================
   18. SIDEBAR (mobile)
   ========================================================================== */
function openSidebar() {
  const sb = $("#sidebar");
  const scrim = $("#scrim");
  const btn = $("#menuBtn");
  sb.classList.add("open");
  scrim.hidden = false;
  requestAnimationFrame(() => scrim.classList.add("show"));
  btn.setAttribute("aria-expanded", "true");
}

function closeSidebar() {
  const sb = $("#sidebar");
  const scrim = $("#scrim");
  const btn = $("#menuBtn");
  if (!sb.classList.contains("open")) return;
  sb.classList.remove("open");
  scrim.classList.remove("show");
  btn.setAttribute("aria-expanded", "false");
  setTimeout(() => { if (!sb.classList.contains("open")) scrim.hidden = true; }, 220);
}

function initSidebar() {
  const btn = $("#menuBtn");
  const scrim = $("#scrim");

  if (btn) {
    btn.onclick = () => {
      const sb = $("#sidebar");
      if (sb.classList.contains("open")) closeSidebar();
      else openSidebar();
    };
  }
  if (scrim) scrim.onclick = closeSidebar;

  // Close on navigation and on Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidebar();
  });

  // Close if the viewport grows past the mobile breakpoint
  window.addEventListener("resize", () => {
    if (window.innerWidth > 860) closeSidebar();
  });
}

/* ==========================================================================
   19. SSE (live updates)
   ========================================================================== */
let eventSource = null;
let mockTickTimer = null;

function connectEvents() {
  if (state.mock) {
    startMockLiveUpdates();
    return;
  }

  if (typeof EventSource === "undefined") return;

  try {
    eventSource = new EventSource("/api/events");
  } catch (err) {
    console.warn("[sse] could not open stream:", err);
    return;
  }

  eventSource.addEventListener("status", (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch (_) { return; }
    const prev = state.status;
    state.status = data;

    if (state.screen === "dashboard") {
      const prevState = prev && prev.server ? prev.server.state : null;
      const nextState = data.server ? data.server.state : null;
      if (prevState !== nextState) {
        renderScreen();     // structural change — full re-render
      } else {
        updateDashboardLive(data); // just numbers
      }
    }
  });

  eventSource.addEventListener("log", (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch (_) { return; }
    const lines = (data && data.lines) || [];

    if (state.screen === "console") {
      lines.forEach(line => appendConsoleLine(line, classifyLogLine(line)));
    } else if (state.screen === "dashboard") {
      const el = $("#dashLog");
      if (el && lines.length) {
        const stick = isScrolledToBottom(el);
        lines.forEach(line => {
          const div = document.createElement("div");
          div.className = "log-line" + (classifyLogLine(line) ? " " + classifyLogLine(line) : "");
          div.textContent = line;
          el.appendChild(div);
        });
        while (el.children.length > 40) el.removeChild(el.firstChild);
        if (stick) el.scrollTop = el.scrollHeight;
      }
    }
  });

  eventSource.addEventListener("players", (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch (_) { return; }
    state.players = data;
    if (state.screen === "players") renderScreen();
  });

  eventSource.addEventListener("job", (e) => {
    let data;
    try { data = JSON.parse(e.data); } catch (_) { return; }
    applyJobs(data);
  });

  eventSource.onerror = () => {
    // EventSource reconnects on its own; just note that we might be offline.
    console.warn("[sse] connection interrupted");
  };
}

/** Mock-mode live simulation: ticks uptime and drips new log lines. */
function startMockLiveUpdates() {
  if (mockTickTimer) clearInterval(mockTickTimer);

  const ambient = [
    "[12:22:11 INFO]: <Alex> brb",
    "[12:23:40 INFO]: Saving the game (this may take a moment!)",
    "[12:23:41 INFO]: Saved the game",
    "[12:25:07 INFO]: Steve[/192.168.1.42:51988] logged in with entity id 311",
    "[12:25:07 INFO]: Steve joined the game",
    "[12:27:33 INFO]: <Steve> back",
    "[12:29:02 WARN]: Can't keep up! Is the server overloaded?",
    "[12:30:18 INFO]: Alex left the game"
  ];
  let i = 0;

  mockTickTimer = setInterval(() => {
    // Tick uptime while running
    if (MOCK.status.server.state === "running") {
      MOCK.status.server.uptime += 1;
      if (state.screen === "dashboard" && state.status) {
        state.status.server.uptime = MOCK.status.server.uptime;
        updateDashboardLive(state.status);
      }
    }

    // Occasionally append a line
    if (Math.random() < 0.25) {
      const line = ambient[i % ambient.length];
      i++;
      pushMockLog(line);

      if (state.screen === "console") {
        appendConsoleLine(line, classifyLogLine(line));
      } else if (state.screen === "dashboard") {
        const el = $("#dashLog");
        if (el) {
          const stick = isScrolledToBottom(el);
          const div = document.createElement("div");
          div.className = "log-line" + (classifyLogLine(line) ? " " + classifyLogLine(line) : "");
          div.textContent = line;
          el.appendChild(div);
          while (el.children.length > 40) el.removeChild(el.firstChild);
          if (stick) el.scrollTop = el.scrollHeight;
        }
      }
    }
  }, 1000);
}

/* ==========================================================================
   20. INIT
   ========================================================================== */
async function boot() {
  initTheme();
  initSidebar();

  renderNav();
  renderInstanceNav();

  // Load instance list up front so the sidebar is populated immediately.
  const list = await apiGet("/api/instances");
  if (list) {
    state.instances = list.instances || [];
    state.instance = list.active || (state.instances[0] && state.instances[0].id) || "main";
    state.instancesLoaded = true;
    renderInstanceNav();
  } else if (!state.mock) {
    state.online = false;
  }

  renderScreen();
  connectEvents();

  // pick up a job that was already running when the page was opened
  const jobs = await apiGet("/api/jobs");
  if (jobs) applyJobs(jobs);

  // Keep the "offline" banner honest — retry a status fetch periodically.
  setInterval(async () => {
    if (state.mock) return;
    const wasOnline = state.online;
    await apiGet("/api/status");
    if (state.online !== wasOnline) renderScreen();
  }, 20000);
}

/* Render the job bar on first paint so it doesn't flash */
renderJobBar();

/* Go */
boot();

/* --------------------------------------------------------------------------
   Keyboard niceties
   -------------------------------------------------------------------------- */
document.addEventListener("keydown", (e) => {
  // "/" focuses the console input when on the console screen
  if (e.key === "/" && state.screen === "console") {
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
      const input = $("#consoleInput");
      if (input) {
        e.preventDefault();
        input.focus();
      }
    }
  }
});
