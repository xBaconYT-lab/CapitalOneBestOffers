/* Best Dollar Offers – front end. No build step, no dependencies. */
(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const OVERRIDE_KEY = "c1-minspend-overrides";

  const state = {
    data: null,
    view: "fixed",
    sort: "value",
    query: "",
    hideBig: false,
    overrides: loadOverrides(),
    expanded: new Set(),
  };

  function loadOverrides() {
    try { return JSON.parse(localStorage.getItem(OVERRIDE_KEY) || "{}"); } catch { return {}; }
  }
  function saveOverrides() {
    try { localStorage.setItem(OVERRIDE_KEY, JSON.stringify(state.overrides)); } catch {}
  }
  function tierKey(offer, tier) { return `${offer.id}|${tier.name}`; }

  // ---------- scoring (mirrors scraper.py, but honours user overrides) ----------
  function evaluate(offer) {
    const tiers = offer.tiers.map((t) => {
      const key = tierKey(offer, t);
      const override = state.overrides[key];
      const minSpend = offer.reward_type === "fixed" ? (override != null ? override : t.min_spend) : null;
      let ratio, net;
      if (offer.reward_type === "fixed") {
        ratio = minSpend > 0 ? t.amount / minSpend : Infinity;
        net = t.amount - (minSpend || 0);
      } else {
        ratio = t.amount / 100;
        net = null;
      }
      return { ...t, minSpend, ratio, net, source: override != null ? "override" : t.min_spend_source, key };
    });
    let best = 0;
    tiers.forEach((t, i) => {
      const b = tiers[best];
      if (t.ratio > b.ratio || (t.ratio === b.ratio && t.amount > b.amount)) best = i;
    });
    return { ...offer, tiers, best, bestTier: tiers[best], score: tiers[best].ratio };
  }

  function verdict(o) {
    const t = o.bestTier;
    if (o.reward_type !== "fixed") return { cls: "neutral", text: `${o.cashback_text} back – value depends on how much you spend` + (o.max_payout ? ` (max ${o.max_payout})` : "") };
    if (t.ratio === Infinity) return { cls: "good", text: "Free to claim – pure profit" };
    if (t.net > 0) return { cls: "good", text: `Profit: you get $${fmt(t.net)} more back than you spend` };
    if (t.ratio >= 1) return { cls: "good", text: "Pays for itself" };
    if (t.ratio >= 0.5) return { cls: "ok", text: "Good – you get at least half your money back" };
    if (t.ratio >= 0.2) return { cls: "neutral", text: "OK – decent rebate on a real purchase" };
    return { cls: "warn", text: `Needs a big purchase (~$${fmt(t.minSpend)}) for the cashback` };
  }

  const fmt = (n) => (Math.abs(n) >= 100 ? Math.round(n).toLocaleString() : (+n).toFixed(2).replace(/\.00$/, ""));
  const money = (n) => (n == null ? "—" : `$${fmt(n)}`);
  const ratioText = (r) => (r === Infinity ? "FREE" : `${r >= 10 ? r.toFixed(0) : r.toFixed(2)}×`);

  function daysLeft(iso) {
    if (!iso) return null;
    const ms = new Date(iso) - Date.now();
    return Math.ceil(ms / 86400000);
  }

  // ---------- filtering / sorting ----------
  function visibleOffers() {
    if (!state.data) return [];
    let list = state.data.offers.map(evaluate);
    if (state.view === "fixed") list = list.filter((o) => o.reward_type === "fixed");
    if (state.hideBig) list = list.filter((o) => o.reward_type !== "fixed" || o.bestTier.minSpend < 100);
    if (state.query) {
      const q = state.query.toLowerCase();
      list = list.filter((o) => [o.merchant, o.domain, o.headline, o.pill, o.event_name, ...o.tiers.map((t) => t.name)].join(" ").toLowerCase().includes(q));
    }
    const sorters = {
      value: (a, b) => b.score - a.score || b.amount - a.amount,
      amount: (a, b) => (b.reward_type === "fixed") - (a.reward_type === "fixed") || b.amount - a.amount,
      net: (a, b) => ((b.bestTier.net ?? -1e9) - (a.bestTier.net ?? -1e9)) || b.score - a.score,
      ending: (a, b) => (a.ends_at ? new Date(a.ends_at) : 8.64e15) - (b.ends_at ? new Date(b.ends_at) : 8.64e15) || b.score - a.score,
      new: (a, b) => (b.new_today ? 1 : 0) - (a.new_today ? 1 : 0) || b.score - a.score,
    };
    list.sort(sorters[state.sort] || sorters.value);
    return list;
  }

  // ---------- rendering ----------
  function render() {
    const list = visibleOffers();
    const podium = $("#podium");
    const listEl = $("#list");
    podium.innerHTML = "";
    listEl.innerHTML = "";
    const showPodium = state.sort === "value" && !state.query;
    const top = showPodium ? list.slice(0, 3) : [];
    const rest = showPodium ? list.slice(3) : list;
    top.forEach((o, i) => podium.appendChild(card(o, i + 1, true)));
    rest.forEach((o, i) => listEl.appendChild(card(o, i + 1 + top.length, false)));
    $("#listTitle").textContent = state.view === "fixed" ? (showPodium ? "More dollar offers" : "Dollar offers") : "All offers";
    $("#count").textContent = `${list.length} shown`;
    if (!list.length) listEl.innerHTML = `<div class="empty">Nothing matches. ${state.view === "fixed" ? "Try “All offers” or clear the search." : "Try clearing the search."}</div>`;
  }

  function card(o, rank, big) {
    const tpl = $("#card-tpl").content.cloneNode(true);
    const el = $(".card", tpl);
    const t = o.bestTier;
    el.dataset.id = o.id;
    if (o.reward_type !== "fixed") el.classList.add("is-pct");

    const rankEl = $(".rank", el);
    rankEl.textContent = `#${rank}`;
    if (rank <= 3 && state.sort === "value") rankEl.classList.add("top");

    const logoWrap = $(".logo-wrap", el);
    const img = $(".logo", el);
    $(".logo-fallback", el).textContent = (o.merchant || "?").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "?";
    if (o.logo) { img.src = o.logo; img.onerror = () => logoWrap.classList.add("no-img"); } else logoWrap.classList.add("no-img");

    $(".merchant", el).textContent = o.merchant;
    const chips = $(".chips", el);
    if (o.new_today) chips.appendChild(chip("NEW today", "new"));
    if (o.pill && !/rewards offer/i.test(o.pill)) chips.appendChild(chip(o.pill, "event"));
    const d = daysLeft(o.ends_at);
    if (d != null) chips.appendChild(chip(d <= 0 ? "Ends today" : d === 1 ? "Ends tomorrow" : `Ends in ${d} days`, "ends"));
    if (o.tiers.length > 1) chips.appendChild(chip(`${o.tiers.length} tiers`, ""));

    const tierLabel = t.name ? `Best tier: ${t.name}` : (o.headline && !/^Save at/i.test(o.headline) ? o.headline : "");
    $(".tier-name", el).textContent = tierLabel;

    $(".fact.cash .big", el).textContent = o.reward_type === "fixed" ? money(t.amount) : `${t.amount}%`;
    const spendFact = $(".fact.spend", el);
    if (o.reward_type === "fixed") {
      const btn = $(".spend-btn", el);
      btn.textContent = `~${money(t.minSpend)}`;
      btn.addEventListener("click", () => editSpend(btn, o, t));
      const src = $(".src", el);
      src.textContent = t.source;
      src.classList.add(t.source);
      src.title = (t.min_spend_note || "") + (t.source === "override" ? ` · your value (was $${fmt(t.min_spend)})` : "");
    } else {
      spendFact.innerHTML = `<span class="big">any</span><span class="lbl">min spend</span>`;
    }
    $(".fact.ratio .big", el).textContent = ratioText(t.ratio);
    $(".fact.ratio .lbl", el).textContent = o.reward_type === "fixed" ? "back per $1" : "back per $1";
    const netEl = $(".fact.net .big", el);
    if (t.net == null) { netEl.textContent = "—"; } else { netEl.textContent = (t.net >= 0 ? "+" : "−") + money(Math.abs(t.net)); netEl.classList.add(t.net >= 0 ? "pos" : "neg"); }

    const v = verdict(o);
    const ver = $(".verdict", el);
    ver.textContent = v.text;
    ver.classList.add(v.cls);
    const fill = $(".bar-fill", el);
    const pct = t.ratio === Infinity ? 100 : Math.min(100, (t.ratio / 3) * 100);
    fill.style.width = `${Math.max(3, pct)}%`;
    if (v.cls === "warn") fill.classList.add("warn");

    const go = $(".go", el);
    go.href = o.href || o.event_href || "https://capitaloneshopping.com/";
    go.textContent = o.event_href && !o.href ? "View event" : "Get offer";

    const more = $(".more", el);
    const details = $(".details", el);
    const open = state.expanded.has(o.id);
    details.hidden = !open;
    more.setAttribute("aria-expanded", String(open));
    more.textContent = open ? "Hide" : "Details";
    more.addEventListener("click", () => {
      if (state.expanded.has(o.id)) state.expanded.delete(o.id); else state.expanded.add(o.id);
      render();
    });
    if (open) fillDetails(details, o);
    return tpl;
  }

  function chip(text, cls) { const s = document.createElement("span"); s.className = `chip ${cls}`; s.textContent = text; return s; }

  function fillDetails(details, o) {
    const tiers = $(".tiers", details);
    if (o.reward_type === "fixed") {
      const rows = o.tiers.map((t, i) => `
        <tr class="${i === o.best ? "best" : ""}">
          <td>${esc(t.name || o.headline || "Offer")}${i === o.best ? " <span class=\"chip new\">best</span>" : ""}</td>
          <td class="num">${money(t.amount)}</td>
          <td class="num"><button type="button" class="spend-btn" data-key="${esc(t.key)}">~${money(t.minSpend)}</button> <span class="src ${t.source}" title="${esc(t.min_spend_note || "")}">${t.source}</span>${t.source === "override" ? `<button type="button" class="reset" data-reset="${esc(t.key)}">reset</button>` : ""}</td>
          <td class="num">${ratioText(t.ratio)}</td>
          <td class="num">${t.net == null ? "—" : (t.net >= 0 ? "+" : "−") + money(Math.abs(t.net))}</td>
        </tr>`).join("");
      tiers.innerHTML = `<table><thead><tr><th>Tier</th><th>Cashback</th><th>Min spend (click to edit)</th><th>Back per $1</th><th>Net</th></tr></thead><tbody>${rows}</tbody></table>`;
      $$(".spend-btn", tiers).forEach((btn) => {
        const t = o.tiers.find((x) => x.key === btn.dataset.key);
        btn.addEventListener("click", () => editSpend(btn, o, t));
      });
      $$(".reset", tiers).forEach((btn) => btn.addEventListener("click", () => { delete state.overrides[btn.dataset.reset]; saveOverrides(); render(); }));
    } else {
      tiers.innerHTML = o.tiers.length > 1 ? `<table><thead><tr><th>Tier</th><th>Rate</th></tr></thead><tbody>${o.tiers.map((t) => `<tr><td>${esc(t.name)}</td><td class="num">${t.amount}%</td></tr>`).join("")}</tbody></table>` : "";
    }
    const note = $(".note", details);
    note.textContent = o.reward_type === "fixed" ? `Min spend estimate: ${o.bestTier.min_spend_note || "—"}${o.parsed_threshold ? ` · Fine print threshold: $${fmt(o.parsed_threshold)}` : ""}` : "";
    $(".excl", details).textContent = o.exclusions ? `Fine print: ${o.exclusions}` : "No exclusions listed.";
    const meta = [];
    if (o.event_name) meta.push(`Event: ${o.event_name}`);
    if (o.ends_at) meta.push(`Ends ${new Date(o.ends_at).toLocaleString()}`);
    meta.push(`Seen in: ${o.sources.join(", ")}`);
    if (o.domain) meta.push(o.domain);
    $(".meta", details).textContent = meta.join(" · ");
  }

  function editSpend(btn, o, t) {
    const input = document.createElement("input");
    input.type = "number"; input.min = "0"; input.step = "0.01"; input.className = "spend-input";
    input.value = t.minSpend == null ? "" : String(+t.minSpend.toFixed(2));
    btn.replaceWith(input);
    input.focus(); input.select();
    const commit = () => {
      const v = parseFloat(input.value);
      if (!Number.isNaN(v) && v >= 0) { state.overrides[t.key] = v; saveOverrides(); }
      render();
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") render(); });
    input.addEventListener("blur", commit);
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- data loading ----------
  async function load(force = false) {
    const btn = $("#refresh");
    btn.disabled = true; btn.textContent = force ? "↻ Refreshing…" : "↻ Loading…";
    $("#updated").textContent = force ? "Pulling today's offers from Capital One Shopping…" : "Loading…";
    try {
      const res = await fetch(force ? "/api/refresh" : "/api/offers", { method: force ? "POST" : "GET", cache: "no-store" });
      const data = await res.json();
      if (!res.ok || !data.offers) throw new Error(data.error || data.last_error || `HTTP ${res.status}`);
      state.data = data;
      const when = new Date(data.generated_at);
      $("#updated").textContent = `Updated ${when.toLocaleString()} · ${data.fixed_offers} dollar offers of ${data.unique_offers} total`;
      const notice = $("#notice");
      if (data.status && data.status.last_error) { notice.hidden = false; notice.className = "notice"; notice.textContent = `Last refresh failed (${data.status.last_error}). Showing the previous data.`; }
      else notice.hidden = true;
      render();
    } catch (err) {
      const notice = $("#notice");
      notice.hidden = false; notice.className = "notice err";
      notice.textContent = `Could not load offers: ${err.message}. Is server.py running? Try Refresh.`;
      $("#updated").textContent = "No data";
    } finally {
      btn.disabled = false; btn.textContent = "↻ Refresh";
    }
  }

  // ---------- wiring ----------
  $$(".seg-btn").forEach((b) => b.addEventListener("click", () => {
    $$(".seg-btn").forEach((x) => { x.classList.toggle("is-on", x === b); x.setAttribute("aria-selected", String(x === b)); });
    state.view = b.dataset.view; render();
  }));
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; render(); });
  $("#search").addEventListener("input", (e) => { state.query = e.target.value.trim(); render(); });
  $("#hideBig").addEventListener("change", (e) => { state.hideBig = e.target.checked; render(); });
  $("#refresh").addEventListener("click", () => load(true));
  load();
})();
