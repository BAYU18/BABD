"use strict";

// ---- token + API --------------------------------------------------------------------------
const params = new URLSearchParams(location.search);
let token = params.get("token") || sessionStorage.getItem("babd-token") || "";
if (params.get("token")) {
  sessionStorage.setItem("babd-token", token);
  history.replaceState(null, "", location.pathname); // keep the token out of the address bar
}

async function api(method, path, body) {
  const res = await fetch(`/api/${path}`, {
    method,
    headers: { "X-BABD-Token": token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ---- helpers -----------------------------------------------------------------------------
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");
const STATUS_COLORS = { working: "var(--good)", done: "var(--ceo)", waiting: "var(--warn)", blocked: "var(--bad)", idle: "var(--dim)", setup: "#c084fc" };
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
const jobs = {};          // job id -> job
const chats = {};         // agent id -> [{role, content}]
const checks = {};        // agent id -> {ok, summary}
let drawer = null;        // {mode: "config"|"chat", agentId, tab}

const agentById = (id) => S.agents.find((a) => a.id === id);
const colorOf = (id) => (id === "ceo" ? "var(--ceo)" : agentById(id)?.color || "var(--muted)");
const nameOf = (id) => (id === "ceo" ? "CEO" : agentById(id)?.short_name || id);
const runActive = () => S?.run && ["running", "waiting_approval"].includes(S.run.status);

async function refresh() {
  S = await api("GET", "state");
  if (!viewingHistory) viewRun = S.run;
  renderAll();
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
  $("#btnRun").disabled = !!runActive();
  $("#btnCancel").classList.toggle("hidden", !runActive());
  if (drawer?.mode === "chat") renderChat();
}

// ---- top bar -----------------------------------------------------------------------------
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
  const live = S.run && runActive() ? S.run : null;
  const status = live ? (live.status === "waiting_approval" ? "WAITING" : "RUNNING") : p.status;
  const progress = live ? live.progress : p.progress;
  const working = live ? Object.values(live.agents).filter((a) => a.status === "working").length
    : S.agents.filter((a) => a.status === "working").length;
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="l">Status</div><div class="v">${pill(status, PROJECT_COLORS[status] || "var(--warn)", !!live)}</div></div>
    <div class="kpi progress"><div class="l">Progress · ${progress}%</div><div class="bar"><i style="width:${progress}%"></i></div></div>
    <div class="kpi"><div class="l">Agents working</div><div class="v">${working} / ${S.agents.length}</div></div>
    <div class="kpi"><div class="l">Approval needed</div><div class="v" style="color:${(live?.approval?.result === "pending" || p.approval_needed) ? "var(--warn)" : "inherit"}">${live?.approval?.result === "pending" ? 1 : p.approval_needed}</div></div>
    <div class="kpi"><div class="l">Blockers</div><div class="v" style="color:${(p.blockers && !live) ? "var(--bad)" : "inherit"}">${live ? live.blockers.length : p.blockers}</div></div>
    <div class="kpi" title="${esc(brainTitle())}"><div class="l">GBrain memory</div><div class="v">${brainPill()}</div></div>
    <div class="kpi"><div class="l">Next action</div><div class="v small">${esc(live ? (live.stage || "").toUpperCase() : p.next_action)}</div></div>`;
}

// ---- agent cards -------------------------------------------------------------------------
function agentLive(a) {
  return S.run && runActive() ? S.run.agents[a.id] : null;
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
      ${live?.task ? `<div class="agent-task-now">${esc(live.task)}</div>` : ""}
    </div>
    <div style="display:grid;gap:10px;align-content:start">
      <div class="chips">
        <span class="chip" title="${esc(a.harness_summary)}">Harness <b>${esc(harnessLabel)}</b></span>
        <span class="chip" title="${esc(llm.base_url || "")}">LLM <b>${esc(llm.model)}</b></span>
        <span class="chip ${llm.api_key_set ? "ok" : "bad"}">${llm.api_key_set ? "key set" : "no key"}</span>
        ${recChip(a)}
        ${packsChip(a)}
        ${a.telegram?.enabled ? `<span class="chip">Telegram <b>${esc(a.telegram.bot_username)}</b></span>` : ""}
        ${check ? `<span class="chip ${check.ok ? "ok" : "bad"}" title="${esc(check.summary)}">${check.ok ? "check OK" : "check failed"}</span>` : ""}
      </div>
      <div class="agent-actions">
        <button class="btn small" data-act="chat">Chat</button>
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
    stations[a.id].dataset.state = agentState(a);
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
  if (btn.dataset.act === "setup") {
    try { trackJob(await api("POST", `agents/${id}/setup`)); toast(`Setting up ${nameOf(id)}…`); }
    catch (err) { toast(err.message, "bad"); }
  }
});

// ---- run panel ---------------------------------------------------------------------------
function renderHistory() {
  const sel = $("#runHistory");
  const current = sel.value;
  sel.innerHTML = `<option value="">Current run</option>` + S.runs
    .map((r) => `<option value="${esc(r.id)}">${esc(r.id)} · ${esc(r.status)} · ${esc((r.goal || "").slice(0, 32))}</option>`).join("");
  sel.value = current;
}

$("#runHistory").addEventListener("change", async (e) => {
  const id = e.target.value;
  viewingHistory = !!id;
  try { viewRun = id ? await api("GET", `runs/${id}`) : S.run; } catch (err) { toast(err.message, "bad"); }
  renderRun();
});

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

function memoryItem(m) {
  const what = m.op === "read"
    ? `read gbrain · ${m.facts} fact(s), ${m.pages} page(s) <span class="kind">${esc(m.query)}</span>`
    : `wrote gbrain · <span class="kind">${esc(m.page || m.entity)}</span>`;
  const title = m.op === "read" ? (m.items || []).join("\n") : (m.fact || "");
  return `<li class="mem ${m.op}" title="${esc(title)}"><span class="mem-dot"></span>
    <span class="who" style="--c:${colorOf(m.agent)}">${esc(nameOf(m.agent))}</span> ${what}
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

function renderRun() {
  const r = viewRun;
  const body = $("#runBody");
  if (!r) {
    body.innerHTML = `<div class="empty">No run yet.<br>Give the team a goal to see the agents talk to each other here.</div>`;
    return;
  }
  const stages = S.flow.stages.map((s) => `<div class="step ${esc(r.stages?.[s.key] || "todo")}" title="${esc(nameOf(s.owner))}"><i></i>${esc(s.label)}</div>`).join("");
  const statusColor = { running: "var(--good)", waiting_approval: "var(--warn)", done: "var(--ceo)", failed: "var(--bad)", cancelled: "var(--dim)" }[r.status];
  const approval = r.approval?.result === "pending" && !viewingHistory ? `
    <div class="approval">
      <div class="eyebrow" style="color:var(--warn)">CEO approval needed</div>
      <div class="q">${esc(r.approval.question)}</div>
      <input type="text" id="approvalNote" placeholder="Note for the team (optional)">
      <div class="row"><button class="btn good" data-approve="1">Approve deploy</button><button class="btn danger" data-approve="0">Reject</button></div>
    </div>` : "";
  const rep = r.report;
  const report = rep ? `
    <div class="report">
      <div class="eyebrow">Report to the CEO</div>
      <div class="report-grid">
        <div><div class="l">Status</div><div class="v">${esc(rep.status)}</div></div>
        <div><div class="l">QA</div><div class="v">${esc(rep.qa_verdict)}${rep.fix_rounds ? ` · ${rep.fix_rounds} fix` : ""}</div></div>
        <div><div class="l">Deployed</div><div class="v">${rep.deployed ? "Yes" : "No"}</div></div>
        <div><div class="l">Recent</div><div class="v">${esc(rep.recent_result || "—")}</div></div>
        <div><div class="l">Next</div><div class="v">${esc(rep.next_action || "—")}</div></div>
        <div><div class="l">Blockers</div><div class="v">${esc(rep.blockers ?? 0)}</div></div>
      </div>
      ${rep.summary ? `<div class="small">${esc(rep.summary)}</div>` : ""}
      ${(rep.blocker_list || []).map((b) => `<div class="small" style="color:var(--bad)">● ${esc(b)}</div>`).join("")}
    </div>` : "";
  body.innerHTML = `
    <div>
      <div class="run-goal">${esc(r.goal)}</div>
      <div class="run-meta">${pill(r.status.replace("_", " "), statusColor, r.status === "running")}
        <span class="muted small">${esc(r.id)} · ${r.progress ?? 0}%${r.qa_rounds ? ` · ${r.qa_rounds} QA fix round(s)` : ""}</span></div>
      ${r.error ? `<div class="note warn" style="margin-top:8px">${esc(r.error)}</div>` : ""}
    </div>
    <div class="stepper">${stages}</div>
    ${approval}${report}
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
  const goal = $("#goal").value.trim();
  if (!goal) { toast("Write a goal for the team first", "bad"); $("#goal").focus(); return; }
  try {
    viewingHistory = false;
    $("#runHistory").value = "";
    S.run = await api("POST", "runs", { goal, auto_approve: $("#autoApprove").checked, update_dashboard: $("#updateImage").checked });
    viewRun = S.run;
    renderAll();
    toast("Team run started");
  } catch (err) { toast(err.message, "bad"); }
});

$("#btnCancel").addEventListener("click", async () => {
  if (!S.run) return;
  try { await api("POST", `runs/${S.run.id}/cancel`); toast("Stopping after the current step…"); }
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
function logLine(source, msg, cls = "") {
  const li = document.createElement("li");
  li.innerHTML = `<span class="t">${new Date().toLocaleTimeString()}</span><span class="s">${esc(source)}</span><span class="${cls}">${esc(msg)}</span>`;
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
        logLine(job.kind, `${id}: ${r.ok ? "OK" : "FAIL"} ${r.summary}`, r.ok ? "ok" : "bad");
      }
      const failed = Object.values(job.result).filter((r) => !r.ok).length;
      toast(`${job.kind === "check" ? "Check" : "Setup"} finished${failed ? ` · ${failed} failed (see Activity)` : " · all OK"}`, failed ? "bad" : "ok");
    } else {
      logLine(job.kind, job.error, "bad");
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
      ${field("Status on the dashboard", select("status", f.status, [["idle", "Idle"], ["working", "Working"], ["waiting", "Waiting"], ["blocked", "Blocked"]]))}
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
      ${llm.api_key_inline ? `<div class="note warn">agents.json contains an inline api_key for this agent. Saving a key here moves it to .env.</div>` : ""}`;
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
      <div class="note">Installed and configured automatically: <b>Save & set up</b> installs the program if needed and writes this agent's config, using the LLM from the LLM tab.</div>
      <div class="note">${esc(agentById(drawer.agentId).harness_summary)}</div>`;
  } else if (drawer.tab === "telegram") {
    const t = f.telegram || {};
    html = `
      <label class="check"><input type="checkbox" name="tg_enabled" ${t.enabled ? "checked" : ""}> Telegram gateway enabled</label>
      ${field("Bot username", text("tg_bot_username", t.bot_username, "@my_agent_bot"))}
      ${field("Token variable", text("tg_token_env", t.token_env, "TELEGRAM_DEV_BOT_TOKEN"), "Environment variable holding the BotFather token.")}
      <div class="note warn">Shown on the dashboard and workspace image. The Telegram bot itself is not connected yet.</div>`;
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
  } else if (tab === "llm") {
    for (const k of ["provider", "api", "base_url", "model", "effort", "api_key_env"]) form.llm[k] = get(k);
    form.llm.max_tokens = get("max_tokens") ? Number(get("max_tokens")) : "";
    form.api_key = get("api_key") || form.api_key;
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
  } else if (tab === "skills") {
    for (const p of PACKS()) form[p.key] = p.catalog.map((c) => c.name).filter((n) => $(`[name="pk_${p.key}_${CSS.escape(n)}"]`)?.checked);
  } else if (tab === "telegram") {
    form.telegram = { ...(form.telegram || {}), enabled: !!$('[name="tg_enabled"]').checked,
      bot_username: get("tg_bot_username"), token_env: get("tg_token_env") };
  }
}

async function saveConfig(setup) {
  readForm();
  const f = form;
  const body = {
    name: f.name, short_name: f.short_name, main_task: f.main_task, sub_tasks: f.sub_tasks, status: f.status,
    skills: f.skills, telegram: f.telegram, harness: f.harness,
    ...Object.fromEntries(PACKS().filter((p) => f[p.key]).map((p) => [p.key, f[p.key]])),
    llm: Object.fromEntries(["provider", "api", "base_url", "model", "effort", "api_key_env", "max_tokens"].map((k) => [k, f.llm[k] ?? ""])),
  };
  if (f.api_key) body.api_key = f.api_key;
  try {
    await api("PUT", `agents/${drawer.agentId}`, body);
    form.api_key = "";
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
    ${field("QA fix rounds", `<input type="number" id="p_rounds" min="0" max="5" value="${esc(p.max_fix_rounds ?? 2)}">`, "How many times a failed QA report goes back to the Developer before the run is blocked.")}
    <div class="field"><label>GBrain team memory</label>
      <label class="check"><input type="checkbox" id="g_enabled" ${(p.gbrain?.enabled ?? true) ? "checked" : ""}> Every agent reads gbrain before a task and writes to it after</label>
      <label class="check"><input type="checkbox" id="g_strict" ${(p.gbrain?.strict ?? true) ? "checked" : ""}> Stop the agent step when gbrain can't be read or written</label>
      <label class="check"><input type="checkbox" id="g_cloud" ${p.gbrain?.allow_cloud ? "checked" : ""}> Allow gbrain to use cloud API keys (off = memory stays on this machine)</label>
    </div>
    <div class="help">Brain: ${esc(S.brain?.home || "")} · ${S.brain?.brain ? "ready" : "not set up yet (Set up all)"}</div>
    ${PACKS().map((k) => `<div class="field"><label>${esc(k.title)} (${esc(k.source)})</label>
      <label class="check"><input type="checkbox" id="pk_en_${k.key}" ${(p[k.key]?.enabled ?? true) ? "checked" : ""}> Agents use their ${esc(k.title)} on every step they apply to</label>
      <label class="check"><input type="checkbox" id="pk_enf_${k.key}" ${(p[k.key]?.enforce ?? true) ? "checked" : ""}> Ask an agent to redo a step once when its answer skips one of these skills</label></div>`).join("")}
    <div class="note">Flow: ${S.flow.stages.map((s) => esc(s.label)).join(" → ")}. Specialists only talk to the Team Lead; only the Team Lead reports to the CEO.</div>
    <div style="display:flex;justify-content:flex-end"><button class="btn primary" id="p_save">Save</button></div>`, true);
  $("#p_save").onclick = async () => {
    try {
      await api("PUT", "project", { name: $('[name="p_name"]').value, require_approval: $("#p_approval").checked, max_fix_rounds: Number($("#p_rounds").value),
        gbrain: { enabled: $("#g_enabled").checked, strict: $("#g_strict").checked, allow_cloud: $("#g_cloud").checked },
        ...Object.fromEntries(PACKS().map((k) => [k.key, { enabled: $(`#pk_en_${k.key}`).checked, enforce: $(`#pk_enf_${k.key}`).checked }])) });
      toast("Settings saved", "ok"); closeModal(); refresh();
    } catch (err) { toast(err.message, "bad"); }
  };
});

// ---- live events -------------------------------------------------------------------------
function connect() {
  const es = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);
  es.addEventListener("log", (e) => { const d = JSON.parse(e.data); logLine(d.source, d.msg, /fail|error/i.test(d.msg) ? "bad" : ""); });
  es.addEventListener("job", (e) => onJob(JSON.parse(e.data)));
  es.addEventListener("memory", (e) => { const m = JSON.parse(e.data); flashMemory(m.agent, m.op); logLine("gbrain", `${nameOf(m.agent)} ${m.op === "read" ? "read" : "wrote"} gbrain`); });
  es.addEventListener("config", () => refreshSoon());
  es.addEventListener("approval", (e) => { toast(`Approval needed: ${JSON.parse(e.data).question}`); });
  es.addEventListener("run", (e) => {
    const d = JSON.parse(e.data);
    S.run = d.summary;
    if (!viewingHistory) viewRun = S.run;
    if (d.event === "message") logLine("flow", `${nameOf(d.data.from)} → ${nameOf(d.data.to)}: ${d.data.kind}`);
    if (d.event === "memory") flashMemory(d.data.agent, d.data.op);
    if (d.event === "skills") logLine("skills", `${nameOf(d.data.agent)}: ${d.data.missing.length ? "skipped " + d.data.missing.join(", ") : "applied " + d.data.skills.join(", ")}`, d.data.missing.length ? "bad" : "ok");
    if (d.event === "memory") logLine("gbrain", `${nameOf(d.data.agent)} ${d.data.op === "read" ? `read ${d.data.facts} fact(s), ${d.data.pages} page(s)` : `wrote ${d.data.page}`}`);
    if (d.event === "finished") { toast(`Run ${d.data.status}`, d.data.status === "done" ? "ok" : "bad"); refreshSoon(); }
    renderTop(); renderAgents(); renderRun();
    $("#btnRun").disabled = !!runActive();
    $("#btnCancel").classList.toggle("hidden", !runActive());
  });
  es.onerror = () => { /* EventSource reconnects by itself */ };
}

(async function start() {
  if (!token) {
    document.body.innerHTML = `<div class="empty" style="margin:15vh auto;max-width:520px">Open the dashboard with the URL printed by <code>babd dashboard</code> (it contains the access token).</div>`;
    return;
  }
  try { await refresh(); connect(); }
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
