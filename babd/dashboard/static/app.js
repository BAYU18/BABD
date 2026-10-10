"use strict";

// ---- token + API --------------------------------------------------------------------------
const params = new URLSearchParams(location.search);
let token = params.get("token") || sessionStorage.getItem("babd-token") || "";
if (params.get("token")) {
  sessionStorage.setItem("babd-token", token);
  history.replaceState(null, "", location.pathname + location.hash); // keep the token out of the address bar
}

async function api(method, path, body) {
  const res = await fetch(`/api/${path}`, {
    method,
    headers: { "X-BABD-Token": token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && data.login && !token) { loginPage("Your session ended. Sign in again."); throw new Error("signed out"); }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ---- helpers -----------------------------------------------------------------------------
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = (iso) => {
  if (!iso) return "";
  // BABD menulis timestamp dengan Python `datetime.now().isoformat()` TANPA
  // penanda zona. Proses dashboard yang sedang berjalan bisa saja memakai
  // localtime UTC (mis. /etc/localtime diganti ke Asia/Jakarta SETELAH proses
  // start), sehingga nilainya adalah UTC tanpa offset, mis. "2026-10-09T01:25:02".
  // `new Date("2026-10-09T01:25:02")` di browser membacanya sebagai waktu LOKAL
  // browser -> tampil 7 jam lebih awal dari WIB. Tempelkan 'Z' bila belum ada
  // offset eksplisit, lalu render di Asia/Jakarta agar selalu = jam WIB.
  let s = String(iso).trim();
  if (!/([zZ]|[+-]\d{2}:?\d{2})$/.test(s)) s += "Z";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false, timeZone: "Asia/Jakarta",
  });
};
const STATUS_COLORS = { working: "var(--good)", done: "var(--ceo)", waiting: "var(--warn)", blocked: "var(--bad)", idle: "var(--dim)", setup: "#c084fc", queued: "#7dd3fc" };
const PROJECT_COLORS = { ACTIVE: "var(--good)", DONE: "var(--ceo)", BLOCKED: "var(--bad)" };

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function pill(label, color, pulse = false) {
  return `<span class="pill ${pulse ? "pulse" : ""}" style="--pc:${color}">${esc(label)}</span>`;
}

// Animated workstation: robot + desk + monitor. The element is built once per agent and kept across
// re-renders (see renderAgents), so its CSS animations never restart; only data-state changes.
function station(a) {
  const c = esc(a.color), id = esc(a.id);
  const code = (dy) => [[0, 34, 1], [9, 54, 0], [18, 44, 0], [27, 24, 1], [36, 50, 0], [45, 30, 1]]
    .map(([y, w, accent]) => `<rect x="131" y="${33 + y + dy}" width="${w}" height="4" rx="2" fill="${accent ? c : "#3a5078"}"/>`).join("");
  return `<svg class="station" viewBox="0 0 220 120" role="img" aria-label="${esc(a.short_name || a.name)} workstation" data-state="idle">
    <defs><clipPath id="scr-${id}"><rect x="124" y="28" width="80" height="48" rx="4"/></clipPath></defs>
    <ellipse class="floor" cx="112" cy="112" rx="100" ry="6" fill="${c}"/>
    <rect x="14" y="98" width="192" height="8" rx="4" fill="#2f4266"/>
    <g class="monitor">
      <rect class="frame" x="118" y="22" width="92" height="60" rx="7" fill="#2a3c5e"/>
      <rect x="124" y="28" width="80" height="48" rx="4" fill="#0b1424"/>
      <g clip-path="url(#scr-${id})">
        <g class="scr scr-code"><g class="scroll">${code(0)}${code(54)}</g></g>
        <g class="scr scr-idle"><circle class="saver" cx="140" cy="44" r="3" fill="${c}"/></g>
        <g class="scr scr-wait"><path class="hourglass" d="M157 40h14l-7 12 7 12h-14l7-12z" fill="none" stroke="${c}" stroke-width="2.4" stroke-linejoin="round"/></g>
        <g class="scr scr-block"><path d="M164 38l12 22h-24z" fill="none" stroke="#f87171" stroke-width="2.6" stroke-linejoin="round"/><rect x="163" y="45" width="2.4" height="8" rx="1" fill="#f87171"/><circle cx="164.2" cy="56" r="1.4" fill="#f87171"/></g>
        <g class="scr scr-setup"><rect x="138" y="49" width="52" height="7" rx="3.5" fill="none" stroke="#3a5078" stroke-width="1.6"/><rect class="bar" x="140" y="51" width="48" height="3" rx="1.5" fill="${c}"/></g>
      </g>
      <rect x="158" y="82" width="12" height="10" fill="#2a3c5e"/>
    </g>
    <rect class="keys" x="98" y="91" width="42" height="7" rx="3" fill="#3a5078"/>
    <g class="sparks"><rect x="104" y="84" width="3" height="3" fill="${c}"/><rect x="116" y="82" width="3" height="3" fill="${c}"/><rect x="128" y="85" width="3" height="3" fill="${c}"/></g>
    <g class="bot">
      <line x1="58" y1="9" x2="58" y2="20" stroke="${c}" stroke-width="3" stroke-linecap="round"/>
      <circle class="bulb" cx="58" cy="7" r="5" fill="${c}"/>
      <g class="head">
        <rect x="32" y="20" width="52" height="40" rx="12" fill="#dfe7f3"/>
        <rect x="39" y="29" width="38" height="20" rx="8" fill="#0b1424"/>
        <g class="eyes"><circle cx="51" cy="39" r="4" fill="${c}"/><circle cx="65" cy="39" r="4" fill="${c}"/></g>
        <rect x="27" y="33" width="6" height="14" rx="3" fill="#b9c5d8"/><rect x="83" y="33" width="6" height="14" rx="3" fill="#b9c5d8"/>
      </g>
      <path d="M34 98v-24a12 12 0 0 1 12-12h24a12 12 0 0 1 12 12v24z" fill="${c}"/>
      <rect class="chest" x="50" y="72" width="16" height="8" rx="3" fill="#0b1424" opacity=".35"/>
      <path class="arm arm-back" d="M74 84q14 3 28 5" stroke="${c}" stroke-width="7" stroke-linecap="round" fill="none" opacity=".75"/>
      <path class="arm arm-front" d="M80 80q14 2 26 4" stroke="${c}" stroke-width="7" stroke-linecap="round" fill="none"/>
    </g>
    <g class="fx zzz" fill="#8597b4" font-family="Inter, sans-serif" font-weight="800">
      <text x="88" y="28" font-size="9">z</text><text x="96" y="21" font-size="11">z</text><text x="105" y="14" font-size="13">z</text></g>
    <g class="fx think"><circle cx="92" cy="14" r="9" fill="#22345a"/><circle cx="84" cy="24" r="2.5" fill="#22345a"/>
      <circle class="d1" cx="88" cy="14" r="1.6" fill="#e8eef8"/><circle class="d2" cx="92" cy="14" r="1.6" fill="#e8eef8"/><circle class="d3" cx="96" cy="14" r="1.6" fill="#e8eef8"/></g>
    <g class="fx alert"><circle cx="92" cy="14" r="9" fill="#f87171"/><rect x="90.8" y="8" width="2.4" height="8" rx="1" fill="#0b1424"/><circle cx="92" cy="19" r="1.4" fill="#0b1424"/></g>
    <g class="fx mem"><circle cx="14" cy="16" r="10" fill="#c084fc"/>
      <path d="M9 16a3 3 0 0 1 3-5a3 3 0 0 1 4 0a3 3 0 0 1 3 5a3 3 0 0 1-3 4a3 3 0 0 1-4 0a3 3 0 0 1-3-4z" fill="none" stroke="#1a1030" stroke-width="1.6"/>
      <path class="mem-arrow" d="M14 29v8m-3-3l3 3l3-3" stroke="#c084fc" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      <text class="mem-label" x="14" y="49" font-size="8.5" font-weight="800" fill="#c084fc" text-anchor="middle" font-family="Inter, sans-serif">read</text></g>
  </svg>`;
}

// ---- state -------------------------------------------------------------------------------
let S = null;             // /api/state
let viewRun = null;       // run shown in the side panel (live or from history)
let viewingHistory = false;
let liveRuns = {};        // run id -> summary, for every task running or waiting for the CEO
let pinnedRun = null;     // a live task picked in the run panel (else the panel follows the latest task)
let view = "command";    // "command" | "board" | "logs" | "reports"
const jobs = {};          // job id -> job
const chats = {};         // agent id -> [{role, content}]
const checks = {};        // agent id -> {ok, summary}
let drawer = null;        // {mode: "config"|"chat", agentId, tab}

const agentById = (id) => S.agents.find((a) => a.id === id);
const colorOf = (id) => (id === "ceo" ? "var(--ceo)" : agentById(id)?.color || "var(--muted)");
const nameOf = (id) => (id === "ceo" ? "CEO" : agentById(id)?.short_name || id);
const LIVE = ["running", "waiting_approval", "waiting_answer", "paused"];
const isLive = (r) => r && LIVE.includes(r.status);
const runActive = () => Object.values(liveRuns).some(isLive);
const liveList = () => Object.values(liveRuns).filter(isLive).sort((a, b) => (a.started_at || "").localeCompare(b.started_at || ""));

async function refresh() {
  S = await api("GET", "state");
  liveRuns = Object.fromEntries((S.active_runs || []).map((r) => [r.id, r]));
  if (!viewingHistory) viewRun = (pinnedRun && (liveRuns[pinnedRun] || (viewRun?.id === pinnedRun ? viewRun : null))) || S.run;
  renderAll();
  if (view === "board") loadBoard();
}

let refreshTimer = null;
function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => refresh().catch((e) => toast(e.message, "bad")), 250);
}

function renderAll() {
  renderTop();
  renderAgents();
  renderRun();
  renderHistory();
  renderRunButtons();
  renderNav();
  renderProjectSelects();
  renderTaskOptions();
  if (drawer?.mode === "chat") renderChat();
}

function renderTaskOptions() {
  const models = [...new Set(S.agents.flatMap((a) => [a.llm.model, a.llm.fallback?.model]).filter(Boolean))];
  for (const box of document.querySelectorAll("[data-opts]")) {
    const body = box.querySelector(".opts-body");
    if (body.dataset.ready) continue;  // keep what the user ticked across re-renders
    body.dataset.ready = "1";
    body.innerHTML = `
      <div class="help">Who works on it:</div>
      <label class="check"><input type="radio" name="mode_${box.dataset.opts}" value="auto" checked> Auto: the Team Lead picks only the agents it needs (a quick job goes straight to one agent)</label>
      <label class="check"><input type="radio" name="mode_${box.dataset.opts}" value="quick"> ⚡ Quick: the Team Lead answers or one agent does it, never the whole team</label>
      <label class="check"><input type="radio" name="mode_${box.dataset.opts}" value="full"> Whole team: plan, design, code, test, approval, deploy</label>
      <label class="check"><input type="checkbox" name="skip" value="architect"> No Architect: small change, the Team Lead's plan is the design</label>
      <label class="check"><input type="checkbox" name="skip" value="devops"> No DevOps: no deploy, stop after QA and the report</label>
      <label class="check"><input type="checkbox" name="skip" value="researcher"> No Researcher: nothing to look up outside, no internet sources needed</label>
      <label class="check"><input type="checkbox" name="skip" value="prep"> No parallel preparation (QA don't prepare while the Developer builds)</label>
      <div class="help">Model for this task only (empty = the agent's own):</div>
      <div class="opt-models">${S.agents.map((a) => `<label>${esc(a.short_name || a.name)}
        <input type="text" name="model_${esc(a.id)}" list="modelList" placeholder="${esc(a.llm.model)}"></label>`).join("")}</div>
      <datalist id="modelList">${models.map((m) => `<option value="${esc(m)}">`).join("")}</datalist>`;
  }
}

function questionCard(runId, q) {
  return `<div class="approval question" data-question="${esc(runId)}">
      <div class="eyebrow" style="color:#f0abfc">${esc(nameOf(q.agent))} asks you</div>
      <div class="q">${esc(q.question)}</div>
      ${(q.options || []).length ? `<div class="row">${q.options.map((o) => `<button type="button" class="btn small" data-answer="${esc(o)}">${esc(o)}</button>`).join("")}</div>` : ""}
      <div class="row"><input type="text" class="answer-input" placeholder="Your answer"><button type="button" class="btn small primary" data-answer-send>Send answer</button></div>
    </div>`;
}

document.addEventListener("click", async (e) => {  // answer an agent's question (task panel or board)
  const box = e.target.closest("[data-question]");
  if (!box) return;
  const opt = e.target.closest("[data-answer]");
  const send = e.target.closest("[data-answer-send]");
  if (!opt && !send) return;
  const answer = opt ? opt.dataset.answer : box.querySelector(".answer-input").value.trim();
  if (!answer) { toast("Type an answer first", "bad"); return; }
  try { await api("POST", `runs/${box.dataset.question}/answer`, { answer }); toast("Answer sent: the agent continues", "ok"); refreshSoon(); boardSoon(); }
  catch (err) { toast(err.message, "bad"); }
});

function packagesBlock(r) {
  const ps = r.packages || [];
  if (!ps.length) return "";
  const icon = { todo: "○", working: "◐", done: "●", failed: "✕" };
  return `<div class="packages"><div class="muted small">Work packages: each starts as soon as what it needs is done</div>
    ${ps.map((p) => `<div class="pkg ${esc(p.status)}"><span class="pkg-dot">${icon[p.status] || "○"}</span>
      <b>${esc(p.id)}</b> ${esc(p.title)} <span class="muted small">· ${esc(nameOf(p.agent))}${p.depends_on?.length ? ` · after ${p.depends_on.map(esc).join(", ")}` : " · starts at once"}</span></div>`).join("")}</div>`;
}

function prLabel(pr) {
  if (!pr) return "";
  const ci = { success: "✓", failure: "✗", pending: "…", none: "" }[pr.checks] ?? "";
  return ` · <a href="${esc(pr.url)}" target="_blank" rel="noopener noreferrer">PR #${esc(pr.number)}</a> ${esc(pr.state === "open" ? `CI ${ci}` : pr.state)}`;
}

function routeLabel(t) {
  const r = t.route;
  if (!r) return t.task_options?.mode && t.task_options.mode !== "auto" ? ` · mode ${esc(t.task_options.mode)}` : "";
  const who = r.route === "answer" ? nameOf("lead") : r.route === "direct" ? nameOf(r.agent) : (r.agents || []).map(nameOf).join(", ");
  return ` · <span title="${esc(r.reason || "")}">${r.route === "team" ? "👥 " : "⚡ "}${esc(who)}</span>`;
}

function readOptions(which) {
  const box = document.querySelector(`[data-opts="${which}"]`);
  const skip = [...box.querySelectorAll('[name="skip"]:checked')].map((c) => c.value);
  const models = Object.fromEntries([...box.querySelectorAll('[name^="model_"]')].map((i) => [i.name.slice(6), i.value.trim()]).filter(([, v]) => v));
  const mode = box.querySelector('[name^="mode_"]:checked')?.value || "auto";
  return skip.length || Object.keys(models).length || mode !== "auto" ? { mode, skip, models } : undefined;
}

function renderProjectSelects() {
  for (const sel of document.querySelectorAll("[data-project-select]")) {
    const keep = sel.value || S.default_project;
    sel.innerHTML = (S.projects || []).map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
    sel.value = (S.projects || []).some((p) => p.id === keep) ? keep : S.default_project;
    sel.closest(".project-pick").classList.toggle("hidden", S.project.use_projects === false);
  }
}

function renderRunButtons() {
  $("#btnCancel").classList.toggle("hidden", !(viewRun && isLive(liveRuns[viewRun.id] || viewRun) && !viewingHistory));
  $("#btnRun").textContent = runActive() ? "Add task" : "Run team";
}

// ---- top bar -----------------------------------------------------------------------------
// Initialize a bot: token + chat id -> token saved, command menu set, chat allowed and greeted, bot on.
function tgInitBlock(key) {
  return `<div class="tg-init">
      <div class="row2"><input type="text" id="tgChat_${esc(key)}" inputmode="numeric" placeholder="Your chat id, e.g. 123456789 (ask @userinfobot)">
        <button type="button" class="btn small primary" data-tg-init="${esc(key)}">⚡ Initialize bot</button></div>
      <div class="help">Paste the bot token above and your chat id, then Initialize: BABD checks the token, saves it to .env, gives the bot a button keyboard (${key === "ceo" ? "every dashboard feature: status, agents, tasks, live logs, reports, quick / full tasks, pause / resume / stop, projects, templates…" : "status, live log, recent work, new chat"}), allows your chat, sends a welcome message and starts the bot. Press Start in the bot first if Telegram says it cannot write to you.</div></div>`;
}

async function tgInit(key, token) {
  const chat = ($(`#tgChat_${key}`)?.value || "").trim();
  if (!chat) { toast("Type your chat id first", "bad"); return; }
  try {
    const r = await api("POST", "telegram/init", { target: key, chat_id: chat, token: token || undefined });
    toast(r.welcome_sent ? `@${r.username} is ready: ${r.buttons} buttons on its keyboard, welcome message sent` : r.note, r.welcome_sent ? "ok" : "bad");
    await refresh(); setTimeout(() => refresh(), 2500);
  } catch (err) { toast(err.message, "bad"); }
}

function tgStatus(key) {
  const tg = S.telegram || {};
  const bot = tg.bots?.[key];
  if (!tg.running) return `<div class="note">Bots run while the dashboard runs (<code>babd dashboard</code>).</div>`;
  if (!bot) return `<div class="note">Bot not running: turn it on and set its token.</div>`;
  return `<div class="note ${bot.ok ? "" : "warn"}">${bot.ok ? "🟢" : "🔴"} ${esc(bot.detail || "")}</div>`;
}

function projectRow(pr, isNew = false) {
  const merge = [["on_approval", "Merge after QA passes and you approve the deploy"], ["on_pass", "Merge when QA passes"], ["never", "Never merge: keep a branch to review"], ["pr", "Pull request on GitHub: merge when CI is green and you press Merge"]];
  return `<div class="proj-row" data-id="${esc(isNew ? "" : pr.id || "")}">
    <div class="row2">${text("pr_name", pr.name, "Name, e.g. Web shop")}${text("pr_repo", pr.repo, "Git repository URL (optional)")}</div>
    <div class="row2">${text("pr_path", pr.custom_path ? pr.path : "", "Folder (optional, default workspace/projects/<id>)")}${text("pr_branch", pr.branch, "Branch (default: the repo's)")}</div>
    ${text("pr_test", pr.test_command, "Test command, e.g. python -m pytest -q (BABD runs it in each task's worktree)")}
    <div class="row2">${select("pr_merge", pr.merge, merge)}
      <label class="check"><input type="checkbox" name="pr_push" ${pr.push ? "checked" : ""}> Push after merging</label></div>
    ${pr.id === "default" ? '<div class="help">Default project (always there).</div>' : `<button type="button" class="linkish" data-proj-rm>Remove</button>`}
  </div>`;
}

