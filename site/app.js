// 宁好前端：读取 data/feed.json，每分钟检查一次新播报。无框架、无构建步骤。
const CATS = ["全部", "项目动态", "政策法规", "财务披露", "话事人发言", "竞争格局", "市场数据"];
const PH = { 项目动态: "项目", 政策法规: "政策", 财务披露: "财报", 话事人发言: "发言", 竞争格局: "竞争", 市场数据: "数据" };
const POLL_MS = 60_000;

const state = { items: [], updated: null, cat: "全部", signal: "", important: false, q: "", known: new Set(), fresh: new Set() };
const $ = (s) => document.querySelector(s);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  return `${Math.floor(s / 86400)} 天前`;
}

function fmt(iso) {
  if (!iso) return "未知";
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function media(item, cls = "media") {
  const ph = `<div class="ph">${esc(PH[item.category] || "情报")}</div>`;
  if (!item.image) return `<div class="${cls}">${ph}</div>`;
  return `<div class="${cls}">${ph}<img src="${esc(item.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()"></div>`;
}

function impactBars(n) {
  return `<span class="impact" title="影响 ${n}/5">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span>`;
}

function metaLine(item) {
  return `<div class="meta">
    <span class="cat">${esc(item.category)}</span>
    <span class="badge ${esc(item.signal)}">${esc(item.signal)}</span>
    ${impactBars(item.impact)}
    <span>${esc(item.region)}</span>
    <span>${ago(item.published || item.broadcast)}</span>
    ${state.fresh.has(item.id) ? '<span class="badge new">新</span>' : ""}
  </div>`;
}

function filtered() {
  const q = state.q.trim().toLowerCase();
  return state.items.filter((it) =>
    (state.cat === "全部" || it.category === state.cat) &&
    (!state.signal || it.signal === state.signal) &&
    (!state.important || it.impact >= 4) &&
    (!q || [it.headline, it.why, it.title_original, it.source, it.region, ...(it.entities || [])].join(" ").toLowerCase().includes(q))
  );
}

function renderChips() {
  const count = (c) => (c === "全部" ? state.items.length : state.items.filter((i) => i.category === c).length);
  $("#cats").innerHTML = CATS.map((c) =>
    `<button class="chip ${c === state.cat ? "on" : ""}" data-cat="${c}" role="tab">${c}<span class="n">${count(c)}</span></button>`
  ).join("");
}

function render() {
  renderChips();
  const list = filtered();
  // 头条：48 小时内影响最高的一条
  const recent = list.filter((i) => Date.now() - new Date(i.published || i.broadcast) < 48 * 3600e3);
  const hero = [...(recent.length ? recent : list)].sort((a, b) => b.impact - a.impact)[0];
  const heroEl = $("#hero");
  if (hero) {
    heroEl.hidden = false;
    heroEl.dataset.id = hero.id;
    heroEl.innerHTML = `${media(hero)}
      <div class="body">
        <div class="kicker">头条 · ${esc(hero.source)}</div>
        <h2>${esc(hero.headline)}</h2>
        ${metaLine(hero)}
        <p class="why">${esc(hero.why)}</p>
        <div class="action">建议：${esc(hero.action)}</div>
      </div>`;
  } else heroEl.hidden = true;

  const rest = list.filter((i) => !hero || i.id !== hero.id);
  $("#feed").innerHTML = rest.map((it) => `
    <article class="card ${state.fresh.has(it.id) ? "fresh" : ""}" data-id="${it.id}" tabindex="0">
      <div>
        ${metaLine(it)}
        <h3>${esc(it.headline)}</h3>
        <p class="why">${esc(it.why)}</p>
        <div class="foot"><b>${esc(it.source)}</b> · 原标题：${esc(it.title_original)}</div>
      </div>
      ${media(it)}
    </article>`).join("");
  $("#empty").hidden = list.length > 0;
}

function openDrawer(id) {
  const it = state.items.find((i) => i.id === id);
  if (!it) return;
  $("#drawer-body").innerHTML = `
    ${media(it, "media d-media")}
    <div class="d-body">
      ${metaLine(it)}
      <h2 id="d-headline">${esc(it.headline)}</h2>
      <div class="d-section"><h4>为什么重要</h4><p>${esc(it.why)}</p></div>
      ${it.facts?.length ? `<div class="d-section"><h4>原文要点</h4><ul>${it.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul></div>` : ""}
      ${it.entities?.length ? `<div class="d-section"><h4>涉及主体</h4><div class="ent">${it.entities.map((e) => `<span>${esc(e)}</span>`).join("")}</div></div>` : ""}
      <div class="d-section"><h4>建议动作</h4><div class="d-action">${esc(it.action)}</div></div>
      <div class="d-section"><h4>原文</h4><p class="d-orig">${esc(it.source)} · ${esc(it.title_original)}</p></div>
      <a class="btn" href="${esc(it.url)}" target="_blank" rel="noopener noreferrer">阅读原文 ↗</a>
      <p class="d-small">发生于 ${fmt(it.published)} · 播报于 ${fmt(it.broadcast)} · 由 ${esc(it.model || "Claude")} 解读</p>
    </div>`;
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
}

function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
}

function updateLive() {
  const el = $("#live");
  if (!state.updated) { $("#live-text").textContent = "暂无数据"; el.classList.add("stale"); return; }
  const mins = (Date.now() - new Date(state.updated)) / 60000;
  el.classList.toggle("stale", mins > 90);
  $("#live-text").textContent = `实时播报中 · ${ago(state.updated)}更新`;
}

function toast(item) {
  const t = $("#toast");
  t.textContent = `新播报 · ${item.headline}`;
  t.hidden = false;
  t.onclick = () => { t.hidden = true; openDrawer(item.id); };
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.hidden = true), 8000);
}

async function load(first = false) {
  try {
    const res = await fetch(`data/feed.json?t=${Date.now()}`, { cache: "no-store" });
    const data = await res.json();
    const incoming = data.items || [];
    if (!first) {
      const news = incoming.filter((i) => !state.known.has(i.id));
      news.forEach((i) => state.fresh.add(i.id));
      if (news.length) toast([...news].sort((a, b) => b.impact - a.impact)[0]);
    }
    incoming.forEach((i) => state.known.add(i.id));
    state.items = incoming;
    state.updated = data.updated;
    render();
  } catch (e) {
    console.warn("读取 feed 失败", e);
  }
  updateLive();
}

document.addEventListener("click", (e) => {
  const chip = e.target.closest("[data-cat]");
  if (chip) { state.cat = chip.dataset.cat; render(); return; }
  const sig = e.target.closest("[data-signal]");
  if (sig) {
    state.signal = sig.dataset.signal;
    document.querySelectorAll("#signals button").forEach((b) => b.classList.toggle("on", b === sig));
    render(); return;
  }
  if (e.target.closest("[data-close]")) { closeDrawer(); return; }
  const card = e.target.closest(".card, .hero");
  if (card) openDrawer(card.dataset.id);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
  if (e.key === "Enter" && e.target.classList?.contains("card")) openDrawer(e.target.dataset.id);
});
$("#important").addEventListener("change", (e) => { state.important = e.target.checked; render(); });
$("#search").addEventListener("input", (e) => { state.q = e.target.value; render(); });

load(true);
setInterval(load, POLL_MS);
setInterval(updateLive, 30_000);
