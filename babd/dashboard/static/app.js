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
const STATUS_COLORS = { working: "var(--good)", done: "var(--ceo)", waiting: "var(--warn)", blocked: "var(--bad)", idle: "var(--dim)" };
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

function robot(color) {
  return `<svg class="avatar" viewBox="0 0 40 40" aria-hidden="true" style="stroke:none">
    <rect x="19" y="2" width="2" height="6" fill="${color}"/><circle cx="20" cy="3" r="2.6" fill="${color}"/>
    <rect x="7" y="8" width="26" height="20" rx="7" fill="#dfe7f3"/><rect x="11" y="13" width="18" height="10" rx="5" fill="#0b1424"/>
    <circle cx="16" cy="18" r="2.2" fill="${color}"/><circle cx="24" cy="18" r="2.2" fill="${color}"/>
    <path d="M9 40v-6a6 6 0 0 1 6-6h10a6 6 0 0 1 6 6v6z" fill="${color}"/></svg>`;
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
    <div class="kpi"><div class="l">Next action</div><div class="v small">${esc(live ? (live.stage || "").toUpperCase() : p.next_action)}</div></div>`;
}

// ---- agent cards -------------------------------------------------------------------------
function agentLive(a) {
  return S.run && runActive() ? S.run.agents[a.id] : null;
}

function agentCard(a) {
  const live = agentLive(a);
  const status = live ? live.status : a.status;
  const busy = Object.values(jobs).find((j) => j.agent === a.id && j.status === "running");
  const llm = a.llm, h = a.harness;
  const check = checks[a.id];
  const harnessLabel = S.harnesses[h.type]?.label || h.type;
  const subs = a.sub_tasks.map((s) => `<li class="${esc(s.state)}"><span class="box"></span>${esc(s.name)}</li>`).join("");
  return `
  <article class="agent ${a.id === "lead" ? "lead" : ""} ${status === "working" ? "working" : ""}" style="--c:${esc(a.color)}" data-agent="${esc(a.id)}">
    <div>
      <div class="agent-top">${robot(a.color)}
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

function renderAgents() {
  $("#agents").innerHTML = S.agents.map(agentCard).join("");
}

$("#agents").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.closest("[data-agent]").dataset.agent;
  if (btn.dataset.act === "config") openDrawer("config", id);
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
    <ol class="timeline" id="timeline">${(r.messages || []).map(messageItem).join("")}</ol>`;
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
    html = `
      <div class="skill-editor">${f.skills.map((s, i) => `<span class="skill">${esc(s)}<button type="button" data-rmskill="${i}" aria-label="Remove ${esc(s)}">×</button></span>`).join("") || '<span class="muted">No skills yet</span>'}</div>
      <div class="chat-input"><input type="text" id="newSkill" placeholder="Add a skill, e.g. Kubernetes"><button type="button" class="btn" id="addSkill">Add</button></div>
      <div class="note">Skills go into the system prompt. Add <code>skills/&lt;skill-name&gt;.md</code> to give a skill real instructions.</div>`;
  }
  $("#drawerBody").innerHTML = html;
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

$("#btnImage").addEventListener("click", () =>
  openModal("Workspace image", `<img src="/workspace.svg?t=${Date.now()}" alt="AI software development workspace">`));

$("#btnSettings").addEventListener("click", () => {
  const p = S.project;
  openModal("Team settings", `
    ${field("Project name", text("p_name", p.name))}
    <label class="check"><input type="checkbox" id="p_approval" ${(p.require_approval || []).includes("deploy") ? "checked" : ""}> CEO must approve before DevOps deploys</label>
    ${field("QA fix rounds", `<input type="number" id="p_rounds" min="0" max="5" value="${esc(p.max_fix_rounds ?? 2)}">`, "How many times a failed QA report goes back to the Developer before the run is blocked.")}
    <div class="note">Flow: ${S.flow.stages.map((s) => esc(s.label)).join(" → ")}. Specialists only talk to the Team Lead; only the Team Lead reports to the CEO.</div>
    <div style="display:flex;justify-content:flex-end"><button class="btn primary" id="p_save">Save</button></div>`, true);
  $("#p_save").onclick = async () => {
    try {
      await api("PUT", "project", { name: $('[name="p_name"]').value, require_approval: $("#p_approval").checked, max_fix_rounds: Number($("#p_rounds").value) });
      toast("Settings saved", "ok"); closeModal(); refresh();
    } catch (err) { toast(err.message, "bad"); }
  };
});

// ---- live events -------------------------------------------------------------------------
function connect() {
  const es = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);
  es.addEventListener("log", (e) => { const d = JSON.parse(e.data); logLine(d.source, d.msg, /fail|error/i.test(d.msg) ? "bad" : ""); });
  es.addEventListener("job", (e) => onJob(JSON.parse(e.data)));
  es.addEventListener("config", () => refreshSoon());
  es.addEventListener("approval", (e) => { toast(`Approval needed: ${JSON.parse(e.data).question}`); });
  es.addEventListener("run", (e) => {
    const d = JSON.parse(e.data);
    S.run = d.summary;
    if (!viewingHistory) viewRun = S.run;
    if (d.event === "message") logLine("flow", `${nameOf(d.data.from)} → ${nameOf(d.data.to)}: ${d.data.kind}`);
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