function scheduleRow(sc, isNew = false) {
  const projOpts = [["", "Default project"], ...(S.projects || []).map((p) => [p.id, p.name])];
  return `<div class="proj-row sch-row" data-id="${esc(isNew ? "" : sc.id || "")}">
    ${text("sc_goal", sc.goal, "Goal, e.g. cek disk dan service di server lpnotif")}
    <div class="row2">${text("sc_cron", sc.cron, "When: daily 07:00 · hourly · weekly mon 07:00 · or cron 0 7 * * *")}${select("sc_mode", sc.mode || "quick", [["quick", "⚡ Quick (one agent)"], ["auto", "Auto (Team Lead decides)"], ["full", "Whole team"]])}</div>
    <div class="row2">${select("sc_project", sc.project || "", projOpts)}
      <span><label class="check"><input type="checkbox" name="sc_enabled" ${sc.enabled !== false ? "checked" : ""}> On</label>
      <label class="check"><input type="checkbox" name="sc_auto" ${sc.auto_approve ? "checked" : ""}> Approve deploys</label></span></div>
    ${isNew ? "" : `<div class="help">${esc(sc.when || sc.cron)}${sc.next ? ` · next ${esc(sc.next.replace("T", " "))}` : ""}${sc.task ? ` · last task ${esc(sc.task)}` : ""}${sc.error ? ` · <span class="bad">${esc(sc.error)}</span>` : ""}</div>
      <button type="button" class="btn small" data-sch-run="${esc(sc.id)}">▶ Run now</button>`}
    <button type="button" class="linkish" data-sch-rm>Remove</button>
  </div>`;
}

function serverRow(sv, isNew = false) {
  const agents = (sv.agents || ["devops"]).join(", ");
  return `<div class="proj-row srv-row" data-id="${esc(isNew ? "" : sv.id || "")}">
    <div class="row2">${text("sv_id", sv.id, "Id, e.g. lpnotif")}${text("sv_name", sv.name, "Name, e.g. Server lpnotif")}</div>
    <div class="row2">${text("sv_host", sv.host, "Host or IP")}${text("sv_user", sv.user || "root", "User")}</div>
    <div class="row2">${text("sv_port", String(sv.port || 22), "Port")}${text("sv_key", sv.key, "Key path (default ~/.ssh/babd_<id>)")}</div>
    <div class="row2">${text("sv_agents", agents, "Agents that may use it, e.g. devops, developer")}${text("sv_notes", sv.notes, "Notes for the agents (OS, services…)")}</div>
    ${isNew ? "" : `<div class="row"><button type="button" class="btn small" data-srv-keygen="${esc(sv.id)}">🔑 ${sv.key_exists ? "Show public key" : "Generate key"}</button>
      <button type="button" class="btn small" data-srv-test="${esc(sv.id)}">🔌 Test connection</button></div><pre class="log-detail hidden" data-srv-out="${esc(sv.id)}"></pre>`}
    <button type="button" class="linkish" data-srv-rm>Remove</button>
  </div>`;
}

function brainPill() {
  const b = S.brain || {};
  if (!b.enabled) return pill("off", "var(--dim)");
  if (!b.brain) return pill("not set up", "var(--warn)");
  return pill("ready", "var(--good)");
}
function brainTitle() {
  const b = S.brain || {};
  return b.enabled ? `Team brain in ${b.home}${b.brain ? "" : " (run Set up all)"}. Every agent reads it before a task and writes to it after.` : "GBrain is off";
}

function renderTop() {
  const p = S.project;
  $("#projectName").textContent = p.name;
  const lives = liveList();
  const live = lives.length ? lives : null;
  // Fallback when nothing is running: show the latest finished run from history, not stale config.
  const latest = (S.runs || [])[0] || null;
  const waitingCeo = lives.filter((r) => r.approval?.result === "pending").length;
  const status = live ? (waitingCeo === lives.length ? "WAITING" : "RUNNING") : (latest ? latest.status : p.status);
  const progress = live ? Math.round(lives.reduce((n, r) => n + (r.progress || 0), 0) / lives.length)
    : (latest ? (latest.progress ?? 0) : p.progress);
  const working = live ? S.agents.filter((a) => agentState(a) === "working").length
    : S.agents.filter((a) => a.status === "working").length;
  const blockers = live ? lives.reduce((n, r) => n + (r.blockers || []).length, 0)
    : (latest ? (latest.blockers || 0) : p.blockers);
  const approval = live ? waitingCeo : (latest ? (latest.approval_needed ?? 0) : p.approval_needed);
  const queued = (S.queue || []).filter((q) => q.status === "queued").length;
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="l">Status</div><div class="v">${pill(status, PROJECT_COLORS[status] || "var(--warn)", !!live)}</div></div>
    <div class="kpi progress"><div class="l">Progres · ${progress}%${lives.length > 1 ? ` · ${lives.length} tasks` : (latest && !live ? ` · ${esc(latest.id)}` : "")}</div><div class="bar"><i style="width:${progress}%"></i></div></div>
    <div class="kpi"><div class="l">Tasks</div><div class="v">${lives.length}<span class="muted small"> running${queued ? ` · ${queued} queued` : ""}</span></div></div>
    <div class="kpi"><div class="l">Agen bekerja</div><div class="v">${working} / ${S.agents.length}</div></div>
    <div class="kpi"><div class="l">Butuh persetujuan</div><div class="v" style="color:${approval ? "var(--warn)" : "inherit"}">${approval}</div></div>
    <div class="kpi"><div class="l">Hambatan</div><div class="v" style="color:${blockers ? "var(--bad)" : "inherit"}">${blockers}</div></div>
    <div class="kpi" title="${esc(brainTitle())}"><div class="l">Memori GBrain</div><div class="v">${brainPill()}</div></div>`;
}

// ---- agent cards -------------------------------------------------------------------------
// The agent across every live task: working beats queued beats waiting; the task line names what it does.
function agentLive(a) {
  const mine = liveList().map((r) => ({ r, s: r.agents?.[a.id] })).filter((x) => x.s && !["idle", "done"].includes(x.s.status));
  if (!mine.length) return null;
  for (const status of ["working", "queued", "waiting", "blocked"]) {
    const hit = mine.filter((x) => x.s.status === status);
    if (!hit.length) continue;
    const many = liveList().length > 1;
    const task = hit.map((x) => (many ? `${x.s.task} — ${x.r.goal.slice(0, 40)}` : x.s.task)).join("\n");
    return { status, task, count: hit.length };
  }
  return null;
}

// What the agent is really doing now: the live run first, then a running chat/setup job; outside a run
// only "waiting" / "blocked" from the last run are kept (other saved statuses are just the template's).
function agentState(a) {
  const live = agentLive(a);
  const job = Object.values(jobs).find((j) => j.agent === a.id && j.status === "running");
  if (live) return live.status === "done" ? "done" : live.status;
  if (job) return job.kind === "setup" ? "setup" : "working";
  return ["waiting", "blocked"].includes(a.status) ? a.status : "idle";
}

function agentCard(a) {
  const live = agentLive(a);
  const status = agentState(a);
  const busy = Object.values(jobs).find((j) => j.agent === a.id && j.status === "running");
  const llm = a.llm, h = a.harness;
  const check = checks[a.id];
  const harnessLabel = S.harnesses[h.type]?.label || h.type;
  const subs = a.sub_tasks.map((s) => `<li class="${esc(s.state)}"><span class="box"></span>${esc(s.name)}</li>`).join("");
  return `
  <article class="agent ${a.id === "lead" ? "lead" : ""} ${status === "working" ? "working" : ""}" style="--c:${esc(a.color)}" data-agent="${esc(a.id)}">
    <div>
      <div class="station-slot" data-station="${esc(a.id)}"></div>
      <div class="agent-top">
        <div><div class="agent-name">${esc(a.name)}</div>${pill(status, STATUS_COLORS[status] || "var(--dim)", status === "working")}</div>
      </div>
      <div class="agent-task" style="margin-top:10px">${esc(a.main_task.join(" "))}</div>
    </div>
    <div style="display:grid;gap:10px;align-content:start">
      <ul class="subtasks">${subs}</ul>
      ${live?.task ? `<div class="agent-task-now">${live.count > 1 ? `<b>${live.count} tasks at once</b><br>` : ""}${esc(live.task).replaceAll("\n", "<br>")}</div>` : ""}
    </div>
    <div style="display:grid;gap:10px;align-content:start">
      <div class="chips">
        <span class="chip" title="${esc(a.harness_summary)}">Harness <b>${esc(harnessLabel)}</b></span>
        <span class="chip" title="${esc(llm.base_url || "")}">LLM <b>${esc(llm.model)}</b></span>
        <span class="chip ${llm.api_key_set ? "ok" : "bad"}">${llm.api_key_set ? "key set" : "no key"}</span>
        ${a.permissions ? `<span class="chip" title="${esc(S.permissions?.profiles[a.permissions] || "")}">🔒 <b>${esc(a.permissions)}</b>${a.sandbox === "docker" ? " · docker" : ""}</span>` : ""}
        ${recChip(a)}
        ${packsChip(a)}
        ${a.telegram?.enabled ? `<span class="chip">Telegram <b>${esc(a.telegram.bot_username)}</b></span>` : ""}
        ${check ? `<span class="chip ${check.ok ? "ok" : "bad"}" title="${esc(check.summary)}">${check.ok ? "check OK" : "check failed"}</span>` : ""}
      </div>
      <div class="agent-actions">
        <button class="btn small" data-act="chat">Chat</button>
        <button class="btn small ghost" data-act="log" title="Everything this agent did">Log</button>
        <button class="btn small" data-act="config">Configure</button>
        <button class="btn small ghost" data-act="setup" ${busy ? "disabled" : ""}>${busy?.kind === "setup" ? '<span class="spinner"></span> Setting up' : "Set up"}</button>
      </div>
    </div>
  </article>`;
}

// ---- skills: packs and what is recommended per agent --------------------------------------
const PACKS = () => S.skillpacks || [];
const STEP_LABELS = { plan: "Plan", design: "Design", code: "Code", test_report: "Test", fix: "Fix",
  deploy_report: "Deploy", report: "Report", report_blocked: "Report when blocked" };
const packList = (f, p) => f[p.key] ?? p.recommended[f.id] ?? [];

function recStatus(f) {
  const out = { packs: {}, have: 0, total: 0 };
  for (const p of PACKS()) {
    const rec = p.recommended[f.id] || [];
    const mine = packList(f, p);
    out.packs[p.key] = { rec, missing: rec.filter((n) => !mine.includes(n)) };
  }
  const listed = (f.skills || []).map((s) => s.toLowerCase());
  const gen = (S.general_skills || {})[f.id] || [];
  out.general = { rec: gen, missing: gen.filter((n) => !listed.includes(n.toLowerCase())) };
  for (const part of [...Object.values(out.packs), out.general]) { out.total += part.rec.length; out.have += part.rec.length - part.missing.length; }
  return out;
}

function recChip(a) {
  const st = recStatus(a);
  if (!st.total) return "";
  const missing = [...st.general.missing, ...Object.values(st.packs).flatMap((x) => x.missing)];
  const ok = !missing.length;
  const title = ok ? "Every skill recommended for this agent is on. Click to see them." : `Recommended but off:\n${missing.join("\n")}\nClick to fix.`;
  return `<button type="button" class="chip rec ${ok ? "ok" : "warn"}" data-act="skills" title="${esc(title)}">★ Recommended <b>${st.have}/${st.total}</b>${ok ? " ✓" : " · fix"}</button>`;
}

function packsChip(a) {
  const on = PACKS().filter((p) => p.enabled && packList(a, p).length);
  if (!on.length) return "";
  const title = on.map((p) => `${p.title}:\n${packList(a, p).join("\n")}`).join("\n\n");
  return `<span class="chip" title="${esc(title)}">Skill packs <b>${on.map((p) => `${esc(p.title.split(" ")[0])} ×${packList(a, p).length}`).join(" · ")}</b></span>`;
}

function packSection(f, p) {
  const rec = p.recommended[f.id] || [];
  const mine = packList(f, p);
  const byName = Object.fromEntries(p.catalog.map((c) => [c.name, c]));
  const recItems = rec.filter((n) => byName[n]).map((n) => byName[n]);
  const others = p.catalog.filter((c) => !rec.includes(c.name));
  const item = (c, isRec) => {
    const on = mine.includes(c.name);
    const steps = c.steps.map((k) => STEP_LABELS[k] || k);
    return `<label class="sp-item ${isRec ? "rec" : ""} ${isRec && !on ? "off" : ""}"><input type="checkbox" name="pk_${p.key}_${esc(c.name)}" ${on ? "checked" : ""}>
      <span><b>${esc(c.name)}</b> ${isRec ? '<span class="rec-badge">★ Recommended</span>' : '<span class="opt-badge">Optional</span>'}${isRec && !on ? ' <span class="off-badge">off</span>' : ""}
        <span class="plain">${esc(c.plain || c.description)}</span>
        <span class="help">${c.optional ? `Not given by default: ${esc(c.optional)} · ` : ""}${steps.length ? `used in: ${esc([...new Set(steps)].join(", "))}` : "used whenever it fits"}</span></span></label>`;
  };
  const onCount = mine.length;
  const recOn = rec.filter((n) => mine.includes(n)).length;
  return `<div class="field pack-head"><label>${esc(p.title)} · <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.source)}</a> · runs locally</label>
      <div class="help">${recOn} of ${rec.length} recommended on · ${onCount} in use. ${p.enabled ? 'Skills that are on are always used: on every team step they fit, their full text goes into the prompt and the answer must end with "Skills applied".' : "This pack is turned off in Team settings."}</div></div>
    ${recItems.length ? `<div class="sp-list">${recItems.map((c) => item(c, true)).join("")}</div>` : '<div class="muted small">Nothing in this pack is needed for this role.</div>'}
    ${others.length ? `<details class="sp-more" data-pack="${esc(p.key)}"><summary>Optional skills (${others.length}): not needed for this role</summary>
      <div class="sp-list">${others.map((c) => item(c, false)).join("")}</div></details>` : ""}`;
}

function skillGuide() {
  const rows = S.agents.map((a) => {
    const st = recStatus(a);
    const ok = st.have === st.total;
    const line = (name, plain, on) => `<li class="${on ? "on" : "off"}"><span class="mark">${on ? "✓" : "✗"}</span><b>${esc(name)}</b><span>${esc(plain)}</span></li>`;
    const basic = st.general.rec.map((n) => line(n, n.toLowerCase() === "gbrain" ? "Shared team memory: read before, write after every task." : "Listed in the agent's instructions.", !st.general.missing.includes(n)));
    const packs = PACKS().map((p) => {
      const rec = p.recommended[a.id] || [];
      if (!rec.length) return "";
      const byName = Object.fromEntries(p.catalog.map((c) => [c.name, c]));
      return `<h5>${esc(p.title)}</h5><ul class="guide-list">${rec.map((n) => line(n, byName[n]?.plain || "", !st.packs[p.key].missing.includes(n))).join("")}</ul>`;
    }).join("");
    return `<section class="guide-agent" style="--c:${esc(a.color)}">
      <header><b>${esc(a.name)}</b><span class="chip rec ${ok ? "ok" : "warn"}">★ ${st.have}/${st.total}${ok ? " ✓" : ""}</span>
        <button class="btn small" data-guide="${esc(a.id)}">${ok ? "Open skills" : "Fix"}</button></header>
      <div class="help">${esc(a.main_task.join(" "))}</div>
      <h5>Basic skills</h5><ul class="guide-list">${basic.join("")}</ul>${packs}</section>`;
  }).join("");
  openModal("Skill guide", `
    <div class="note">Each agent needs the skills marked ★ for its job. ✓ = on, ✗ = recommended but off. Skills run on this machine and are used on every step they fit.</div>
    <div class="guide">${rows}</div>`);
  for (const b of document.querySelectorAll("[data-guide]")) b.onclick = () => { closeModal(); openDrawer("config", b.dataset.guide, "skills"); };
}

const stations = {}; // agent id -> its <svg class="station">, reused across renders
function renderAgents() {
  const box = $("#agents");
  for (const el of Object.values(stations)) el.remove(); // detach first, so innerHTML can't destroy them
  box.innerHTML = S.agents.map(agentCard).join("");
  for (const a of S.agents) {
    const slot = box.querySelector(`[data-station="${CSS.escape(a.id)}"]`);
    const key = `${a.id}|${a.color}`;
    if (!stations[a.id] || stations[a.id].dataset.key !== key) {
      const t = document.createElement("template");
      t.innerHTML = station(a).trim();
      stations[a.id] = t.content.firstChild;
      stations[a.id].dataset.key = key;
    }
    stations[a.id].dataset.state = agentState(a) === "queued" ? "waiting" : agentState(a);
    slot.appendChild(stations[a.id]);
  }
}

// a short "gbrain read / write" badge over the agent's head
const memTimers = {};
function flashMemory(agentId, op) {
  const el = stations[agentId];
  if (!el) return;
  el.dataset.mem = op;
  el.querySelector(".mem-label").textContent = op === "read" ? "read" : "write";
  el.setAttribute("aria-label", `${nameOf(agentId)} ${op === "read" ? "reading" : "writing"} gbrain`);
  clearTimeout(memTimers[agentId]);
  memTimers[agentId] = setTimeout(() => delete el.dataset.mem, 2400);
}

$("#agents").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.closest("[data-agent]").dataset.agent;
  if (btn.dataset.act === "config") openDrawer("config", id);
  if (btn.dataset.act === "skills") openDrawer("config", id, "skills");
  if (btn.dataset.act === "chat") openDrawer("chat", id);
  if (btn.dataset.act === "log") { logAgent = id; setView("logs"); }
  if (btn.dataset.act === "setup") {
    try { trackJob(await api("POST", `agents/${id}/setup`)); toast(`Setting up ${nameOf(id)}…`); }
    catch (err) { toast(err.message, "bad"); }
  }
});

// ---- run panel ---------------------------------------------------------------------------
function renderHistory() {
  const sel = $("#runHistory");
  const current = sel.value;
  const lives = liveList();
  const liveIds = new Set(lives.map((r) => r.id));
  sel.innerHTML = `<option value="">Latest task</option>`
    + (lives.length ? `<optgroup label="Running now">${lives.map((r) => `<option value="live:${esc(r.id)}">● ${esc(r.status === "waiting_approval" ? "waiting CEO" : "running")} · ${esc((r.goal || "").slice(0, 34))}</option>`).join("")}</optgroup>` : "")
    + `<optgroup label="History">${S.runs.filter((r) => !liveIds.has(r.id))
      .map((r) => `<option value="${esc(r.id)}">${esc(r.id)} · ${esc(r.status)} · ${esc((r.goal || "").slice(0, 32))}</option>`).join("")}</optgroup>`;
  sel.value = [...sel.options].some((o) => o.value === current) ? current : "";
}

async function showRun(id) {
  const liveId = id.startsWith("live:") ? id.slice(5) : (liveRuns[id] ? id : null);
  viewingHistory = !!id && !liveId;
  try { viewRun = liveId ? liveRuns[liveId] : id ? await api("GET", `runs/${id}`) : S.run; } catch (err) { toast(err.message, "bad"); }
  pinnedRun = liveId || null;
  renderRun();
  renderRunButtons();
}

$("#runHistory").addEventListener("change", (e) => showRun(e.target.value));

const shown = new Set();
function messageItem(m) {
  const long = String(m.content).length > 280;
  const open = shown.has(`${viewRun.id}:${m.seq}`);
  return `<li class="msg">
    <div class="msg-head">
      <span class="who" style="--c:${colorOf(m.from)}">${esc(nameOf(m.from))}</span><span class="arrow">→</span>
      <span class="who" style="--c:${colorOf(m.to)}">${esc(nameOf(m.to))}</span>
      <span class="kind">${esc(m.kind)}</span>${m.seconds ? `<span class="muted small">${m.seconds}s</span>` : ""}
      <span class="msg-time">${fmtTime(m.at)}</span>
    </div>
    <div class="msg-body ${long && !open ? "clamp" : ""}">${esc(m.content)}</div>
    ${long ? `<button class="linkish" data-seq="${m.seq}">${open ? "Show less" : "Show more"}</button>` : ""}
  </li>`;
}

// ---- memory text helpers (pure; tested by tests/test_memory_text.py) ----
const MEM_KEYWORDS_MAX = 6;
const MEM_ITEMS_SHOWN = 3;

function memoryNum(v) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

function memoryKeywords(query) {
  const parts = String(query ?? "").split(/\s+or\s+/i).map((w) => w.trim()).filter(Boolean);
  if (parts.length <= MEM_KEYWORDS_MAX) return parts;
  return [...parts.slice(0, MEM_KEYWORDS_MAX), "…"];
}

function memoryCountLine(facts, pages) {
  const f = memoryNum(facts), p = memoryNum(pages);
  if (!f && !p) return "";
  const cat = (n, word) => `${n} ${word}`;
  return `${cat(f, "catatan")}, ${cat(p, "halaman")}`;
}

function memoryHeadline(m) {
  const read = m.op === "read";
  const detail = (read ? m.items || [] : m.fact ? [m.fact] : []).map(String);
  const facts = read ? memoryNum(m.facts) : 0;
  const pages = read ? memoryNum(m.pages) : 0;
  return {
    label: read ? "Membaca memori tim" : "Menyimpan ke memori tim",
    count: read ? memoryCountLine(facts, pages) : "",
    keywords: read ? memoryKeywords(m.query) : [],
    detail,
    empty: read && !facts && !pages,
  };
}

function memoryLogText(who, m) {
  const h = memoryHeadline(m);
  if (h.empty) return `${who} · ${h.label} · tidak ada memori terkait · kata kunci: ${h.keywords.join(", ")}`;
  const kw = h.keywords.length ? ` · kata kunci: ${h.keywords.join(", ")}` : "";
  return `${who} · ${h.label}${h.count ? ` · ${h.count}` : ""}${kw}`;
}
// ---- end memory text helpers ----

function memoryItem(m) {
  const h = memoryHeadline(m);
  const head = `<span class="mem-dot"></span>
    <span class="who" style="--c:${colorOf(m.agent)}">${esc(nameOf(m.agent))}</span>
    <span class="mem-act">${esc(h.label)}</span>`;
  const bits = [];
  if (h.count) bits.push(`<span class="kind">${esc(h.count)}</span>`);
  if (h.keywords.length) bits.push(`<span class="mem-kw">kata kunci: ${esc(h.keywords.join(", "))}</span>`);
  const empty = h.empty ? ` <span class="mem-empty">Tidak ada memori terkait — kamu yang pertama</span>` : "";
  const found = !h.empty && h.detail.length
    ? `<span class="mem-found">↳ ${h.detail.length} temuan: ${esc(h.detail.slice(0, MEM_ITEMS_SHOWN).map((d) => `"${d}"`).join(", "))}${h.detail.length > MEM_ITEMS_SHOWN ? " …" : ""}</span>`
    : "";
  return `<li class="mem ${m.op}" title="${esc(h.detail.join("\n"))}">${head}
    <span class="mem-mid">${bits.join(" · ")}${empty}${found}</span>
    <span class="msg-time">${fmtTime(m.at)}</span></li>`;
}

function skillsItem(k) {
  const ok = !k.missing.length;
  const what = ok ? `applied ${k.skills.length} skill(s)${k.retried ? " (after a redo)" : ""}`
    : `⚠ skipped ${esc(k.missing.join(", "))}${k.retried ? " even after a redo" : ""}`;
  return `<li class="mem skills ${ok ? "ok" : "bad"}" title="${esc(k.skills.join("\n"))}"><span class="mem-dot"></span>
    <span class="who" style="--c:${colorOf(k.agent)}">${esc(nameOf(k.agent))}</span> skills · ${what}
    <span class="kind">${esc(k.skills.join(", "))}</span><span class="msg-time">${fmtTime(k.at)}</span></li>`;
}

function timelineItems(r) {
  const mem = [...(r.memory || []), ...(r.skills || []).map((k) => ({ ...k, isSkills: true }))]
    .sort((a, b) => (a.at || "").localeCompare(b.at || ""));
  const out = [];
  const memAfter = (seq) => mem.filter((m) => m.after_seq === seq).map((m) => (m.isSkills ? skillsItem(m) : memoryItem(m)));
  out.push(...memAfter(0));
  for (const m of r.messages || []) {
    out.push(messageItem(m));
    out.push(...memAfter(m.seq));
  }
  return out.join("");
}

const typingAnswer = () => document.activeElement?.classList?.contains("answer-input");

function renderRun() {
  if (typingAnswer()) { setTimeout(renderRun, 1500); return; }  // never wipe an answer being typed
  const r = viewRun;
  const body = $("#runBody");
  if (!r) {
    body.innerHTML = `<div class="empty">Belum ada run.<br>Beri tim sebuah goal untuk melihat para agen saling berbicara di sini.</div>`;
    return;
  }
  const stages = S.flow.stages.map((s) => `<div class="step ${esc(r.stages?.[s.key] || "todo")}" title="${esc(nameOf(s.owner))}"><i></i>${esc(s.label)}</div>`).join("");
  const statusColor = { waiting_answer: "#f0abfc", paused: "#c4b5fd", running: "var(--good)", waiting_approval: "var(--warn)", done: "var(--ceo)", failed: "var(--bad)", cancelled: "var(--dim)", interrupted: "var(--warn)" }[r.status];
  const approval = r.approval?.result === "pending" && !viewingHistory ? `
    <div class="approval">
      <div class="eyebrow" style="color:var(--warn)">CEO approval needed</div>
      <div class="q">${esc(r.approval.question)}</div>
      <input type="text" id="approvalNote" placeholder="Note for the team (optional)">
      <div class="row"><button class="btn good" data-approve="1">Approve deploy</button><button class="btn danger" data-approve="0">Reject</button></div>
    </div>` : "";
  const qn = r.question && !viewingHistory ? questionCard(r.id, r.question) : "";
  const rep = r.report;
  const report = rep ? `
    <div class="report">
      <div class="eyebrow">Laporan ke CEO</div>
      <div class="report-grid">
        <div><div class="l">Status</div><div class="v">${esc(rep.status)}</div></div>
        <div><div class="l">QA</div><div class="v">${esc(rep.qa_verdict)}${rep.fix_rounds ? ` · ${rep.fix_rounds} fix` : ""}
          <span class="ev ${rep.verified ? "ok" : "no"}" title="${esc(r.evidence?.note || "")}">${rep.verified ? "✓ verified" : "unverified"}</span></div></div>
        <div><div class="l">Deployed</div><div class="v">${rep.deployed ? "Yes" : "No"}</div></div>
        <div><div class="l">Recent</div><div class="v">${esc(rep.recent_result || "—")}</div></div>
        <div><div class="l">Next</div><div class="v">${esc(rep.next_action || "—")}</div></div>
        <div><div class="l">Hambatan</div><div class="v">${esc(rep.blockers ?? 0)}</div></div>
      </div>
      ${rep.summary ? `<div class="small">${esc(rep.summary)}</div>` : ""}
      ${(rep.blocker_list || []).map((b) => `<div class="small" style="color:var(--bad)">● ${esc(b)}</div>`).join("")}
    </div>` : "";
  body.innerHTML = `
    <div>
      <div class="run-goal">${esc(r.goal)}</div>
      ${docChips(r.documents, r.id)}${workspaceLine(r.workspace)}${evidenceLine(r)}
      <div class="run-meta">${pill(r.status.replace("_", " "), statusColor, r.status === "running")}
        <span class="muted small">${esc(r.id)} · ${r.progress ?? 0}%${r.qa_rounds ? ` · ${r.qa_rounds} QA fix round(s)` : ""}${usageText(r.usage) ? ` · ${esc(usageText(r.usage))}` : ""}</span></div>
      ${r.error ? `<div class="note warn" style="margin-top:8px">${esc(r.error)}</div>` : ""}
      ${r.status === "running" && !r.paused ? `<button type="button" class="btn small ghost" style="margin-top:8px" data-pause-run="${esc(r.id)}" title="The steps already working finish; the next ones wait">⏸ Pause</button>` : ""}
      ${isLive(r) && (r.paused || r.status === "paused") ? `<button type="button" class="btn small good" style="margin-top:8px" data-unpause-run="${esc(r.id)}">▶ Resume</button>` : ""}
      ${RESUMABLE.includes(r.status) ? `<button type="button" class="btn small" style="margin-top:8px" data-resume-run="${esc(r.id)}">Resume from the last finished step</button>` : ""}
      ${!isLive(r) && r.finished_at ? `<button type="button" class="btn small ghost" style="margin-top:8px" data-export-run="${esc(r.id)}">Ekspor laporan (.md)</button>` : ""}
    </div>
    <div class="stepper">${stages}</div>
    ${packagesBlock(r)}
    ${qn}${approval}${report}
    <ol class="timeline" id="timeline">${timelineItems(r)}</ol>`;
  const tl = $("#timeline");
  if (r.status === "running" || r.status === "waiting_approval") tl.scrollTop = tl.scrollHeight;
}

$("#runBody").addEventListener("click", async (e) => {
  const more = e.target.closest("[data-seq]");
  if (more) {
    const key = `${viewRun.id}:${more.dataset.seq}`;
    shown.has(key) ? shown.delete(key) : shown.add(key);
    renderRun();
    return;
  }
  const ex = e.target.closest("[data-export-run]");
  if (ex) { downloadReport(ex.dataset.exportRun); return; }
  const pz = e.target.closest("[data-pause-run], [data-unpause-run]");
  if (pz) {
    const id = pz.dataset.pauseRun || pz.dataset.unpauseRun;
    try { const r = await api("POST", `runs/${id}/${pz.dataset.pauseRun ? "pause" : "resume"}`); toast(r.note || "Continuing", "ok"); refreshSoon(); boardSoon(); }
    catch (err) { toast(err.message, "bad"); }
    return;
  }
  const rs = e.target.closest("[data-resume-run]");
  if (rs) {
    try { const r = await api("POST", `runs/${rs.dataset.resumeRun}/resume`); toast(`Resuming: ${r.goal}`, "ok"); viewingHistory = false; pinnedRun = rs.dataset.resumeRun; refreshSoon(); }
    catch (err) { toast(err.message, "bad"); }
    return;
  }
  const ap = e.target.closest("[data-approve]");
  if (ap) {
    try {
      await api("POST", `runs/${viewRun.id}/approve`, { approved: ap.dataset.approve === "1", note: $("#approvalNote")?.value || "" });
      toast(ap.dataset.approve === "1" ? "Deploy approved" : "Deploy rejected", ap.dataset.approve === "1" ? "ok" : "");
    } catch (err) { toast(err.message, "bad"); }
  }
});

// ---- command center ----------------------------------------------------------------------
$("#btnRun").addEventListener("click", async () => {
  let goal = $("#goal").value.trim();
  const att = attachments.command;
  if (isLink(goal)) { addLink("command", goal); goal = ""; $("#goal").value = ""; }  // a pasted link is a document
  if (!goal && !att.docs.length && !att.links.length) { toast("Write a goal, or attach a .md task file", "bad"); $("#goal").focus(); return; }
  try {
    viewingHistory = false;
    $("#runHistory").value = "";
    $("#btnRun").disabled = true;
    const r = await api("POST", "runs", { goal, auto_approve: $("#autoApprove").checked, update_dashboard: $("#updateImage").checked,
      documents: att.docs.map((d) => ({ name: d.name, content: d.content })), links: att.links, project: $("#goalProject").value || undefined, options: readOptions("command") })
      .finally(() => { $("#btnRun").disabled = false; });
    $("#goal").value = "";
    clearAttach("command");
    if (r.status === "queued") {
      toast(`Task queued (#${r.position}): it starts when a task slot is free`);
      refreshSoon();
      return;
    }
    S.run = r; liveRuns[r.id] = r; viewRun = r; pinnedRun = null;
    renderAll();
    toast(liveList().length > 1 ? `Task started · ${liveList().length} tasks running in parallel` : "Team run started");
  } catch (err) { toast(err.message, "bad"); }
});

