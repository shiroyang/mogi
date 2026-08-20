// mogi shared helpers
async function api(path, opts = {}) {
  const r = await fetch("/api" + path, {
    credentials: "same-origin",
    headers: { "x-mogi": "1", ...(opts.body ? { "content-type": "application/json" } : {}) },
    ...opts,
  });
  if (r.status === 401) { showLogin(); throw new Error("not signed in"); }
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}

function showLogin() {
  document.body.innerHTML = `
    <div class="login-splash">
      <div class="logo">mogi <span style="color:var(--muted);font-size:1.1rem">模擬 — the 真題 judge</span></div>
      <a class="btn primary" href="/api/auth/login">Sign in with GitHub</a>
    </div>`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function fmtDate(tsSec) {
  return new Date(tsSec * 1000).toISOString().slice(0, 16).replace("T", " ");
}

// GitHub-style heatmap: events = [{ts(ms), verdict}], weeks columns × 7 rows
function renderHeatmap(el, events, weeks = 26) {
  const byDay = {};
  for (const e of events) {
    const d = new Date(e.ts).toISOString().slice(0, 10);
    byDay[d] = (byDay[d] || 0) + (e.verdict === "AC" ? 1 : 0.25);
  }
  const cells = [];
  const today = new Date();
  const start = new Date(today); start.setDate(today.getDate() - (weeks * 7 - 1) - today.getDay());
  for (let i = 0; i < weeks * 7 + today.getDay() + 1; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    if (d > today) break;
    const key = d.toISOString().slice(0, 10);
    const n = byDay[key] || 0;
    const lvl = n === 0 ? "" : n < 1 ? "l1" : n < 3 ? "l2" : n < 6 ? "l3" : "l4";
    cells.push(`<div class="${lvl}" title="${key}: ${n} "></div>`);
  }
  el.innerHTML = cells.join("");
}