$("#btnCancel").addEventListener("click", async () => {
  if (!viewRun) return;
  try { const r = await api("POST", `runs/${viewRun.id}/cancel`); toast(r.note || "Stopping…"); }
  catch (err) { toast(err.message, "bad"); }
});

$("#btnCheck").addEventListener("click", async () => {
  try { trackJob(await api("POST", "check")); toast("Sending a test message to every agent…"); }
  catch (err) { toast(err.message, "bad"); }
});

$("#btnSetup").addEventListener("click", async () => {
  try { trackJob(await api("POST", "setup")); toast("Installing and configuring every harness…"); }
  catch (err) { toast(err.message, "bad"); }
});

// ---- activity log + jobs -----------------------------------------------------------------
function logLine(source, msg, cls = "", at = null) {
  const li = document.createElement("li");
  // at kosong -> pakai jam SERVER (atNow). Kalau server belum diketahui, TULIS "—"
  // (jangan pernah jam OS klien: itu akar "beda dengan jam WIB").
  const t = (at === null || at === undefined || at === "") ? atNow() : at;
  const stamp = (t === null || t === undefined || t === "") ? "—" : (hhmmISO(t) || "—");
  li.innerHTML = `<span class="t">${stamp}</span><span class="s">${esc(source)}</span><span class="${cls}">${esc(msg)}</span>`;
  const list = $("#activity");
  list.appendChild(li);
  while (list.children.length > 400) list.firstChild.remove();
  list.scrollTop = list.scrollHeight;
}
$("#btnClearLog").addEventListener("click", () => ($("#activity").innerHTML = ""));

function trackJob(job) {
  // the job's "done" event can arrive before this POST response: never overwrite a finished job
  if (!jobs[job.id] || jobs[job.id].status === "running") jobs[job.id] = job;
  renderAgents();
  if (drawer?.mode === "chat") renderChat();
}

function onJob(job) {
  const prev = jobs[job.id];
  jobs[job.id] = job;
  if (job.status === "running") return renderAgents();
  if (prev?.status === job.status) return;
  if (job.kind === "chat") {
    if (job.status === "done") chats[job.agent] = job.result.history;
    else (chats[job.agent] ||= []).push({ role: "assistant", content: `⚠ ${job.error}`, error: true });
    if (drawer?.mode === "chat" && drawer.agentId === job.agent) renderChat();
  } else if (job.kind === "check" || job.kind === "setup") {
    if (job.status === "done") {
      for (const [id, r] of Object.entries(job.result)) {
        if (job.kind === "check") checks[id] = r;
        logLine(job.kind, `${id}: ${r.ok ? "OK" : "FAIL"} ${r.summary}`, r.ok ? "ok" : "bad", atNow());
      }
      const failed = Object.values(job.result).filter((r) => !r.ok).length;
      toast(`${job.kind === "check" ? "Check" : "Setup"} finished${failed ? ` · ${failed} failed (see Activity)` : " · all OK"}`, failed ? "bad" : "ok");
    } else {
      logLine(job.kind, job.error, "bad", atNow());
      toast(job.error, "bad");
    }
    refreshSoon();
  }
  renderAgents();
}

// ---- drawer: config + chat ---------------------------------------------------------------
const IMPLICIT_TRUE = new Set(["auto_install"]); // harness options that are on when unset
const TABS = [["role", "Role"], ["llm", "LLM"], ["harness", "Harness"], ["telegram", "Telegram"], ["skills", "Skills"]];
let form = null; // working copy of the agent being edited

function openDrawer(mode, agentId, tab = "role") {
  const a = agentById(agentId);
  drawer = { mode, agentId, tab };
  form = JSON.parse(JSON.stringify(a));
  form.api_key = "";
  $("#drawer").style.setProperty("--c", a.color);
  $("#drawerEyebrow").textContent = mode === "chat" ? "Talk to the agent" : "Agent config";
  $("#drawerTitle").textContent = a.name;
  $("#scrim").classList.remove("hidden");
  $("#drawer").classList.remove("hidden");
  mode === "chat" ? renderChat() : renderConfig();
}

function closeDrawer() {
  drawer = null;
  $("#scrim").classList.add("hidden");
  $("#drawer").classList.add("hidden");
}
$("#drawerClose").addEventListener("click", closeDrawer);
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer(); closeModal(); } });

function field(label, input, help = "") {
  return `<div class="field"><label>${esc(label)}</label>${input}${help ? `<div class="help">${esc(help)}</div>` : ""}</div>`;
}
const text = (name, value, ph = "") => `<input type="text" name="${name}" value="${esc(value ?? "")}" placeholder="${esc(ph)}">`;
const select = (name, value, opts) => `<select name="${name}">${opts.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(value ?? "") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;

function renderConfig() {
  $("#tabs").innerHTML = TABS.map(([k, l]) => `<button type="button" class="tab ${drawer.tab === k ? "on" : ""}" data-tab="${k}">${l}</button>`).join("");
  const f = form, llm = f.llm, h = f.harness;
  let html = "";
  if (drawer.tab === "role") {
    html = `
      <div class="row2">${field("Name", text("name", f.name))}${field("Short name", text("short_name", f.short_name))}</div>
      <div class="row2">${field("Main task · line 1", text("main0", f.main_task[0]))}${field("Main task · line 2", text("main1", f.main_task[1]))}</div>
      ${f.sub_tasks.map((s, i) => field(`Sub-task ${i + 1}`, `<div class="sub-row">${text(`sub${i}`, s.name)}${select(`substate${i}`, s.state, [["todo", "To do"], ["active", "Active"], ["done", "Done"]])}</div>`)).join("")}
      ${field("Status on the dashboard", select("status", f.status, [["idle", "Idle"], ["working", "Bekerja"], ["waiting", "Menunggu"], ["blocked", "Terhambat"]]))}
      ${field("Parallel steps", `<input type="number" name="parallel" min="1" max="8" value="${esc(f.parallel ?? 2)}">`, "How many steps this agent works on at the same time, across all tasks (1–8). More = faster with many tasks, but more LLM calls at once.")}
      <div class="note">Main task and sub-tasks also go into the agent's system prompt.</div>`;
  } else if (drawer.tab === "llm") {
    html = `
      <div class="row2">${field("Provider", text("provider", llm.provider, "Anthropic, Custom, OpenRouter…"))}
        ${field("API style", select("api", llm.api, [["anthropic", "Anthropic (Claude)"], ["openai", "OpenAI-compatible"]]))}</div>
      ${field("Base URL", text("base_url", llm.base_url, "https://api.anthropic.com or http://localhost:11434/v1"))}
      ${field("Model", text("model", llm.model, "claude-opus-5-5, qwen2.5-coder:7b…"))}
      <div class="row2">${field("Effort (Claude)", select("effort", llm.effort, [["", "Default"], ["low", "Low"], ["medium", "Medium"], ["high", "High"], ["xhigh", "Extra high"], ["max", "Max"]]))}
        ${field("Max tokens", `<input type="number" name="max_tokens" value="${esc(llm.max_tokens ?? "")}" placeholder="default">`)}</div>
      ${field("API key variable", text("api_key_env", llm.api_key_env, "ANTHROPIC_API_KEY"), "Name of the environment variable that holds the key.")}
      ${field("API key", `<input type="password" name="api_key" placeholder="${llm.api_key_set ? "•••••••• set — type to replace" : "paste the key"}" autocomplete="new-password">`,
        "Saved to .env (file mode 600) under the variable above. Never written to agents.json or sent back to this page.")}
      ${llm.api_key_inline ? `<div class="note warn">agents.json contains an inline api_key for this agent. Saving a key here moves it to .env.</div>` : ""}
      <div class="field"><label>Fallback model (optional)</label>
        <div class="help">When this model keeps failing (after the retries), the step is tried on this one. Empty fields use the agent's own settings.</div></div>
      <div class="row2">${text("fb_model", llm.fallback?.model, "e.g. a cheaper or local model")}${text("fb_base_url", llm.fallback?.base_url, "Base URL (optional)")}</div>
      <div class="row2">${select("fb_api", llm.fallback?.api || "", [["", "Same API style"], ["anthropic", "Anthropic (Claude)"], ["openai", "OpenAI-compatible"]])}${text("fb_key_env", llm.fallback?.api_key_env, "Key variable (optional)")}</div>`;
  } else if (drawer.tab === "harness") {
    const meta = S.harnesses[h.type] || { options: [], doc: "" };
    html = `
      ${field("Harness", select("harness_type", h.type, Object.entries(S.harnesses).map(([k, v]) => [k, `${v.label} (${k})`])), meta.doc)}
      ${meta.options.map(([key, type, help]) => {
        const v = h[key];
        if (type === "bool") return `<label class="check"><input type="checkbox" name="h_${key}" ${(v ?? IMPLICIT_TRUE.has(key)) ? "checked" : ""}> ${esc(key)} <span class="help">— ${esc(help)}</span></label>`;
        if (type === "list") return field(key, text(`h_${key}`, (v || []).join(", "), "comma separated"), help);
        if (type === "number") return field(key, `<input type="number" name="h_${key}" value="${esc(v ?? "")}">`, help);
        return field(key, text(`h_${key}`, v), help);
      }).join("")}
      <div class="row2">${field("Permissions", select("permissions", f.permissions, Object.entries(S.permissions.profiles).map(([k]) => [k, k + (S.permissions.defaults[f.id] === k ? " (recommended)" : "")])),
          esc(S.permissions.profiles[f.permissions] || ""))}
        ${field("Sandbox", select("sandbox", f.sandbox || "", [["", `Project default (${S.project?.isolation || "none"})`], ["none", "None"], ["bwrap", "bwrap: isolated (recommended)"], ["docker", "Docker (needs Docker)"]]), "bwrap: the agent's program runs isolated: system and BABD read-only, only the task's folder writable, BABD's secrets hidden. Docker: a Hermes agent's commands run in a container.")}</div>
      <div class="note">Installed and configured automatically: <b>Save & set up</b> installs the program if needed and writes this agent's config, using the LLM from the LLM tab.</div>
      <div class="note">${esc(agentById(drawer.agentId).harness_summary)}</div>`;
  } else if (drawer.tab === "telegram") {
    const t = f.telegram || {};
    html = `
      <label class="check"><input type="checkbox" name="tg_enabled" ${t.enabled ? "checked" : ""}> Telegram gateway enabled</label>
      ${field("Bot username", text("tg_bot_username", t.bot_username, "@my_agent_bot"))}
      ${field("Token variable", text("tg_token_env", t.token_env, "TELEGRAM_DEV_BOT_TOKEN"), "Environment variable holding the BotFather token.")}
      ${field("Bot token", `<input type="password" name="tg_token" placeholder="${S.telegram?.agents?.[f.id] ? "•••••••• set — type to replace" : "paste the token from @BotFather"}" autocomplete="new-password">`, "Saved to .env under the variable above, never to agents.json.")}
      ${tgInitBlock(f.id)}
      ${tgStatus(f.id)}
      <div class="note">Talk to this agent from Telegram: send the bot a message, it answers like the dashboard's Chat. Only the users allowed in Team settings → Telegram can use it.</div>`;
  } else if (drawer.tab === "skills") {
    const st = recStatus(f);
    const allOn = st.have === st.total;
    const recGeneral = new Set(st.general.rec.map((n) => n.toLowerCase()));
    html = `
      <div class="rec-summary ${allOn ? "ok" : "warn"}">
        <div><span class="rec-badge">★ Recommended</span> <b>${st.have} of ${st.total}</b> recommended skills are on for ${esc(f.short_name || f.name)}.
          <div class="help">★ Recommended = what this agent needs for its job, picked for its role. Optional = available, but not needed for this role.</div></div>
        ${allOn ? '<span class="rec-ok">✓ All set</span>' : '<button type="button" class="btn small primary" id="useRec">Turn on all recommended</button>'}
      </div>
      <div class="field"><label>Basic skills</label>
        <div class="help">Short names that go into the agent's instructions. GBrain is the shared team memory, read before and written after every task.</div></div>
      <div class="skill-editor">${f.skills.map((s, i) => `<span class="skill">${recGeneral.has(s.toLowerCase()) ? '<i class="star" title="Recommended">★</i>' : ""}${esc(s)}<button type="button" data-rmskill="${i}" aria-label="Remove ${esc(s)}">×</button></span>`).join("") || '<span class="muted">No skills yet</span>'}</div>
      ${st.general.missing.length ? `<div class="suggest"><span class="help">Recommended, not added yet:</span> ${st.general.missing.map((n) => `<button type="button" class="skill add" data-addskill="${esc(n)}">+ ${esc(n)} <i class="star">★</i></button>`).join("")}</div>` : ""}
      <div class="chat-input"><input type="text" id="newSkill" placeholder="Add a skill, e.g. Kubernetes"><button type="button" class="btn" id="addSkill">Add</button></div>
      <div class="note">Add <code>skills/&lt;skill-name&gt;.md</code> to give a basic skill real instructions.</div>
      ${PACKS().map((p) => packSection(f, p)).join("")}`;
  }
  const open = new Set([...document.querySelectorAll("#drawerBody details[open][data-pack]")].map((d) => d.dataset.pack));
  $("#drawerBody").innerHTML = html;
  for (const d of document.querySelectorAll("#drawerBody details[data-pack]")) if (open.has(d.dataset.pack)) d.open = true;
  $("#drawerFoot").innerHTML = `
    <span class="muted small" style="margin-right:auto">Saved to agents.json · image redrawn</span>
    <button class="btn" id="saveCfg">Save</button>
    <button class="btn primary" id="saveSetup">Save & set up</button>`;
  $("#saveCfg").onclick = () => saveConfig(false);
  $("#saveSetup").onclick = () => saveConfig(true);
}

$("#tabs").addEventListener("click", (e) => {
  const t = e.target.closest("[data-tab]");
  if (!t || drawer?.mode !== "config") return;
  readForm();
  drawer.tab = t.dataset.tab;
  renderConfig();
});

$("#drawerBody").addEventListener("change", (e) => {
  if (e.target.name?.startsWith("pk_")) { readForm(); renderConfig(); return; }
  if (e.target.name === "harness_type") {
    readForm();
    const type = e.target.value;
    form.harness = { type, ...JSON.parse(JSON.stringify(S.harnesses[type].defaults || {})) };
    renderConfig();
  }
});

$("#drawerBody").addEventListener("click", (e) => {
  const ti = e.target.closest("[data-tg-init]");
  if (ti) { tgInit(ti.dataset.tgInit, ($('[name="tg_token"]')?.value || "").trim()); return; }
  if (e.target.id === "addSkill") {
    const v = $("#newSkill").value.trim();
    if (v && !form.skills.includes(v)) form.skills.push(v);
    renderConfig();
    $("#newSkill")?.focus();
  }
  const add = e.target.closest("[data-addskill]");
  if (add) { readForm(); if (!form.skills.includes(add.dataset.addskill)) form.skills.push(add.dataset.addskill); renderConfig(); }
  if (e.target.id === "useRec") {
    readForm();
    for (const p of PACKS()) form[p.key] = [...new Set([...packList(form, p), ...(p.recommended[form.id] || [])])];
    for (const n of recStatus(form).general.missing) form.skills.push(n);
    renderConfig();
    toast("All recommended skills are on. Save to keep them.", "ok");
  }
  const rm = e.target.closest("[data-rmskill]");
  if (rm) { form.skills.splice(Number(rm.dataset.rmskill), 1); renderConfig(); }
});

$("#drawerBody").addEventListener("keydown", (e) => {
  if (e.target.id === "newSkill" && e.key === "Enter") { e.preventDefault(); $("#addSkill").click(); }
});

function readForm() {
  if (drawer?.mode !== "config") return;
  const fd = new FormData($("#drawerBody"));
  const get = (k) => (fd.has(k) ? String(fd.get(k)) : undefined);
  const tab = drawer.tab;
  if (tab === "role") {
    form.name = get("name"); form.short_name = get("short_name");
    form.main_task = [get("main0"), get("main1")].filter((x) => x);
    form.sub_tasks = form.sub_tasks.map((s, i) => ({ name: get(`sub${i}`), state: get(`substate${i}`) }));
    form.status = get("status");
    if (get("parallel")) form.parallel = Number(get("parallel"));
  } else if (tab === "llm") {
    for (const k of ["provider", "api", "base_url", "model", "effort", "api_key_env"]) form.llm[k] = get(k);
    form.llm.max_tokens = get("max_tokens") ? Number(get("max_tokens")) : "";
    form.api_key = get("api_key") || form.api_key;
    const fb = Object.fromEntries([["model", "fb_model"], ["base_url", "fb_base_url"], ["api", "fb_api"], ["api_key_env", "fb_key_env"]]
      .map(([k, n]) => [k, (get(n) || "").trim()]).filter(([, v]) => v));
    form.llm.fallback = fb.model ? fb : "";
  } else if (tab === "harness") {
    const type = get("harness_type");
    const h = { type };
    for (const [key, t] of S.harnesses[type].options) {
      const el = $(`[name="h_${key}"]`);
      if (!el) continue;
      if (t === "bool") {
        const before = form.harness?.type === type ? form.harness[key] : undefined;
        // an option left at its implicit default stays unset in agents.json
        if (before !== undefined || el.checked !== IMPLICIT_TRUE.has(key)) h[key] = el.checked;
      }
      else if (t === "list") h[key] = el.value.split(",").map((x) => x.trim()).filter(Boolean);
      else if (t === "number") h[key] = el.value === "" ? "" : Number(el.value);
      else h[key] = el.value.trim();
    }
    form.harness = h;
    form.permissions = get("permissions") || form.permissions;
    form.sandbox = get("sandbox") || form.sandbox;
  } else if (tab === "skills") {
    for (const p of PACKS()) form[p.key] = p.catalog.map((c) => c.name).filter((n) => $(`[name="pk_${p.key}_${CSS.escape(n)}"]`)?.checked);
  } else if (tab === "telegram") {
    form.telegram = { ...(form.telegram || {}), enabled: !!$('[name="tg_enabled"]').checked,
      bot_username: get("tg_bot_username"), token_env: get("tg_token_env") };
    form.telegram_token = get("tg_token") || form.telegram_token;
  }
}

async function saveConfig(setup) {
  readForm();
  const f = form;
  const body = {
    name: f.name, short_name: f.short_name, main_task: f.main_task, sub_tasks: f.sub_tasks, status: f.status,
    skills: f.skills, telegram: f.telegram, harness: f.harness, ...(f.parallel ? { parallel: f.parallel } : {}),
    ...(f.permissions ? { permissions: f.permissions, sandbox: f.sandbox || "none" } : {}),
    ...Object.fromEntries(PACKS().filter((p) => f[p.key]).map((p) => [p.key, f[p.key]])),
    llm: Object.fromEntries(["provider", "api", "base_url", "model", "effort", "api_key_env", "max_tokens", "fallback"].map((k) => [k, f.llm[k] ?? ""])),
  };
  if (f.api_key) body.api_key = f.api_key;
  if (f.telegram_token) body.telegram_token = f.telegram_token;
  try {
    await api("PUT", `agents/${drawer.agentId}`, body);
    form.api_key = ""; form.telegram_token = "";
    toast(`${f.short_name || f.name} saved`, "ok");
    if (setup) trackJob(await api("POST", `agents/${drawer.agentId}/setup`));
    await refresh();
    openDrawer("config", drawer.agentId, drawer.tab);
  } catch (err) { toast(err.message, "bad"); }
}

function renderChat() {
  const id = drawer.agentId;
  const history = chats[id] || [];
  const busy = Object.values(jobs).some((j) => j.agent === id && j.kind === "chat" && j.status === "running");
  const a = agentById(id);
  $("#tabs").innerHTML = "";
  $("#drawerBody").innerHTML = `
    <div class="note">Direct line to ${esc(a.short_name)} through its harness <b>${esc(S.harnesses[a.harness.type]?.label)}</b>
      with <b>${esc(a.llm.model)}</b>. This is outside the team flow; use "Run team" for the full CEO → Lead → … flow.</div>
    <div class="chat" id="chatList">
      ${history.map((m) => `<div class="bubble ${m.role === "user" ? "from-user" : "from-agent"}">${esc(m.content)}</div>`).join("") || '<div class="empty">Say something to start.</div>'}
      ${busy ? '<div class="bubble from-agent"><span class="spinner"></span> working…</div>' : ""}
    </div>`;
  $("#drawerFoot").innerHTML = `
    <div class="chat-input">
      <textarea id="chatMsg" rows="2" placeholder="Message ${esc(a.short_name)}… (Enter to send, Shift+Enter for a new line)"></textarea>
      <div style="display:grid;gap:6px"><button class="btn primary" id="chatSend" ${busy ? "disabled" : ""}>Send</button>
      <button class="btn ghost small" id="chatReset">Reset</button></div>
    </div>`;
  const list = $("#drawerBody");
  list.scrollTop = list.scrollHeight;
  $("#chatSend").onclick = sendChat;
  $("#chatReset").onclick = async () => { await api("POST", `agents/${id}/chat/reset`); chats[id] = []; renderChat(); };
  $("#chatMsg").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } });
  $("#chatMsg").focus();
}

async function sendChat() {
  const id = drawer.agentId;
  const msg = $("#chatMsg").value.trim();
  if (!msg) return;
  (chats[id] ||= []).push({ role: "user", content: msg });
  $("#chatMsg").value = "";
  try { trackJob(await api("POST", `agents/${id}/chat`, { message: msg })); }
  catch (err) { chats[id].push({ role: "assistant", content: `⚠ ${err.message}` }); renderChat(); }
}

// ---- modal: settings + image -------------------------------------------------------------
function openModal(title, html, narrow = false) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = html;
  $(".modal-card").classList.toggle("narrow", narrow);
  $("#modal").classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); }
$("#modalClose").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });

$("#btnGuide").addEventListener("click", skillGuide);

$("#btnImage").addEventListener("click", () =>
  openModal("Workspace image", `<img src="/workspace.svg?t=${Date.now()}" alt="AI software development workspace">`));

$("#btnSettings").addEventListener("click", () => {
  const p = S.project;
  openModal("Team settings", `
    ${field("Project name", text("p_name", p.name))}
    <label class="check"><input type="checkbox" id="p_approval" ${(p.require_approval || []).includes("deploy") ? "checked" : ""}> CEO must approve before DevOps deploys</label>
    ${field("Retries", `<input type="number" id="p_retries" min="1" max="10" value="${esc(p.retry?.attempts ?? 3)}">`, "Tries per step when the LLM has a temporary error (time-out, rate limit, 5xx, lost connection), waiting longer each time; then the agent's fallback model.")}
    <div class="field"><label>Token budget and prompt size</label>
      <div class="row2">${field("Tokens per task", `<input type="number" id="b_tt" min="0" step="10000" value="${esc(p.budget?.tokens_per_task || 0)}">`)}${field("USD per task", `<input type="number" id="b_ct" min="0" step="0.5" value="${esc(p.budget?.cost_per_task || 0)}">`)}</div>
      <div class="row2">${field("Tokens per day", `<input type="number" id="b_td" min="0" step="100000" value="${esc(p.budget?.tokens_per_day || 0)}">`)}${field("USD per day", `<input type="number" id="b_cd" min="0" step="1" value="${esc(p.budget?.cost_per_day || 0)}">`)}</div>
      <div class="help">0 = no limit. A task over its budget stops before its next step (raise the budget, then Resume); over the daily budget, queued tasks wait. Costs need a price per agent (agents.json llm.price) unless the tool reports them (Claude Code). Hermes token counts are estimates (~4 characters a token).</div>
      ${field("GitHub (projects with merge = pull request)", `<div class="row2"><input type="password" id="p_gh_token" placeholder="${S.github_token_set ? "•••••••• token set — type to replace" : "GitHub token (contents + pull requests: write)"}" autocomplete="new-password">${select("p_pr_merge", p.pr_merge || "approve", [["approve", "Merge a PR when you press Merge and CI is green"], ["auto", "Merge a PR by itself when CI is green"]])}</div>`, "BABD pushes the task's branch, opens the PR with the report, follows its CI checks, and merges it. The token goes to .env.")}
      ${field("Agent isolation", select("p_isolation", p.isolation || "none", [["none", "None: agents run as BABD's user (guard rules only)"], ["bwrap", "bwrap: each agent isolated (recommended; apt install bubblewrap)"], ["docker", "Docker (Hermes agents' commands)"]]), "For every agent that does not set its own sandbox. bwrap: system and BABD read-only, only the task's folder writable, .env / runs / logs / secrets hidden, BABD's processes invisible.")}
      ${field("Skill texts in prompts", select("p_skills_mode", p.skills_mode || "full", [["full", "Full text (most reliable, most tokens)"], ["lean", "Lean: the start of each skill (~70% fewer skill tokens)"]]))}</div>
    <label class="check"><input type="checkbox" id="p_evidence" ${p.require_evidence ? "checked" : ""}> A QA PASS needs evidence (the project's tests passing, or QA's commands and outputs); without it the verdict is FAIL</label>
    ${field("QA fix rounds", `<input type="number" id="p_rounds" min="0" max="5" value="${esc(p.max_fix_rounds ?? 2)}">`, "How many times a failed QA report goes back to the Developer before the run is blocked.")}
    ${field("Continue rounds", `<input type="number" id="p_controunds" min="0" max="5" value="${esc(p.max_continue_rounds ?? 2)}">`, "When an agent runs out of its step (iteration) budget, how many times the Team Lead asks it to continue from its partial summary before the run is blocked.")}
    <div class="field"><label>Parallel work</label>
      ${field("Tasks at the same time", `<input type="number" id="p_tasks" min="1" max="10" value="${esc(p.max_parallel_tasks ?? 3)}">`, "More tasks wait in the queue. A task waiting for your approval does not count.")}
      <label class="check"><input type="checkbox" id="p_prep" ${(p.parallel_prep ?? true) ? "checked" : ""}> While the Developer builds, QA writes the test plan and DevOps prepares the deploy</label>
      <label class="check"><input type="checkbox" id="p_fast" ${(p.fast_lane ?? true) ? "checked" : ""}> ⚡ Fast lane: the Team Lead first decides who is needed; quick jobs (a command, a key, a config change) go straight to one agent instead of the whole team</label>
      <div class="help">How many steps each agent runs at once is set per agent (Configure → Role → Parallel steps).</div></div>
    <div class="field"><label>GBrain team memory</label>
      <label class="check"><input type="checkbox" id="g_enabled" ${(p.gbrain?.enabled ?? true) ? "checked" : ""}> Every agent reads gbrain before a task and writes to it after</label>
      <label class="check"><input type="checkbox" id="g_strict" ${(p.gbrain?.strict ?? true) ? "checked" : ""}> Stop the agent step when gbrain can't be read or written</label>
      <label class="check"><input type="checkbox" id="g_cloud" ${p.gbrain?.allow_cloud ? "checked" : ""}> Allow gbrain to use cloud API keys (off = memory stays on this machine)</label>
    </div>
    <div class="help">Brain: ${esc(S.brain?.home || "")} · ${S.brain?.brain ? "ready" : "not set up yet (Set up all)"}</div>
    ${PACKS().map((k) => `<div class="field"><label>${esc(k.title)} (${esc(k.source)})</label>
      <label class="check"><input type="checkbox" id="pk_en_${k.key}" ${(p[k.key]?.enabled ?? true) ? "checked" : ""}> Agents use their ${esc(k.title)} on every step they apply to</label>
      <label class="check"><input type="checkbox" id="pk_enf_${k.key}" ${(p[k.key]?.enforce ?? true) ? "checked" : ""}> Ask an agent to redo a step once when its answer skips one of these skills</label></div>`).join("")}
    <div class="field"><label>Telegram: CEO bot</label>
      <div class="help">Send the bot a goal, a .md file or a link: it becomes a task. Approvals arrive with Approve / Reject buttons. Create a bot with @BotFather and paste its token.</div>
      <label class="check"><input type="checkbox" id="tg_enabled" ${S.telegram?.ceo?.enabled ? "checked" : ""}> CEO bot on</label>
      <div class="row2"><input type="text" id="tg_username" value="${esc(S.telegram?.ceo?.bot_username || "")}" placeholder="@my_ceo_bot">
        <input type="password" id="tg_token" placeholder="${S.telegram?.ceo?.token_set ? "•••••••• token set — type to replace" : "bot token from @BotFather"}" autocomplete="new-password"></div>
      <input type="text" id="tg_users" value="${esc((S.telegram?.ceo?.allowed_users || []).join(", "))}" placeholder="Allowed Telegram users: numeric ids or @usernames, comma separated">
      <div class="help">Only these users can use the CEO bot and the agent bots. Anyone else who writes to a bot is told their id, so you can add it here. Prefer numeric ids: a @username is tied to the first account that uses it.</div>
      <label class="check"><input type="checkbox" id="tg_groups" ${S.telegram?.ceo?.allow_groups ? "checked" : ""}> Also answer in group chats (everyone in the group reads the replies and reports)</label>
      <div class="tg-notify">${(S.telegram?.notify_options || []).map((n) => `<label class="check"><input type="checkbox" name="tg_notify" value="${esc(n)}" ${(S.telegram?.ceo?.notify || S.telegram?.notify_options || []).includes(n) ? "checked" : ""}> ${esc(n)}</label>`).join("")}
        <label class="project-pick">Daily report at <input type="number" id="tg_hour" min="0" max="23" value="${esc(S.telegram?.ceo?.daily_report_hour ?? 18)}" style="width:64px">:00</label></div>
      ${tgInitBlock("ceo")}
      ${tgStatus("ceo")}
      <div class="row"><button type="button" class="btn small" id="tgSave">Save Telegram</button></div></div>
    <div class="field"><label>Projects (where the agents work)</label>
      <div class="help">Each task works in its own git branch of the chosen project, outside the BABD installation. When the task ends BABD commits the work and merges it (by the merge rule) into the project's branch.</div>
      <div class="proj-list" id="projList">${(S.projects || []).map((pr) => projectRow(pr)).join("")}</div>
      <div class="row"><button type="button" class="btn small" id="projAdd">+ Add project</button>
        <label class="project-pick">Default <select id="projDefault">${(S.projects || []).map((pr) => `<option value="${esc(pr.id)}" ${pr.id === S.default_project ? "selected" : ""}>${esc(pr.name)}</option>`).join("")}</select></label>
        <button type="button" class="btn small primary" id="projSave">Save projects</button></div></div>
    <div class="field"><label>Scheduled tasks</label>
      <div class="help">A goal that becomes a task on a schedule (this machine's time): e.g. every morning a quick check of a server, every Friday a dependency update.</div>
      <div class="proj-list" id="schList">${(S.schedules || []).map((sc) => scheduleRow(sc)).join("")}</div>
      <div class="row"><button type="button" class="btn small" id="schAdd">+ Add schedule</button>
        <button type="button" class="btn small primary" id="schSave">Save schedules</button></div></div>
    <div class="field"><label>Servers (SSH)</label>
      <div class="help">Servers the agents may reach: a task can just say "server lpnotif". Only the key's path is stored; Generate key makes an ed25519 key on this machine and shows the public key to put in the server's ~/.ssh/authorized_keys. Save first, then Generate key / Test.</div>
      <div class="proj-list" id="srvList">${(S.servers || []).map((sv) => serverRow(sv)).join("")}</div>
      <div class="row"><button type="button" class="btn small" id="srvAdd">+ Add server</button>
        <button type="button" class="btn small primary" id="srvSave">Save servers</button></div></div>
    ${!token ? `<div class="row"><button type="button" class="btn small ghost" id="btnLogout">Sign out</button></div>` : ""}
    <div class="note">Flow: ${S.flow.stages.map((s) => esc(s.label)).join(" → ")}. Specialists only talk to the Team Lead; only the Team Lead reports to the CEO.</div>
    <div style="display:flex;justify-content:flex-end"><button class="btn primary" id="p_save">Save</button></div>`, true);
  if ($("#btnLogout")) $("#btnLogout").onclick = async () => { await fetch("/api/logout", { method: "POST" }); location.reload(); };
  $("[data-tg-init='ceo']").onclick = () => tgInit("ceo", $("#tg_token").value.trim());
  $("#tgSave").onclick = async () => {
    try {
      await api("PUT", "telegram", { enabled: $("#tg_enabled").checked, bot_username: $("#tg_username").value.trim(),
        token: $("#tg_token").value.trim() || undefined, allowed_users: $("#tg_users").value,
        notify: [...document.querySelectorAll('[name="tg_notify"]:checked')].map((c) => c.value), daily_report_hour: Number($("#tg_hour").value),
        allow_groups: $("#tg_groups").checked });
      toast("Telegram saved", "ok"); await refresh(); setTimeout(async () => { await refresh(); }, 2500);
    } catch (err) { toast(err.message, "bad"); }
  };
  $("#schAdd").onclick = () => $("#schList").insertAdjacentHTML("beforeend", scheduleRow({ cron: "daily 07:00", mode: "quick" }, true));
  $("#schList").onclick = async (e) => {
    const rm = e.target.closest("[data-sch-rm]");
    if (rm) { rm.closest(".sch-row").remove(); return; }
    const run = e.target.closest("[data-sch-run]");
    if (run) {
      try { const t = await api("POST", `schedules/${run.dataset.schRun}/run`); toast(`Started: ${t.goal}`, "ok"); refreshSoon(); }
      catch (err) { toast(err.message, "bad"); }
    }
  };
  $("#schSave").onclick = async () => {
    const list = [...document.querySelectorAll("#schList .sch-row")].map((r) => {
      const v = (n) => r.querySelector(`[name="${n}"]`).value.trim();
      return { id: r.dataset.id || undefined, goal: v("sc_goal"), cron: v("sc_cron"), mode: v("sc_mode"), project: v("sc_project"),
        enabled: r.querySelector('[name="sc_enabled"]').checked, auto_approve: r.querySelector('[name="sc_auto"]').checked };
    });
    try { await api("PUT", "schedules", { schedules: list }); toast("Schedules saved", "ok"); await refresh(); $("#btnSettings").click(); }
    catch (err) { toast(err.message, "bad"); }
  };
  $("#srvAdd").onclick = () => $("#srvList").insertAdjacentHTML("beforeend", serverRow({}, true));
  $("#srvList").onclick = async (e) => {
    const rm = e.target.closest("[data-srv-rm]");
    if (rm) { rm.closest(".srv-row").remove(); return; }
    const b = e.target.closest("[data-srv-keygen], [data-srv-test]");
    if (!b) return;
    const id = b.dataset.srvKeygen || b.dataset.srvTest;
    const out = document.querySelector(`[data-srv-out="${CSS.escape(id)}"]`);
    out.classList.remove("hidden"); out.textContent = "…";
    try {
      if (b.dataset.srvKeygen) {
        const r = await api("POST", `servers/${id}/keygen`);
        out.textContent = `${r.hint}:\n\n${r.public_key}`;
      } else {
        const r = await api("POST", `servers/${id}/test`);
        out.textContent = `${r.ok ? "✅ Connected" : "❌ Could not connect"}\n${r.output}`;
      }
    } catch (err) { out.textContent = err.message; }
  };
  $("#srvSave").onclick = async () => {
    const list = [...document.querySelectorAll("#srvList .srv-row")].map((r) => {
      const v = (n) => r.querySelector(`[name="${n}"]`).value.trim();
      return { id: v("sv_id"), name: v("sv_name"), host: v("sv_host"), user: v("sv_user"), port: Number(v("sv_port") || 22),
        key: v("sv_key") || undefined, agents: v("sv_agents").split(/[,\s]+/).filter(Boolean), notes: v("sv_notes") };
    });
    try { await api("PUT", "servers", { servers: list }); toast("Servers saved", "ok"); await refresh(); $("#btnSettings").click(); }
    catch (err) { toast(err.message, "bad"); }
  };
  $("#projAdd").onclick = () => $("#projList").insertAdjacentHTML("beforeend", projectRow({ merge: "on_approval" }, true));
  $("#projList").onclick = (e) => { const rm = e.target.closest("[data-proj-rm]"); if (rm) rm.closest(".proj-row").remove(); };
  $("#projSave").onclick = async () => {
    const rows = [...document.querySelectorAll("#projList .proj-row")].filter((r) => r.dataset.id !== "default" || r.querySelector('[name="pr_repo"]').value || r.querySelector('[name="pr_path"]').value);
    const list = rows.map((r) => {
      const v = (n) => r.querySelector(`[name="${n}"]`).value.trim();
      return { id: r.dataset.id || undefined, name: v("pr_name"), path: v("pr_path"), repo: v("pr_repo"), branch: v("pr_branch"),
        merge: v("pr_merge"), push: r.querySelector('[name="pr_push"]').checked, test_command: v("pr_test") };
    }).filter((p) => p.name || p.repo || p.path);
    try {
      await api("PUT", "projects", { projects: list, default_project: $("#projDefault").value });
      toast("Projects saved", "ok"); await refresh(); $("#btnSettings").click();
    } catch (err) { toast(err.message, "bad"); }
  };
  $("#p_save").onclick = async () => {
    try {
      await api("PUT", "project", { name: $('[name="p_name"]').value, require_approval: $("#p_approval").checked, max_fix_rounds: Number($("#p_rounds").value), max_continue_rounds: Number($("#p_controunds").value),
        max_parallel_tasks: Number($("#p_tasks").value), parallel_prep: $("#p_prep").checked, fast_lane: $("#p_fast").checked,
        retry: { attempts: Number($("#p_retries").value) }, require_evidence: $("#p_evidence").checked,
        budget: { tokens_per_task: Number($("#b_tt").value), cost_per_task: Number($("#b_ct").value), tokens_per_day: Number($("#b_td").value), cost_per_day: Number($("#b_cd").value) },
        skills_mode: $('[name="p_skills_mode"]').value, isolation: $('[name="p_isolation"]').value,
        pr_merge: $('[name="p_pr_merge"]').value, github_token: $("#p_gh_token").value.trim() || undefined,
        gbrain: { enabled: $("#g_enabled").checked, strict: $("#g_strict").checked, allow_cloud: $("#g_cloud").checked },
        ...Object.fromEntries(PACKS().map((k) => [k.key, { enabled: $(`#pk_en_${k.key}`).checked, enforce: $(`#pk_enf_${k.key}`).checked }])) });
      toast("Settings saved", "ok"); closeModal(); refresh();
    } catch (err) { toast(err.message, "bad"); }
  };
});

// ---- task board: every task and what each agent is doing ----------------------------------
let B = null;              // /api/board
let boardOffset = 0;       // server clock minus browser clock (ms)
let boardSpan = 0;         // seconds shown in the activity timeline (0 = fit the recent activity)
let taskFilter = "all";
let historyLimit = 30;     // finished tasks loaded on the board ("Show older tasks" adds more)
let searchResults = null;  // tasks found by the search box (null: not searching)
const openTasks = new Set();
const KIND_LABELS = { plan: "Plan", design: "Design", code: "Build", test_plan: "Test plan", deploy_prep: "Deploy prep",
  test_report: "Test", fix: "Fix", deploy_report: "Deploy", report: "Report" };
const TASK_COLORS = { waiting_answer: "#f0abfc", paused: "#c4b5fd", running: "var(--good)", waiting_approval: "var(--warn)", queued: "#7dd3fc", done: "var(--ceo)", failed: "var(--bad)", cancelled: "var(--dim)", interrupted: "var(--warn)" };
const TASK_LABELS = { waiting_answer: "question for you", paused: "paused", running: "running", waiting_approval: "waiting for you", queued: "queued", done: "done", failed: "failed", cancelled: "stopped", interrupted: "interrupted" };
const RESUMABLE = ["failed", "cancelled", "interrupted"];
const ms = (iso) => (iso ? new Date(iso).getTime() : NaN);
const serverNow = () => Date.now() + boardOffset;
// Jam otoritatif untuk baris activity log. boardOffset = jam server - jam browser
// (di-set di loadBoard()). Kalau offset belum pernah di-set (board belum dimuat),
// nilai 0 berarti "belum tahu" -> kita tandai dan lebih memilih timestamp eksplisit
// dari server (mis. summary.updated_at) daripada jam OS klien.
let serverOffsetKnown = false;
const atNow = () => (boardOffset === 0 && !serverOffsetKnown ? null : (Date.now() + boardOffset)) / 1000;

async function downloadReport(runId) {
  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/report.md`, { headers: { "X-BABD-Token": token } });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `babd-${runId}.md` });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (err) { toast(err.message, "bad"); }
}

let searchTimer = null;
$("#taskSearch").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  searchTimer = setTimeout(async () => {
    if (!q) { searchResults = null; renderTasks(); return; }
    try { searchResults = (await api("GET", `search?q=${encodeURIComponent(q)}&limit=200`)).tasks; renderTasks(); }
    catch (err) { toast(err.message, "bad"); }
  }, 300);
});
$("#btnMoreTasks").addEventListener("click", () => { historyLimit += 50; loadBoard(); });

function fmtTok(n) {
  if (!n) return "0";
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}k` : String(n);
}
function usageText(u, long = false) {
  if (!u || !(u.input || u.output)) return "";
  const tok = `${u.estimated ? "~" : ""}${fmtTok((u.input || 0) + (u.output || 0))} tokens`;
  const cost = u.cost ? ` · $${u.cost.toFixed(u.cost < 1 ? 3 : 2)}${u.cost_unknown ? "+" : ""}` : "";
  return long ? `${tok} (${fmtTok(u.input)} in / ${fmtTok(u.output)} out)${cost}` : tok + cost;
}

function fmtDur(sec) {
  if (sec == null || !isFinite(sec)) return "—";
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, "0")}s`;
  return `${Math.floor(sec / 3600)}h ${String(Math.floor(sec / 60) % 60).padStart(2, "0")}m`;
}
// Timestamp BABD (ISO tanpa offset) = UTC; render di Asia/Jakarta.
const toWib = (iso) => {
  if (iso === null || iso === undefined || iso === "") return null;
  // Backend mengirim `at` sebagai EPOCH DETIK (time.time()), bukan ISO. Angka tidak boleh
  // ditempeli "Z" (-> Invalid Date -> jam kosong). Terima angka = detik/milidetik epoch.
  if (typeof iso === "number") {
    const d = new Date(iso < 1e12 ? iso * 1000 : iso);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (iso instanceof Date) return Number.isNaN(iso.getTime()) ? null : iso;
  let s = String(iso).trim();
  if (!/([zZ]|[+-]\d{2}:?\d{2})$/.test(s)) s += "Z";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
};
// "en-GB" -> "08:25" (titik dua). "id-ID" -> "08.25" (titik) = beda dari jam WIB CEO.
const hhmm = (iso) => toWib(iso)?.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Jakarta" }) ?? "";
const wibNowTime = () => new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "Asia/Jakarta" });
const hhmmISO = (iso) => { const d = toWib(iso); return d ? hhmm(iso) : ""; };
const clock = (t) => hhmm(t);

function setView(v) {
  view = v;
  $("#commandView").classList.toggle("hidden", v !== "command");
  $("#boardView").classList.toggle("hidden", v !== "board");
  $("#logsView").classList.toggle("hidden", v !== "logs");
  $("#reportsView").classList.toggle("hidden", v !== "reports");
  if (v === "logs") loadLog();
  if (v === "reports") loadReports();
  try { localStorage.setItem("babd.view", v); } catch { /* private mode: fine */ }
  renderNav();
  if (v === "board") loadBoard();
  window.scrollTo(0, 0);
}
function renderNav() {
  for (const b of document.querySelectorAll("#views [data-view]")) b.classList.toggle("on", b.dataset.view === view);
  const n = liveList().length + (S?.queue || []).filter((q) => q.status === "queued").length;
  $("#navCount").textContent = n ? n : "";
}
$("#views").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (b) setView(b.dataset.view); });

async function loadBoard() {
  try {
    B = await api("GET", `board?history=${historyLimit}`);
    boardOffset = ms(B.now) - Date.now();
    if (isFinite(boardOffset)) serverOffsetKnown = true;   // jam server kini terkalibrasi
    renderBoard();
  } catch (err) { toast(err.message, "bad"); }
}
let boardTimer = null;
function boardSoon() {
  if (view !== "board") return;
  clearTimeout(boardTimer);
  boardTimer = setTimeout(loadBoard, 400);
}

function renderBoard() {
  if (!B) return;
  const c = B.counts || {};
  const busy = B.agents.filter((a) => a.working.length).length;
  const steps = B.agents.reduce((n, a) => n + a.working.length, 0);
  const tile = (label, value, color, sub = "") => `<div class="tile"><div class="l">${esc(label)}</div><div class="v"${color ? ` style="color:${color}"` : ""}>${value}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>`;
  $("#boardKpis").innerHTML = [
    tile("Running", c.running || 0, c.running ? "var(--good)" : ""),
    tile("Waiting for you", c.waiting_approval || 0, c.waiting_approval ? "var(--warn)" : "", "CEO approval"),
    tile("Queued", c.queued || 0, "", `up to ${B.limits.max_parallel_tasks} at once`),
    tile("Done", c.done || 0),
    tile("Failed / stopped", (c.failed || 0) + (c.cancelled || 0) + (c.interrupted || 0), (c.failed ? "var(--bad)" : ""), c.interrupted ? `${c.interrupted} interrupted` : ""),
    tile("Agents busy", `${busy}<span class="of"> / ${B.agents.length}</span>`, "", `${steps} step(s) in parallel`),
    tile("Used today", `${B.usage_today.estimated ? "~" : ""}${fmtTok(B.usage_today.input + B.usage_today.output)}<span class="of"> tok</span>`, "",
      `${B.usage_today.cost ? `$${B.usage_today.cost.toFixed(2)}${B.usage_today.cost_unknown ? "+" : ""} · ` : ""}${budgetLine()}`),
  ].join("") + (B.budget_block ? `<div class="note warn budget-note">⛔ ${esc(B.budget_block)}</div>` : "");
  $("#boardLimits").textContent = `Up to ${B.limits.max_parallel_tasks} tasks run at the same time; the rest wait in the queue.${B.limits.parallel_prep ? " Inside a task, QA and DevOps prepare while the Developer builds." : ""}`;
  renderLanes();
  renderGantt();
  renderTasks();
}

function budgetLine() {
  const b = B.budget || {};
  const parts = [b.tokens_per_day ? `${fmtTok(b.tokens_per_day)} tok/day` : "", b.cost_per_day ? `$${b.cost_per_day}/day` : ""].filter(Boolean);
  return parts.length ? `budget ${parts.join(", ")}` : "no daily budget";
}

function renderLanes() {
  $("#lanes").innerHTML = B.agents.map((a) => {
    const boxes = Array.from({ length: a.capacity }, (_, i) => `<i class="${i < a.active ? "on" : ""}"></i>`).join("");
    const now = a.working.map((st) => `<div class="now-item"><span class="kind">${esc(KIND_LABELS[st.kind] || st.kind)}</span>
      <span class="goal" title="${esc(st.goal)}">${esc(st.goal)}</span><span class="since" data-since="${esc(st.started_at)}">${fmtDur((serverNow() - ms(st.started_at)) / 1000)}</span></div>`).join("");
    const wait = a.queued.length ? `<div class="lane-wait">${a.queued.length} step(s) waiting for a free slot: ${a.queued.map((st) => esc(`${KIND_LABELS[st.kind] || st.kind} · ${st.goal.slice(0, 30)}`)).join(", ")}</div>` : "";
    return `<div class="lane ${a.working.length ? "busy" : ""}" style="--c:${esc(a.color)}">
      <div class="lane-head"><b>${esc(a.name)}</b><span class="slots" title="${a.active} of ${a.capacity} slots busy">${boxes}</span><span class="muted small">${a.active}/${a.capacity} slots</span></div>
      <div class="lane-now">${now || '<div class="muted small">Idle: ready for the next step</div>'}</div>${wait}
      <div class="lane-stats"><span><b>${a.done}</b> done</span><span>avg <b>${fmtDur(a.avg_seconds)}</b></span><span>busy <b>${fmtDur(a.busy_seconds)}</b></span>${a.failed ? `<span class="bad"><b>${a.failed}</b> failed</span>` : ""}${usageText(a.usage) ? `<span title="${esc(usageText(a.usage, true))}"><b>${esc(usageText(a.usage))}</b></span>` : ""}</div>
    </div>`;
  }).join("");
}

function renderGantt() {
  const box = $("#gantt");
  const W = Math.max(320, box.clientWidth || 900);
  const labelW = W < 560 ? 76 : 110, padR = 12, barH = 12, gap = 2, rowPad = 8, axisH = 22;
  const all = B.tasks.flatMap((t) => (t.steps || []).map((st) => ({ ...st, run: t.id, goal: t.goal })));
  const now = serverNow();
  let end = now;
  let span = boardSpan;
  if (!span) {
    // auto: while tasks run, from their first step to now; when nothing runs, the window of the most recent
    // activity (so finished work does not shrink to a sliver as time passes), at least 1 minute
    const live = new Set(B.tasks.filter((t) => LIVE.includes(t.status)).map((t) => t.id));
    const pool = all.filter((st) => live.has(st.run));
    const recent = all.filter((st) => now - ms(st.finished_at || st.started_at || st.queued_at) < 86400e3);
    if (!pool.length && recent.length) {
      const last = Math.max(...recent.map((st) => ms(st.finished_at || st.started_at || st.queued_at)).filter(isFinite));
      const first = Math.min(...recent.filter((st) => last - ms(st.queued_at || st.started_at) < 6 * 3600e3)
        .map((st) => ms(st.queued_at || st.started_at)).filter(isFinite));
      const pad = Math.max(3e3, (last - first) * 0.05, (60e3 - (last - first)) / 2);  // the work in the middle
      end = Math.min(now, last + pad);
      span = (end - (first - pad)) / 1000;
    } else {
      const firsts = (pool.length ? pool : all).map((st) => ms(st.queued_at || st.started_at)).filter((t) => isFinite(t) && now - t < 86400e3);
      span = Math.max(60, Math.min(86400, ((now - Math.min(now - 60e3, ...firsts)) / 1000) * 1.08));
    }
  }
  const start = end - span * 1000;
  const x = (t) => labelW + ((Math.max(start, Math.min(end, t)) - start) / (end - start)) * (W - labelW - padR);
  let y = axisH;
  const rows = B.agents.map((a) => {
    const items = all.filter((st) => st.agent === a.id).map((st) => {
      const q = ms(st.queued_at), b = ms(st.started_at), f = ms(st.finished_at);
      const from = isFinite(q) ? q : b;
      const open = ["working", "queued"].includes(st.status);  // only these may still grow to "now"
      const to = isFinite(f) ? f : open ? end : (isFinite(b) ? b : from);
      return { st, from, b, to };
    }).filter((it) => isFinite(it.from) && it.to >= start).sort((p, q) => p.from - q.from);
    const laneEnds = [];
    for (const it of items) {  // parallel steps of one agent go on separate lines
      let lane = laneEnds.findIndex((e) => e <= it.from);
      if (lane < 0) { lane = laneEnds.length; laneEnds.push(0); }
      laneEnds[lane] = it.to;
      it.lane = lane;
    }
    const h = Math.max(1, laneEnds.length) * (barH + gap) - gap + rowPad * 2;
    const top = y;
    y += h;
    const marks = items.map((it) => {
      const by = top + rowPad + it.lane * (barH + gap);
      const st = it.st;
      const tip = `<b>${esc(KIND_LABELS[st.kind] || st.kind)}</b> · ${esc(nameOf(st.agent))}<br>${esc(st.goal)}<br>${esc(st.status)}${st.started_at ? ` · ${clock(it.b)}` : ""}${st.seconds != null ? ` · took ${fmtDur(st.seconds)}` : st.status === "working" ? ` · ${fmtDur((end - it.b) / 1000)} so far` : ""}${isFinite(it.b) && it.b - it.from > 1500 ? `<br>waited ${fmtDur((it.b - it.from) / 1000)} for a slot` : ""}`;
      const waitTo = isFinite(it.b) ? it.b : end;
      const waitEl = waitTo - it.from > 1500 ? `<line class="g-wait" x1="${x(it.from)}" x2="${x(waitTo)}" y1="${by + barH / 2}" y2="${by + barH / 2}"/>` : "";
      if (!isFinite(it.b) && st.status !== "queued") return "";  // never started (e.g. stopped while waiting)
      if (!isFinite(it.b)) return `<g data-tip="${esc(tip)}" data-run="${esc(st.run)}">${waitEl}<rect class="g-hit" x="${x(it.from)}" y="${by - 2}" width="${Math.max(6, x(end) - x(it.from))}" height="${barH + 4}"/></g>`;
      const bx = x(it.b), bw = Math.max(4, x(it.to) - bx);
      return `<g data-tip="${esc(tip)}" data-run="${esc(st.run)}">${waitEl}<rect class="g-bar ${esc(st.status)}" x="${bx}" y="${by}" width="${bw}" height="${barH}" rx="3" style="fill:${esc(a.color)}"/>
        <rect class="g-hit" x="${bx - 2}" y="${by - 2}" width="${bw + 4}" height="${barH + 4}"/></g>`;
    }).join("");
    return `<line class="g-row" x1="0" x2="${W}" y1="${top + h}" y2="${top + h}"/>
      <text class="g-label" x="0" y="${top + h / 2 + 4}" style="fill:${esc(a.color)}">${esc(a.name)}</text>${marks}`;
  });
  const steps = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600];
  const stepS = steps.find((s) => span / s <= (W < 560 ? 4 : 7)) || 21600;
  const ticks = [];
  for (let t = Math.ceil(start / (stepS * 1000)) * stepS * 1000; t <= end; t += stepS * 1000) {
    ticks.push(`<line class="g-grid" x1="${x(t)}" x2="${x(t)}" y1="${axisH - 4}" y2="${y}"/><text class="g-tick" x="${x(t)}" y="12" text-anchor="middle">${stepS < 60 ? new Date(t).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: "Asia/Jakarta" }) : clock(t)}</text>`);
  }
  box.innerHTML = `<svg width="${W}" height="${y + 2}" viewBox="0 0 ${W} ${y + 2}" role="img" aria-label="When each agent worked on which task">
    ${ticks.join("")}${rows.join("")}${end >= now - 1000 ? `<line class="g-now" x1="${x(end)}" x2="${x(end)}" y1="${axisH - 4}" y2="${y}"/>` : ""}</svg>
    ${all.some((st) => ms(st.finished_at || st.started_at || st.queued_at) >= start || st.status === "working") ? "" : '<div class="gantt-empty muted small">No agent work in this time range yet.</div>'}`;
}

function stageTrack(t) {
  return `<div class="stage-track" aria-hidden="true">${B.stages.map((s) => `<i class="${esc(t.stages?.[s.key] || "todo")}" title="${esc(s.label)}"></i>`).join("")}</div>`;
}

function renderTasks() {
  if (typingAnswer()) { setTimeout(renderTasks, 1500); return; }
  const order = { running: 0, waiting_approval: 0, queued: 1 };
  const shownTasks = (searchResults || B.tasks).filter((t) => taskFilter === "all"
    || (taskFilter === "active" && LIVE.includes(t.status))
    || (taskFilter === "queued" && t.status === "queued")
    || (taskFilter === "done" && t.status === "done")
    || (taskFilter === "problem" && RESUMABLE.includes(t.status)))
    .sort((a, b) => (order[a.status] ?? 2) - (order[b.status] ?? 2)
      || (a.status === "queued" ? (a.position || 0) - (b.position || 0) : (b.started_at || b.queued_at || "").localeCompare(a.started_at || a.queued_at || "")));
  $("#btnMoreTasks").classList.toggle("hidden", !!searchResults || B.tasks.filter((t) => ![...LIVE, "queued"].includes(t.status)).length < historyLimit);
  if (!shownTasks.length) { $("#taskList").innerHTML = `<div class="empty">${searchResults ? "No task matches the search." : "No tasks here yet. Add some above."}</div>`; return; }
  $("#taskList").innerHTML = shownTasks.map((t) => {
    const live = LIVE.includes(t.status);
    const startedMs = ms(t.started_at), endMs = t.finished_at ? ms(t.finished_at) : serverNow();
    const working = (t.steps || []).filter((st) => st.status === "working");
    const waiting = (t.steps || []).filter((st) => st.status === "queued");
    const now = [...working.map((st) => `<span class="who-chip" style="--c:${colorOf(st.agent)}">${esc(nameOf(st.agent))} · ${esc(KIND_LABELS[st.kind] || st.kind)}</span>`),
      ...waiting.map((st) => `<span class="who-chip wait" style="--c:${colorOf(st.agent)}">${esc(nameOf(st.agent))} · waiting for a slot</span>`)].join("");
    const meta = t.status === "queued" ? `#${t.position} in the queue · added ${clock(ms(t.queued_at))}`
      : `${t.resume ? "resume · " : ""}${esc(t.id)} · ${usageText(t.usage) ? `${esc(usageText(t.usage))} · ` : ""}started ${clock(startedMs)} · ${live ? `<span data-since="${esc(t.started_at)}">${fmtDur((endMs - startedMs) / 1000)}</span>` : `took ${fmtDur((endMs - startedMs) / 1000)}`}`;
    const open = openTasks.has(t.id);
    const stepRows = (t.steps || []).map((st) => {
      const waited = st.started_at ? (ms(st.started_at) - ms(st.queued_at)) / 1000 : null;
      return `<tr><td><span class="dot" style="background:${colorOf(st.agent)}"></span>${esc(nameOf(st.agent))}</td><td>${esc(KIND_LABELS[st.kind] || st.kind)}</td>
        <td>${pill(st.status, STATUS_COLORS[st.status] || (st.status === "failed" ? "var(--bad)" : "var(--dim)"), st.status === "working")}${st.retries ? ` <span class="muted" title="${esc(st.last_error || "")}">↻ ${st.retries}</span>` : ""}${st.fallback ? ` <span class="muted" title="${esc(st.last_error || "")}">fallback ${esc(st.fallback)}</span>` : ""}</td>
        <td>${waited != null && waited >= 1 ? fmtDur(waited) : "—"}</td><td title="${esc(usageText(st.usage, true))}">${esc(usageText(st.usage)) || "—"}</td><td>${st.seconds != null ? fmtDur(st.seconds) : st.status === "working" ? `<span data-since="${esc(st.started_at)}"></span>` : "—"}</td></tr>`;
    }).join("");
    return `<article class="task" data-task="${esc(t.id)}">
      <div class="task-row">
        <button type="button" class="task-toggle" data-toggle="${esc(t.id)}" aria-expanded="${open}" aria-label="Show steps">${open ? "▾" : "▸"}</button>
        <div class="task-title"><div class="goal">${t.documents?.length ? "📄 " : ""}${esc(t.goal)}</div><div class="muted small">${meta}${routeLabel(t)}${t.task_options?.skip?.length ? ` · no ${t.task_options.skip.map(esc).join(", no ")}` : ""}${Object.keys(t.task_options?.models || {}).length ? ` · ${Object.entries(t.task_options.models).map(([a, m]) => `${esc(nameOf(a))}: ${esc(m)}`).join(", ")}` : ""}${t.evidence ? ` · ${t.evidence.verified ? "✓ verified" : "unverified"}` : ""}${t.workspace?.name || t.project ? ` · 📁 ${esc(t.workspace?.name || projectName(t.project))}` : ""}${t.workspace?.result?.merged ? " · merged" : ""}${prLabel(t.workspace?.result?.pr)}${t.documents?.length ? ` · ${t.documents.map((d) => esc(d.name)).join(", ")}` : ""}</div></div>
        <div class="task-status">${pill(TASK_LABELS[t.status] || t.status, TASK_COLORS[t.status] || "var(--dim)", t.status === "running")}</div>
        <div class="task-progress">${t.status === "queued" ? '<span class="muted small">not started</span>' : `${stageTrack(t)}<span class="pct">${t.progress ?? 0}%</span>`}</div>
        ${t.question ? questionCard(t.id, t.question) : ""}
        <div class="task-now">${now || (t.waiting_ceo ? '<span class="muted small">QA passed · waiting for your approval to deploy</span>' : live ? '<span class="muted small">between steps</span>' : "")}</div>
        <div class="task-actions">
          ${t.status !== "queued" ? `<button type="button" class="btn small" data-open="${esc(t.id)}">Open</button><button type="button" class="btn small ghost" data-report="${esc(t.id)}" title="The full report of this task">Report</button>` : ""}
          ${t.status !== "queued" && !LIVE.includes(t.status) ? `<button type="button" class="btn small ghost" data-export="${esc(t.id)}" title="Download the task as a Markdown report">Export</button>` : ""}
          ${t.waiting_ceo ? `<button type="button" class="btn small good" data-approve-task="${esc(t.id)}">Approve deploy</button><button type="button" class="btn small danger" data-reject-task="${esc(t.id)}">Reject</button>` : ""}
          ${t.status === "running" || (live && t.paused === false && t.status !== "paused" && t.status !== "waiting_approval") ? `<button type="button" class="btn small ghost" data-pause="${esc(t.id)}" title="The steps already working finish; the next ones wait">⏸ Pause</button>` : ""}
          ${t.status === "paused" || (live && t.paused) ? `<button type="button" class="btn small good" data-unpause="${esc(t.id)}">▶ Resume</button>` : ""}
          ${live || t.status === "queued" ? `<button type="button" class="btn small ghost" data-cancel="${esc(t.id)}">${t.status === "queued" ? "Remove" : "⏹ Stop"}</button>` : ""}
          ${RESUMABLE.includes(t.status) ? `<button type="button" class="btn small" data-resume="${esc(t.id)}" title="Continue from the last finished step">Resume</button>` : ""}
        </div>
      </div>
      ${t.error ? `<div class="note warn">${esc(t.error)}</div>` : ""}
      ${open && t.documents?.length && t.status !== "queued" ? docChips(t.documents, t.id) : ""}
      ${open ? workspaceLine(t.workspace) + evidenceLine(t) : ""}
      ${open ? `<div class="task-steps">${stepRows ? `<table><thead><tr><th>Agen</th><th>Langkah</th><th>Status</th><th>Menunggu</th><th>Token</th><th>Durasi</th></tr></thead><tbody>${stepRows}</tbody></table>` : '<div class="muted small">Belum ada langkah.</div>'}</div>` : ""}
    </article>`;
  }).join("");
}

$("#boardView").addEventListener("click", async (e) => {
  const t = (sel) => e.target.closest(sel);
  if (t("[data-span]")) {
    boardSpan = Number(t("[data-span]").dataset.span);
    for (const b of document.querySelectorAll("#spanSeg button")) b.classList.toggle("on", b === t("[data-span]"));
    renderGantt();
  } else if (t("[data-filter]")) {
    taskFilter = t("[data-filter]").dataset.filter;
    for (const b of document.querySelectorAll("#taskFilter button")) b.classList.toggle("on", b === t("[data-filter]"));
    renderTasks();
  } else if (t("[data-toggle]")) {
    const id = t("[data-toggle]").dataset.toggle;
    openTasks.has(id) ? openTasks.delete(id) : openTasks.add(id);
    renderTasks();
  } else if (t("[data-run]")) {
    const id = t("[data-run]").dataset.run;
    openTasks.add(id);
    taskFilter = "all";
    for (const b of document.querySelectorAll("#taskFilter button")) b.classList.toggle("on", b.dataset.filter === "all");
    renderTasks();
    document.querySelector(`[data-task="${CSS.escape(id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  } else if (t("[data-open]")) {
    const id = t("[data-open]").dataset.open;
    const key = liveRuns[id] && isLive(liveRuns[id]) ? `live:${id}` : id;
    setView("command");
    renderHistory();
    $("#runHistory").value = key;
    await showRun(key);
  } else if (t("[data-approve-task]") || t("[data-reject-task]")) {
    const ok = !!t("[data-approve-task]");
    const id = (t("[data-approve-task]") || t("[data-reject-task]")).dataset[ok ? "approveTask" : "rejectTask"];
    try { await api("POST", `runs/${id}/approve`, { approved: ok }); toast(ok ? "Deploy approved" : "Deploy rejected", ok ? "ok" : ""); boardSoon(); }
    catch (err) { toast(err.message, "bad"); }
  } else if (t("[data-export]")) {
    downloadReport(t("[data-export]").dataset.export);
  } else if (t("[data-pause]") || t("[data-unpause]")) {
    const el = t("[data-pause]") || t("[data-unpause]");
    const id = el.dataset.pause || el.dataset.unpause;
    try { const r = await api("POST", `runs/${id}/${el.dataset.pause ? "pause" : "resume"}`); toast(r.note || (r.goal ? `Continuing: ${r.goal}` : "ok"), "ok"); boardSoon(); refreshSoon(); }
    catch (err) { toast(err.message, "bad"); }
  } else if (t("[data-resume]")) {
    try { const r = await api("POST", `runs/${t("[data-resume]").dataset.resume}/resume`); toast(`Resuming: ${r.goal}`, "ok"); boardSoon(); refreshSoon(); }
    catch (err) { toast(err.message, "bad"); }
  } else if (t("[data-cancel]")) {
    try { const r = await api("POST", `runs/${t("[data-cancel]").dataset.cancel}/cancel`); toast(r.note); boardSoon(); refreshSoon(); }
    catch (err) { toast(err.message, "bad"); }
  }
});

$("#btnAddTasks").addEventListener("click", async () => {
  const lines = $("#taskGoals").value.split("\n").map((g) => g.trim()).filter(Boolean);
  const att = attachments.board;
  const goals = lines.filter((l) => !isLink(l));
  const links = [...att.links, ...lines.filter(isLink)];
  if (!goals.length && !att.docs.length && !links.length) { toast("Write at least one task, or attach .md task files", "bad"); $("#taskGoals").focus(); return; }
  try {
    $("#btnAddTasks").disabled = true;
    const r = await api("POST", "tasks", { goals, auto_approve: $("#taskAutoApprove").checked,
      documents: att.docs.map((d) => ({ name: d.name, content: d.content })), links, project: $("#taskProject").value || undefined, options: readOptions("board") })
      .finally(() => { $("#btnAddTasks").disabled = false; });
    const started = r.tasks.filter((t) => t.status !== "queued").length;
    toast(`${r.tasks.length} task(s) added: ${started} started, ${r.tasks.length - started} queued`, "ok");
    $("#taskGoals").value = "";
    clearAttach("board");
    refreshSoon(); boardSoon();
  } catch (err) { toast(err.message, "bad"); }
});

// hover tooltips for the timeline (delegated, so they survive re-renders)
$("#gantt").addEventListener("mousemove", (e) => {
  const g = e.target.closest("[data-tip]");
  const tip = $("#tip");
  if (!g) { tip.classList.add("hidden"); return; }
  tip.innerHTML = g.dataset.tip;
  tip.classList.remove("hidden");
  const r = tip.getBoundingClientRect();
  tip.style.left = `${Math.min(window.innerWidth - r.width - 8, e.clientX + 14)}px`;
  tip.style.top = `${Math.max(8, e.clientY - r.height - 12)}px`;
});
$("#gantt").addEventListener("mouseleave", () => $("#tip").classList.add("hidden"));
window.addEventListener("resize", () => { if (view === "board" && B) renderGantt(); });

setInterval(() => {  // live clocks: elapsed times tick and running bars grow
  if (view !== "board" || !B) return;
  for (const el of document.querySelectorAll("#boardView [data-since]")) el.textContent = fmtDur((serverNow() - ms(el.dataset.since)) / 1000);
  renderGantt();
}, 1000);

// ---- task documents: .md files (attach or drop) and links ----------------------------------
const MAX_DOC_BYTES = 500_000;
const DOC_EXT = /\.(md|markdown|mdown|txt|text|rst)$/i;
const attachments = { command: { docs: [], links: [] }, board: { docs: [], links: [] } };
const isLink = (t) => /^https?:\/\/\S+$/i.test(t.trim());

async function addFiles(which, files) {
  for (const f of files) {
    if (!DOC_EXT.test(f.name)) { toast(`${f.name}: send a Markdown or text file (.md, .txt)`, "bad"); continue; }
    if (f.size > MAX_DOC_BYTES) { toast(`${f.name}: larger than ${MAX_DOC_BYTES / 1000} KB`, "bad"); continue; }
    const content = await f.text();
    if (!content.trim()) { toast(`${f.name}: the file is empty`, "bad"); continue; }
    const list = attachments[which].docs;
    const i = list.findIndex((d) => d.name === f.name);
    if (i >= 0) list.splice(i, 1);
    list.push({ name: f.name, content, title: docTitle(content, f.name) });
  }
  renderAttach(which);
}

function docTitle(text, fallback) {  // same rule as the server: first heading, else first line
  const fm = text.match(/^---\n([\s\S]*?)\n---\n/);
  const t = fm && fm[1].match(/^title:\s*['"]?(.+?)['"]?\s*$/m);
  if (t) return t[1].slice(0, 120);
  const body = fm ? text.slice(fm[0].length) : text;
  for (const line of body.split("\n")) {
    const t = line.trim().replace(/^#{1,6}\s+/, "").replace(/^[\s#*_`]+|[\s#*_`]+$/g, "");
    if (t) return t.slice(0, 120);
  }
  return fallback.replace(/\.[^.]+$/, "");
}

function addLink(which, url) {
  url = url.trim();
  if (!isLink(url)) { toast("Paste a full link starting with http:// or https://", "bad"); return false; }
  if (!attachments[which].links.includes(url)) attachments[which].links.push(url);
  renderAttach(which);
  return true;
}

function renderAttach(which) {
  const a = attachments[which];
  const fmtKB = (n) => (n < 1000 ? `${n} B` : `${(n / 1000).toFixed(1)} KB`);
  document.querySelector(`[data-list="${which}"]`).innerHTML = [
    ...a.docs.map((d, i) => `<span class="doc-chip" title="${esc(d.title)}">📄 <b>${esc(d.name)}</b><span class="muted">${esc(d.title)} · ${fmtKB(new Blob([d.content]).size)}</span><button type="button" data-rm-doc="${which}:${i}" aria-label="Remove ${esc(d.name)}">×</button></span>`),
    ...a.links.map((u, i) => `<span class="doc-chip" title="${esc(u)}">🔗 <b>${esc(u.replace(/^https?:\/\//, "").slice(0, 60))}</b><span class="muted">read when the task starts</span><button type="button" data-rm-link="${which}:${i}" aria-label="Remove link">×</button></span>`),
  ].join("");
}

function clearAttach(which) { attachments[which] = { docs: [], links: [] }; renderAttach(which); }

for (const box of document.querySelectorAll("[data-attach]")) {
  const which = box.dataset.attach;
  box.querySelector("[data-file]").addEventListener("change", async (e) => { await addFiles(which, [...e.target.files]); e.target.value = ""; });
  const input = box.querySelector("[data-link-input]");
  box.querySelector("[data-add-link]").addEventListener("click", () => { if (addLink(which, input.value)) input.value = ""; });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (addLink(which, input.value)) input.value = ""; } });
  box.addEventListener("click", (e) => {
    const d = e.target.closest("[data-rm-doc]"), l = e.target.closest("[data-rm-link]");
    if (d) { attachments[which].docs.splice(Number(d.dataset.rmDoc.split(":")[1]), 1); renderAttach(which); }
    if (l) { attachments[which].links.splice(Number(l.dataset.rmLink.split(":")[1]), 1); renderAttach(which); }
  });
  const zone = box.closest(".card");
  zone.addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); zone.classList.add("dropping"); } });
  zone.addEventListener("dragleave", (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove("dropping"); });
  zone.addEventListener("drop", async (e) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    zone.classList.remove("dropping");
    await addFiles(which, [...e.dataTransfer.files]);
  });
}

// ---- task templates -----------------------------------------------------------------------
let TEMPLATES = null;
async function templateModal(which) {
  try { TEMPLATES = (await api("GET", "templates")).templates; } catch (err) { toast(err.message, "bad"); return; }
  if (!TEMPLATES.length) { toast("No templates in templates/tasks yet", "bad"); return; }
  openModal("Task from a template", `
    <div class="note">Pick a template, fill in the &lt;…&gt; parts, then use it: it becomes this task's document${which === "board" ? " (a task of its own)" : ""}.</div>
    <div class="tpl-pick">${TEMPLATES.map((t, i) => `<button type="button" class="tpl ${i ? "" : "on"}" data-tpl="${esc(t.id)}"><b>${esc(t.title)}</b><span>${esc(t.description)}</span></button>`).join("")}</div>
    <textarea id="tplBody" rows="16" spellcheck="true"></textarea>
    <div class="row tpl-actions">
      <input type="text" id="tplSaveId" placeholder="save as template id, e.g. my-feature">
      <button type="button" class="btn small ghost" id="tplSave">Save as template</button>
      <div class="spacer"></div>
      <button type="button" class="btn primary" id="tplUse">Use this task</button>
    </div>`);
  const show = (id) => {
    const t = TEMPLATES.find((x) => x.id === id);
    $("#tplBody").value = t.body;
    for (const b of document.querySelectorAll("[data-tpl]")) b.classList.toggle("on", b.dataset.tpl === id);
  };
  show(TEMPLATES[0].id);
  $("#modalBody").querySelector(".tpl-pick").onclick = (e) => { const b = e.target.closest("[data-tpl]"); if (b) show(b.dataset.tpl); };
  $("#tplUse").onclick = () => {
    const text = $("#tplBody").value.trim();
    if (!text) { toast("The task is empty", "bad"); return; }
    const title = docTitle(text, "task");
    const name = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "task"}.md`;
    attachments[which].docs.push({ name, content: text, title });
    renderAttach(which);
    closeModal();
    toast(which === "board" ? "Added: press Add to queue" : "Attached: press Run team", "ok");
  };
  $("#tplSave").onclick = async () => {
    const id = $("#tplSaveId").value.trim();
    try {
      await api("POST", "templates", { id, title: docTitle($("#tplBody").value, id), body: $("#tplBody").value });
      toast(`Template ${id} saved`, "ok");
    } catch (err) { toast(err.message, "bad"); }
  };
}
document.addEventListener("click", (e) => { const b = e.target.closest("[data-template]"); if (b) templateModal(b.dataset.template); });

async function viewDocument(runId) {
  try {
    const r = await api("GET", `runs/${runId}/document`);
    openModal("Task document", `<pre class="doc-view">${esc(r.text)}</pre>`);
  } catch (err) { toast(err.message, "bad"); }
}

const projectName = (id) => (S.projects || []).find((p) => p.id === id)?.name || id;

function evidenceLine(r) {
  const ev = r.evidence;
  const t = (r.tests || []).slice(-1)[0];
  if (!ev && !t) return "";
  return `<div class="ws-line">🧪 ${ev ? `<b class="${ev.verified ? "ok-text" : "warn-text"}">${ev.verified ? "verified" : "not verified"}</b> · ${esc(ev.note || "")}` : ""}${t && !ev ? `tests: <code>${esc(t.command)}</code> exit ${esc(t.exit)}` : ""}</div>`;
}

function workspaceLine(ws) {
  if (!ws?.name) return "";
  const r = ws.result;
  const res = !r ? (ws.branch ? `working on <code>${esc(ws.branch)}</code>` : "preparing the workspace")
    : r.merged ? `merged into <code>${esc(ws.base)}</code> (${r.files} file(s), ${esc(r.commit || "")})${r.pushed ? " · pushed" : ""}`
    : r.commit ? `on branch <code>${esc(ws.branch)}</code> (${esc(r.commit)})` : "";
  const written = (ws.files_written || []).length ? ` · BABD wrote ${ws.files_written.length} file(s) for agents without tools` : "";
  return `<div class="ws-line" title="${esc(ws.dir || "")}">📁 <b>${esc(ws.name)}</b> · ${res}${r?.note ? ` · <span class="muted">${esc(r.note)}</span>` : ""}${written}</div>`;
}

function docChips(docs, runId) {
  if (!docs?.length) return "";
  return `<div class="doc-chips">${docs.map((d) => `<span class="doc-chip small" title="${esc(d.url || d.name)}">${d.source === "link" ? "🔗" : "📄"} <b>${esc(d.name)}</b></span>`).join("")}${runId ? `<button type="button" class="linkish" data-view-doc="${esc(runId)}">View document</button>` : ""}</div>`;
}
document.addEventListener("click", (e) => { const b = e.target.closest("[data-view-doc]"); if (b) viewDocument(b.dataset.viewDoc); });

// ---- live events -------------------------------------------------------------------------
function connect() {
  const es = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);
  es.addEventListener("log", (e) => { const d = JSON.parse(e.data); logLine(d.source, d.msg, /fail|error/i.test(d.msg) ? "bad" : "", d.at); });
  es.addEventListener("job", (e) => onJob(JSON.parse(e.data)));
  es.addEventListener("memory", (e) => { const m = JSON.parse(e.data); flashMemory(m.agent, m.op); logLine("gbrain", memoryLogText(nameOf(m.agent), m), "", atNow()); });
  es.addEventListener("config", () => refreshSoon());
  es.addEventListener("approval", (e) => { toast(`Butuh persetujuan: ${JSON.parse(e.data).question}`); boardSoon(); });
  es.addEventListener("tasks", () => { refreshSoon(); boardSoon(); });
  es.addEventListener("agentlog", (e) => onAgentLog(JSON.parse(e.data)));
  es.addEventListener("run", (e) => {
    const d = JSON.parse(e.data);
    // Timestamp otoritatif dari SERVER (ringkasan run) — jangan jam klien.
    const evAt = (d.summary && d.summary.updated_at) || atNow();
    liveRuns[d.summary.id] = d.summary;
    reportLive(d.summary);
    if (!S.run || d.summary.id === S.run.id || (d.summary.started_at || "") >= (S.run.started_at || "")) S.run = d.summary;
    if (!viewingHistory) viewRun = pinnedRun ? liveRuns[pinnedRun] || viewRun : S.run;
    if (viewRun && viewRun.id === d.summary.id) viewRun = d.summary;
    boardSoon();
    if (d.event === "message") logLine("flow", `${nameOf(d.data.from)} → ${nameOf(d.data.to)}: ${d.data.kind}`, "", evAt);
    if (d.event === "memory") flashMemory(d.data.agent, d.data.op);
    if (d.event === "route") logLine("route", `${d.data.route === "answer" ? "Team Lead answers directly" : d.data.route === "direct" ? "⚡ fast lane → " + nameOf(d.data.agent) : "team: " + (d.data.agents || []).map(nameOf).join(", ")}${d.data.reason ? " (" + d.data.reason + ")" : ""}`, "ok", evAt);
    if (d.event === "question") { toast(`${nameOf(d.data.agent)} asks: ${d.data.question}`); logLine("question", `${nameOf(d.data.agent)} asks: ${d.data.question}`, "bad", evAt); boardSoon(); }
    if (d.event === "package") logLine("package", `${d.data.id} ${d.data.title} · ${nameOf(d.data.agent)}: ${d.data.status}`, d.data.status === "failed" ? "bad" : "ok", evAt);
    if (d.event === "paused" || d.event === "unpaused") { logLine("task", d.event === "paused" ? "paused" : "continuing", "", evAt); refreshSoon(); boardSoon(); }
    if (d.event === "skills") logLine("skills", `${nameOf(d.data.agent)}: ${d.data.missing.length ? "skipped " + d.data.missing.join(", ") : "applied " + d.data.skills.join(", ")}`, d.data.missing.length ? "bad" : "ok", evAt);
    if (d.event === "memory") logLine("gbrain", memoryLogText(nameOf(d.data.agent), d.data), "", evAt);
    if (d.event === "retry") logLine("retry", `${nameOf(d.data.agent)} ${d.data.kind}: ${d.data.fallback ? `trying fallback model ${d.data.fallback}` : `retry ${d.data.attempt}/${d.data.of} in ${d.data.wait}s`} (${d.data.error})`, "bad", evAt);
    if (d.event === "continue") logLine("continue", `${nameOf(d.data.agent)} ran out of steps on "${(d.data.task || "").slice(0, 60)}" \u2014 Lead asked it to continue (${d.data.round}/${d.data.max_rounds})`, "warn-text", evAt);
    if (d.event === "continue_exhausted") logLine("retry", `${nameOf(d.data.agent)} still out of steps after ${d.data.rounds} continuation(s) on "${(d.data.task || "").slice(0, 60)}" \u2014 needs the Lead/CEO`, "bad", evAt);
    if (d.event === "finished") { toast(`Task ${d.data.status}: ${d.summary.goal.slice(0, 50)}`, d.data.status === "done" ? "ok" : "bad"); refreshSoon(); }
    renderTop(); renderAgents(); renderRun(); renderRunButtons(); renderNav();
  });
  es.onerror = () => { /* EventSource reconnects by itself */ };
}

function loginPage(message = "") {
  document.body.innerHTML = `<form class="login card" id="loginForm">
    <div class="brand"><div class="brand-mark" aria-hidden="true"><span></span><span></span></div>
      <div><div class="eyebrow">CEO Command Center</div><div class="project-name">Sign in</div></div></div>
    <label class="field"><span class="muted small">Dashboard password</span>
      <input type="password" id="loginPassword" autocomplete="current-password" required autofocus></label>
    <div class="note warn ${message ? "" : "hidden"}" id="loginMsg">${esc(message)}</div>
    <button class="btn primary" type="submit">Sign in</button>
  </form>`;
  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const res = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("#loginPassword").value }) });
    if (res.ok) { location.reload(); return; }
    const body = await res.json().catch(() => ({}));
    $("#loginMsg").textContent = body.error || "Could not sign in";
    $("#loginMsg").classList.remove("hidden");
  });
}

// ---- agent logs: everything one agent did, across all tasks --------------------------------
let logAgent = null;
let logEntries = [];
let logTimer = null;
const LOG_TYPES = { step: "step", message: "message", retry: "error", continue: "step", memory: "gbrain", skills: "skills", files: "files", package: "package", route: "triage" };

async function loadLog(more = false) {
  if (!S) return;
  logAgent = logAgent && S.agents.some((a) => a.id === logAgent) ? logAgent : S.agents[0]?.id;
  try {
    const sum = await api("GET", "agentlogs");
    renderLogAgents(sum.agents || {});
  } catch { renderLogAgents({}); }
  const q = encodeURIComponent($("#logSearch").value.trim()), type = encodeURIComponent($("#logType").value);
  const before = more && logEntries.length ? `&before=${logEntries[logEntries.length - 1].seq}` : "";
  try {
    const r = await api("GET", `agents/${encodeURIComponent(logAgent)}/log?limit=200&q=${q}&type=${type}${before}`);
    logEntries = more ? logEntries.concat(r.entries) : r.entries;
    $("#btnMoreLog").classList.toggle("hidden", r.entries.length < 200);
    renderLog();
  } catch (err) { toast(err.message, "bad"); }
}

function renderLogAgents(sum) {
  $("#logAgents").innerHTML = S.agents.map((a) => {
    const s = sum[a.id] || {}, st = agentState(a);
    return `<button type="button" class="log-agent ${a.id === logAgent ? "on" : ""}" data-log-agent="${esc(a.id)}" style="--c:${esc(a.color)}">
      <b>${esc(a.short_name || a.name)}</b> ${pill(st, STATUS_COLORS[st] || "var(--dim)", st === "working")}
      <span class="muted small">${s.last_at ? `${esc(fmtWhen(s.last_at))} · ${esc((s.last_text || "").slice(0, 60))}` : "no activity yet"}</span></button>`;
  }).join("");
  $("#logTitle").textContent = `${nameOf(logAgent)} · activity log`;
}

function fmtWhen(iso) {
  const d = toWib(iso);
  if (!d) return "";
  const opts = { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Jakarta" };
  const time = d.toLocaleTimeString("en-GB", opts); // en-GB -> "08:25"; id-ID -> "08.25" (salah)
  const wibToday = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Jakarta" }); // YYYY-MM-DD
  const day = d.toLocaleDateString("en-CA", { timeZone: "Asia/Jakarta" });
  return day === wibToday ? time : `${d.toLocaleDateString("id-ID", { day: "2-digit", month: "2-digit", timeZone: "Asia/Jakarta" })} ${time}`;
}

function logItem(e) {
  const cls = e.status === "failed" || e.type === "retry" ? "bad" : e.status === "done" ? "ok" : "";
  return `<li class="log-item ${cls}" data-seq="${e.seq}">
    <span class="log-time" title="${esc(e.at)}">${esc(fmtWhen(e.at))}</span>
    <span class="log-type t-${esc(e.type)}">${esc(LOG_TYPES[e.type] || e.type)}${e.dir ? (e.dir === "in" ? " ←" : " →") : ""}</span>
    <span class="log-text">${esc(e.text)}
      <button type="button" class="linkish muted small" data-report="${esc(e.run)}" title="Open the report of this task">${esc(e.goal || e.run)}</button>
      ${e.detail ? `<details><summary class="muted small">details</summary><pre class="log-detail">${esc(e.detail)}</pre></details>` : ""}</span></li>`;
}

function renderLog() {
  $("#logList").innerHTML = logEntries.length ? logEntries.map(logItem).join("")
    : '<div class="empty">Nothing logged for this agent yet. Its steps, messages, errors and memory use show up here as soon as it works on a task.</div>';
}

function onAgentLog(e) {  // live: a new line for the agent on screen goes on top
  if (view !== "logs" || !$("#logLive").checked) return;
  if (e.agent !== logAgent || $("#logSearch").value.trim() || ($("#logType").value && $("#logType").value !== e.type)) {
    clearTimeout(logTimer); logTimer = setTimeout(() => api("GET", "agentlogs").then((s) => renderLogAgents(s.agents || {})).catch(() => {}), 800);
    return;
  }
  logEntries.unshift(e);
  const list = $("#logList");
  if (list.querySelector(".empty")) list.innerHTML = "";
  list.insertAdjacentHTML("afterbegin", logItem(e));
}

$("#logAgents").addEventListener("click", (e) => {
  const b = e.target.closest("[data-log-agent]");
  if (b) { logAgent = b.dataset.logAgent; loadLog(); }
});
$("#logType").addEventListener("change", () => loadLog());
$("#logSearch").addEventListener("input", () => { clearTimeout(logTimer); logTimer = setTimeout(() => loadLog(), 300); });
$("#btnMoreLog").addEventListener("click", () => loadLog(true));

// ---- reports: the full story of every task ---------------------------------------------------
let repId = null;
let repTimer = null;

async function loadReports() {
  const q = encodeURIComponent($("#repSearch").value.trim()), st = encodeURIComponent($("#repStatus").value);
  try {
    const r = await api("GET", `search?q=${q}&status=${st}&limit=200`);
    const live = liveList().filter((x) => !st || x.status === st).map((x) => ({ ...x, live: true }));
    const items = [...live, ...r.tasks.filter((t) => !live.some((x) => x.id === t.id))];
    $("#repItems").innerHTML = items.length ? items.map((t) => `
      <button type="button" class="rep-item ${t.id === repId ? "on" : ""}" data-rep="${esc(t.id)}">
        <span class="rep-goal">${esc(t.goal)}</span>
        <span class="muted small">${pill(TASK_LABELS[t.status] || t.status, TASK_COLORS[t.status] || "var(--dim)", t.status === "running")} ${esc(fmtWhen(t.started_at))}${t.started_at && t.finished_at ? ` · ${fmtDur((ms(t.finished_at) - ms(t.started_at)) / 1000)}` : ""}${t.verdict ? ` · QA ${esc(t.verdict)}` : ""}</span>
      </button>`).join("") : '<div class="empty">No tasks match.</div>';
    if (!repId && items.length) openReport(items[0].id);
    else if (repId) openReport(repId, true);
  } catch (err) { toast(err.message, "bad"); }
}

async function openReport(id, quiet = false) {
  repId = id;
  for (const b of document.querySelectorAll("#repItems [data-rep]")) b.classList.toggle("on", b.dataset.rep === id);
  try { renderReport(await api("GET", `runs/${encodeURIComponent(id)}`)); }
  catch (err) { if (!quiet) toast(err.message, "bad"); }
}

function sumUsage(steps) {
  const u = { input: 0, output: 0, cost: 0, calls: 0 };
  for (const s of steps) { const x = s.usage || {}; u.input += x.input || 0; u.output += x.output || 0; u.cost += x.cost || 0; u.calls += x.calls || 0; if (x.estimated) u.estimated = true; }
  return u;
}

function renderReport(r) {
  const steps = r.steps || [];
  const rep = r.report || {};
  const startMs = ms(r.started_at), endMs = isLive(r) ? serverNow() : ms(r.finished_at);
  const took = isFinite(startMs) && isFinite(endMs) ? fmtDur((endMs - startMs) / 1000) : "—";
  const route = r.route ? (r.route.route === "answer" ? "Team Lead answered" : r.route.route === "direct" ? `⚡ straight to ${nameOf(r.route.agent)}` : `👥 team: ${(r.route.agents || []).map(nameOf).join(", ")}`) : "whole team";
  const opts = r.task_options || {};
  const tile = (l, v, sub = "") => `<div class="rep-tile"><div class="l">${esc(l)}</div><div class="v">${v}</div>${sub ? `<div class="muted small">${sub}</div>` : ""}</div>`;
  const byAgent = {};
  for (const s of steps) {
    const a = (byAgent[s.agent] ||= { steps: 0, secs: 0, failed: 0, retries: 0, list: [] });
    a.steps += 1; a.secs += s.seconds || 0; a.failed += s.status === "failed" ? 1 : 0; a.retries += s.retries || 0; a.list.push(s);
  }
  const waited = (s) => (isFinite(ms(s.started_at)) && isFinite(ms(s.queued_at)) ? (ms(s.started_at) - ms(s.queued_at)) / 1000 : 0);
  const ws = r.workspace || {}, res = ws.result || {};
  const ev = r.evidence || {};
  const conv = (r.messages || []).map((m) => `<details class="rep-msg"><summary><b>${esc(nameOf(m.from))} → ${esc(nameOf(m.to))}</b> · ${esc(m.kind)} <span class="muted small">${esc(fmtWhen(m.at))} · ${String(m.content || "").length.toLocaleString()} characters</span></summary><pre class="log-detail">${esc(m.content)}</pre></details>`).join("");
  $("#repMain").innerHTML = `
    <div class="rep-head">
      <div><div class="run-goal">${esc(r.goal)}</div>
        <div class="muted small">${pill(TASK_LABELS[r.status] || r.status, TASK_COLORS[r.status] || "var(--dim)", r.status === "running")} ${esc(r.id)} · started ${esc(fmtWhen(r.started_at) || "—")} · took ${took}${r.resumes ? ` · resumed ${r.resumes}×` : ""}</div></div>
      <div class="rep-actions">
        ${r.status === "running" && !r.paused ? `<button type="button" class="btn small ghost" data-rep-act="pause">⏸ Pause</button>` : ""}
        ${isLive(r) && (r.paused || r.status === "paused") ? `<button type="button" class="btn small good" data-rep-act="resume">▶ Resume</button>` : ""}
        ${isLive(r) ? `<button type="button" class="btn small ghost" data-rep-act="cancel">⏹ Stop</button>` : ""}
        ${RESUMABLE.includes(r.status) ? `<button type="button" class="btn small" data-rep-act="resume">Resume</button>` : ""}
        <button type="button" class="btn small ghost" data-rep-act="open">Open in Command center</button>
        <button type="button" class="btn small ghost" data-rep-act="export">Export .md</button>
      </div>
    </div>
    ${r.error ? `<div class="note warn">${esc(r.error)}</div>` : ""}
    <div class="rep-tiles">
      ${tile("Status", esc(rep.status || (TASK_LABELS[r.status] || r.status)), `${r.progress ?? 0}% selesai`)}
      ${tile("Duration", took, `${steps.length} step(s)`)}
      ${tile("Who worked", esc(route), r.route?.reason ? esc(r.route.reason) : "")}
      ${tile("QA", esc(r.verdict || "—"), `${r.qa_rounds ? `${r.qa_rounds} fix round(s) · ` : ""}${ev.verified ? "✓ verified" : ev.note ? "unverified" : ""}`)}
      ${tile("Deploy", r.deployed ? "deployed" : "not deployed", r.approval ? `approval: ${esc(r.approval.result)}` : "no approval asked")}
      ${tile("Usage", esc(usageText(r.usage) || "—"), r.usage?.calls ? `${r.usage.calls} LLM call(s)` : "")}
    </div>
    ${rep.summary ? `<h3>Laporan ke CEO</h3><div class="rep-summary">${esc(rep.summary)}</div>` : ""}
    ${(rep.blocker_list || r.blockers || []).length ? `<h3>Hambatan</h3><ul>${(rep.blocker_list || r.blockers).map((b) => `<li class="bad">${esc(b)}</li>`).join("")}</ul>` : ""}
    <h3>Stages</h3><div class="stepper">${S.flow.stages.map((s) => `<div class="step ${esc(r.stages?.[s.key] || "todo")}"><i></i>${esc(s.label)}</div>`).join("")}</div>
    ${packagesBlock(r)}
    <h3>Per agent</h3>
    <table class="rep-table"><thead><tr><th>Agen</th><th>Langkah</th><th>Waktu kerja</th><th>Token</th><th>Masalah</th></tr></thead><tbody>
      ${Object.entries(byAgent).map(([id, a]) => `<tr><td><button type="button" class="linkish" data-log-of="${esc(id)}" title="Open this agent's log">${esc(nameOf(id))}</button></td><td>${a.steps}</td><td>${fmtDur(a.secs)}</td><td>${esc(usageText(sumUsage(a.list)) || "—")}</td><td>${a.failed ? `<span class="bad">${a.failed} failed</span> ` : ""}${a.retries ? `${a.retries} retr${a.retries > 1 ? "ies" : "y"}` : ""}${!a.failed && !a.retries ? "—" : ""}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">Belum ada langkah.</td></tr>'}
    </tbody></table>
    <h3>Every step</h3>
    <table class="rep-table"><thead><tr><th>#</th><th>Agen</th><th>Langkah</th><th>Tugas</th><th>Status</th><th>Mulai</th><th>Menunggu</th><th>Durasi</th><th>Token</th></tr></thead><tbody>
      ${steps.map((s) => `<tr class="${s.status === "failed" ? "bad" : ""}"><td>${s.n}</td><td>${esc(nameOf(s.agent))}</td><td>${esc(KIND_LABELS[s.kind] || s.kind)}</td><td class="wrap">${esc(s.task || "")}${s.last_error ? `<div class="bad small">${esc(s.last_error)}</div>` : ""}</td><td>${esc(s.status)}${s.fallback ? ` · fallback ${esc(s.fallback)}` : ""}</td><td>${esc(fmtWhen(s.started_at) || "—")}</td><td>${waited(s) > 1 ? fmtDur(waited(s)) : "—"}</td><td>${s.seconds != null ? fmtDur(s.seconds) : s.status === "working" ? "…" : "—"}</td><td>${esc(usageText(s.usage) || "—")}</td></tr>`).join("") || '<tr><td colspan="9" class="muted">Belum ada langkah.</td></tr>'}
    </tbody></table>
    ${ev.note || (r.tests || []).length ? `<h3>Tests and evidence</h3><div class="small">${ev.verified ? "✓ verified" : "not verified"}${ev.source ? ` (${esc(ev.source)})` : ""}: ${esc(ev.note || "")}</div>
      ${(r.tests || []).map((t) => `<details><summary>Round ${t.round}: <code>${esc(t.command)}</code> → exit ${t.exit}</summary><pre class="log-detail">${esc(t.output)}</pre></details>`).join("")}` : ""}
    ${ws.name ? `<h3>Project and code</h3><div class="small">📁 ${esc(ws.name)} · branch <code>${esc(ws.branch || "—")}</code>${res.commit ? ` · commit <code>${esc(res.commit)}</code>` : ""}${res.files ? ` · ${res.files} file(s)` : ""}${res.merged ? ` · merged into <code>${esc(ws.base)}</code>` : ""}${res.pushed ? " · pushed" : ""}${res.note ? `<br>${esc(res.note)}` : ""}</div>
      ${res.pr ? `<div class="small">🔀 <a href="${esc(res.pr.url)}" target="_blank" rel="noopener noreferrer">Pull request #${esc(res.pr.number)}</a> · ${esc(res.pr.state)} · CI ${esc(res.pr.checks)}${res.pr.merge_requested && res.pr.state === "open" ? " · merges when CI is green" : ""}${res.pr.error ? ` · <span class="bad">${esc(res.pr.error)}</span>` : ""}
        ${res.pr.state === "open" && !res.pr.merge_requested ? `<button type="button" class="btn small good" data-rep-act="merge-pr">🔀 Merge PR</button>` : ""}</div>` : ""}
      ${(ws.files_written || []).length ? `<details><summary class="small">${ws.files_written.length} file(s) written for agents without file tools</summary><pre class="log-detail">${esc(ws.files_written.map((f) => `${f.path}  (${nameOf(f.agent)})`).join("\n"))}</pre></details>` : ""}` : ""}
    ${(r.documents || []).length ? `<h3>Task documents</h3>${docChips(r.documents, r.id)}` : ""}
    <div class="small muted" style="margin-top:8px">Options: mode ${esc(opts.mode || "auto")}${(opts.skip || []).length ? ` · no ${opts.skip.map(esc).join(", no ")}` : ""}${Object.keys(opts.models || {}).length ? ` · ${Object.entries(opts.models).map(([a, m]) => `${esc(nameOf(a))}: ${esc(m)}`).join(", ")}` : ""}</div>
    <h3>Conversation (${(r.messages || []).length} messages)</h3>
    <div class="rep-conv">${conv || '<div class="muted small">No messages yet.</div>'}</div>`;
}

$("#repItems").addEventListener("click", (e) => { const b = e.target.closest("[data-rep]"); if (b) openReport(b.dataset.rep); });
$("#repSearch").addEventListener("input", () => { clearTimeout(repTimer); repTimer = setTimeout(loadReports, 300); });
$("#repStatus").addEventListener("change", loadReports);
$("#repMain").addEventListener("click", async (e) => {
  const lg = e.target.closest("[data-log-of]");
  if (lg) { logAgent = lg.dataset.logOf; setView("logs"); return; }
  const b = e.target.closest("[data-rep-act]");
  if (!b || !repId) return;
  const act = b.dataset.repAct;
  if (act === "export") return downloadReport(repId);
  if (act === "open") {
    const key = liveRuns[repId] && isLive(liveRuns[repId]) ? `live:${repId}` : repId;
    setView("command"); renderHistory(); $("#runHistory").value = key; $("#runHistory").dispatchEvent(new Event("change"));
    return;
  }
  try { const r = await api("POST", `runs/${repId}/${act}`); toast(r.note || (r.goal ? `Continuing: ${r.goal}` : "ok"), "ok"); setTimeout(() => openReport(repId, true), 400); refreshSoon(); }
  catch (err) { toast(err.message, "bad"); }
});
document.addEventListener("click", (e) => {  // a task link anywhere (e.g. in an agent's log) opens its report
  const b = e.target.closest("[data-report]");
  if (!b) return;
  repId = b.dataset.report; setView("reports");
});
function reportLive(summary) {  // the open report follows its live task
  if (view === "reports" && summary && summary.id === repId) { clearTimeout(repTimer); repTimer = setTimeout(() => openReport(repId, true), 700); }
}

(async function start() {
  if (!token) {
    const auth = await fetch("/api/auth").then((r) => r.json()).catch(() => ({}));
    if (auth.login && !auth.authenticated) { loginPage(); return; }
    if (!auth.authenticated) {
      document.body.innerHTML = `<div class="empty" style="margin:15vh auto;max-width:520px">Open the dashboard with the URL printed by <code>babd dashboard</code> (it contains the access token).</div>`;
      return;
    }
  }
  try {
    await refresh(); connect();
    let saved = "command";
    try { saved = localStorage.getItem("babd.view") || "command"; } catch { /* private mode */ }
    if (location.hash === "#board" || saved === "board") setView("board");
    else if (["logs", "reports"].includes(location.hash.slice(1)) || ["logs", "reports"].includes(saved)) setView(["logs", "reports"].includes(location.hash.slice(1)) ? location.hash.slice(1) : saved);
  }
  catch (err) {
    document.body.innerHTML = `<div class="empty" style="margin:15vh auto;max-width:520px">Cannot load the dashboard: ${esc(err.message)}.<br>Restart <code>babd dashboard</code> and open the new URL.</div>`;
  }
})();

// ---- team memory search ------------------------------------------------------------------
async function searchMemory() {
  const q = $("#memQuery").value.trim();
  const box = $("#memResults");
  if (!q) return;
  box.innerHTML = '<div class="muted small"><span class="spinner"></span> searching gbrain…</div>';
  try {
    const r = await api("GET", `brain/recall?q=${encodeURIComponent(q)}`);
    const facts = r.facts.map((f) => `<li class="msg"><div class="msg-body">${esc(f.fact)}</div><div class="muted small">${esc(f.provenance || f.source || "")}</div></li>`);
    const pages = r.results.map((p) => `<li class="msg"><div class="msg-head"><span class="kind">${esc(p.slug)}</span></div><div class="msg-body clamp">${esc(p.chunk)}</div></li>`);
    box.innerHTML = `<div class="muted small">Searched: ${esc(r.query)} · ${r.facts.length} fact(s), ${r.results.length} page(s)</div>
      <ol class="timeline">${facts.join("") + pages.join("") || '<div class="empty">Nothing in gbrain for these words yet.</div>'}</ol>`;
  } catch (err) { box.innerHTML = `<div class="note warn">${esc(err.message)}</div>`; }
}
$("#memSearch").addEventListener("click", searchMemory);
$("#memQuery").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); searchMemory(); } });
