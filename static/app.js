/* Best Dollar Offers – front end. No build step, no dependencies. */
(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const OVERRIDE_KEY = "c1-minspend-overrides";

  const state = {
    data: null,
    config: {},
    staticMode: false,
    cardOffers: [],
    minSpendTable: null,
    view: "fixed",
    sort: "value",
    query: "",
    hideBig: false,
    hideLimit: 100,
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
    let list = state.data.offers.concat(state.cardOffers).map(evaluate);
    if (state.view === "fixed") list = list.filter((o) => o.reward_type === "fixed");
    if (state.view === "percent") list = list.filter((o) => o.reward_type !== "fixed");
    if (state.hideBig) list = list.filter((o) => o.reward_type !== "fixed" || o.bestTier.minSpend <= state.hideLimit);
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
    const titles = { fixed: showPodium ? "More dollar offers" : "Dollar offers", percent: showPodium ? "More percent offers" : "Percent offers", all: showPodium ? "More offers" : "All offers" };
    $("#listTitle").textContent = titles[state.view] || "Offers";
    $("#count").textContent = `${list.length} shown`;
    $(".check").style.display = state.view === "percent" ? "none" : "";
    if (!list.length) listEl.innerHTML = `<div class="empty">Nothing matches. ${state.view === "fixed" ? "Try “Percent offers”, raise the hide limit, or clear the search." : "Try clearing the search."}</div>`;
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
    if (o.card_offer) chips.appendChild(chip("Your card offer", "card"));
    if (o.new_today) chips.appendChild(chip("NEW today", "new"));
    if (o.pill && !/rewards offer/i.test(o.pill)) chips.appendChild(chip(o.pill, "event"));
    const d = daysLeft(o.ends_at);
    if (d != null) chips.appendChild(chip(d <= 0 ? "Ends today" : d === 1 ? "Ends tomorrow" : `Ends in ${d} days`, "ends"));
    if (o.tiers.length > 1) chips.appendChild(chip(`${o.tiers.length} tiers`, ""));

    const tierLabel = t.name ? `Best tier: ${t.name}` : (o.headline && !/^Save at/i.test(o.headline) ? o.headline : "");
    $(".tier-name", el).textContent = tierLabel;
    renderReqs($(".reqs", el), o, 4);

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
    $(".fact.ratio .big", el).textContent = o.reward_type === "fixed" ? ratioText(t.ratio) : `${Math.round(t.amount)}¢`;
    $(".fact.ratio .lbl", el).textContent = "back per $1";
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
    go.addEventListener("click", () => openClaim(o));

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
    const tags = (o.conditions && o.conditions.tags) || [];
    $(".reqlist", details).textContent = tags.length ? `Requirements: ${tags.join(" · ")}` : "";
    const note = $(".note", details);
    note.textContent = o.reward_type === "fixed" ? `Min spend estimate: ${o.bestTier.min_spend_note || "—"}` : "";
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

  const HARD = /^(Keep it|Order \$|Devices must|New customers|First order|No free trial|No renewals)/;
  function renderReqs(container, o, limit) {
    container.innerHTML = "";
    const tags = (o.conditions && o.conditions.tags) || [];
    const shown = limit ? tags.slice(0, limit) : tags;
    shown.forEach((tag) => { const s = document.createElement("span"); s.className = `req ${HARD.test(tag) ? "hard" : ""}`; s.textContent = tag; container.appendChild(s); });
    if (limit && tags.length > limit) { const s = document.createElement("span"); s.className = "req"; s.textContent = `+${tags.length - limit} more`; container.appendChild(s); }
  }

  const modal = $("#claim");
  function openClaim(o) {
    const t = o.bestTier;
    if (o.card_offer) return openCardClaim(o, t);
    $("#claimTitle").textContent = `Claim ${o.merchant} on Capital One Shopping`;
    $("#claimSub").textContent = o.reward_type === "fixed"
      ? `${money(t.amount)} back${t.name ? ` on ${t.name}` : ""} · estimated min spend ${money(t.minSpend)}${t.min_spend_months > 1 ? ` (${t.min_spend_months} months)` : ""}`
      : `${o.cashback_text} back`;
    const join = $("#claimJoin");
    join.href = state.config.referral_url || "https://capitaloneshopping.com/";
    join.textContent = state.config.referral_url ? "Join with referral link / sign in" : "Join / sign in";
    renderReqs($("#claimReqs"), o, 0);
    $("#claimExcl").textContent = o.exclusions ? `Fine print: ${o.exclusions}` : "";
    const go = $("#claimGo");
    const target = o.store_url || o.event_href || "https://capitaloneshopping.com/";
    go.href = target;
    go.textContent = o.store_url ? `Open ${o.merchant} on Capital One Shopping` : (o.event_href ? "Open this event on Capital One Shopping" : "Open Capital One Shopping");
    modal.hidden = false;
    go.focus();
  }
  function openCardClaim(o, t) {
    $("#claimTitle").textContent = `Add the ${o.merchant} offer to your card`;
    $("#claimSub").textContent = `${o.cashback_text} back · Capital One Offers (card-linked)${o.channel ? ` · ${o.channel}` : ""}`;
    $(".steps", modal).innerHTML = `
      <li><strong>Open Capital One Offers</strong> and sign in to your Capital One account.</li>
      <li><strong>Find ${esc(o.merchant)}</strong> and press <em>Add to card</em>. Offers are personal, so it may not be shown to everyone.</li>
      <li><strong>Pay with that Capital One card</strong>${o.channel ? ` (${esc(o.channel)})` : ""}. The cashback posts to your statement after the purchase settles.</li>`;
    $("#claimJoin").href = "https://capitaloneoffers.com/feed";
    renderReqs($("#claimReqs"), o, 0);
    $("#claimExcl").textContent = "Terms are shown on the offer itself at capitaloneoffers.com. Imported offers keep no fine print, so the min spend here is only the merchant's entry price.";
    const go = $("#claimGo");
    go.href = "https://capitaloneoffers.com/feed";
    go.textContent = "Open Capital One Offers";
    modal.hidden = false;
    go.focus();
  }
  const defaultSteps = $(".steps", modal).innerHTML;
  function closeClaim() { modal.hidden = true; $(".steps", modal).innerHTML = defaultSteps; }
  $("#claimClose").addEventListener("click", closeClaim);
  $("#claimCancel").addEventListener("click", closeClaim);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeClaim(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) closeClaim(); });

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- Capital One Offers (card-linked) import ----------
  const CARD_KEY = "c1-card-offers";
  const BACK_RE = /^(up to\s+)?\$?\s?(\d+(?:\.\d+)?)\s*(%)?\s*back\.?$/i;
  const CHANNEL_RE = /^(online|in[- ]store|in[- ]app|in[- ]store\s*&\s*(online|in[- ]app)|online\s*&\s*in[- ]store)$/i;
  const NOISE_RE = /^(get this offer|added( to card)?|activated?|limited availability\.?|today'?s top offer\.?.*|new offers revealed daily|featured offers for you|additional offers for you|add offers.*|earn by purchasing.*|category|new|apparel|travel & entertainment|home|general retail|.*\b\d{1,2}\/\d{2}\b.*|\d+ of \d+ activated)$/i;

  function loadCardOffers() { try { return JSON.parse(localStorage.getItem(CARD_KEY) || "[]"); } catch { return []; } }
  function saveCardOffers() { try { localStorage.setItem(CARD_KEY, JSON.stringify(state.cardOffers)); } catch {} }
  const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");

  async function loadMinSpendTable() {
    try { const r = await fetch("data/min_spend.json", { cache: "no-store" }); if (r.ok) state.minSpendTable = await r.json(); } catch {}
    if (state.minSpendTable && !state.minSpendTable._index) {
      const idx = {};
      for (const [domain, entry] of Object.entries(state.minSpendTable.merchants || {})) {
        idx[norm(domain)] = domain;
        idx[norm(domain.split(".")[0])] = idx[norm(domain.split(".")[0])] || domain;
        (entry.aliases || []).forEach((a) => { idx[norm(a)] = idx[norm(a)] || domain; });
      }
      state.minSpendTable._index = idx;
    }
  }

  function estimateMinSpend(merchant) {
    const t = state.minSpendTable;
    if (!t) return { min_spend: 50, source: "unknown", note: "Estimate table not loaded", domain: "" };
    const domain = t._index[norm(merchant)];
    if (domain) { const e = t.merchants[domain]; return { min_spend: +e.min_spend, source: "curated", note: e.note || "", domain }; }
    for (const rule of t.merchant_keywords || []) {
      if (new RegExp(rule.match, "i").test(merchant)) return { min_spend: +rule.min_spend, source: "estimated", note: rule.note || "", domain: "" };
    }
    return { min_spend: +(t.fallback || 50), source: "unknown", note: "No estimate available – set it yourself", domain: "" };
  }

  function makeCardOffer(merchant, text, channel) {
    const m = String(text || "").trim().match(BACK_RE);
    if (!m || !merchant) return null;
    const amount = parseFloat(m[2]);
    const isPct = !!m[3];
    const est = estimateMinSpend(merchant);
    const minSpend = isPct ? null : est.min_spend;
    const tier = { name: "", amount, min_spend: minSpend, min_spend_base: minSpend, min_spend_months: 1,
      min_spend_source: isPct ? "n/a" : est.source, min_spend_note: isPct ? "Percentage offer" : est.note,
      ratio: isPct ? amount / 100 : (minSpend > 0 ? amount / minSpend : null), net: isPct ? null : amount - (minSpend || 0) };
    const tags = ["Add to card first"];
    if (channel) tags.unshift(channel);
    return {
      id: `card|${norm(merchant)}|${isPct ? "pct" : "usd"}|${amount}`,
      merchant: merchant.trim(), domain: est.domain, channel: channel || "",
      logo: est.domain ? `https://images.capitaloneshopping.com/api/v1/logos?domain=${est.domain}&height=400&type=cropped&fallback=true` : null,
      cashback_text: `${m[1] ? "up to " : ""}${isPct ? `${amount}%` : `$${amount}`}`,
      reward_type: isPct ? "percentage" : "fixed", amount, max_payout: null,
      tiers: [tier], best_tier_index: 0, headline: `Capital One Offers${channel ? ` · ${channel}` : ""}`,
      pill: null, filter_label: "Capital One Offers", item_type: "card_offer", item_level: "merchant",
      sources: ["capitaloneoffers.com"], ends_at: null, exclusions: "", parsed_threshold: null,
      conditions: { tags, threshold: null, commitment_months: null }, href: null, event_href: null,
      store_url: "https://capitaloneoffers.com/feed", card_offer: true, imported_at: new Date().toISOString(),
    };
  }

  function parseCardText(text) {
    const lines = String(text || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    const found = [];
    lines.forEach((line, i) => {
      if (!BACK_RE.test(line)) return;
      let merchant = null, channel = null;
      for (let j = i - 1; j >= Math.max(0, i - 4); j--) {
        const l = lines[j];
        if (BACK_RE.test(l)) break;
        if (CHANNEL_RE.test(l)) { channel = channel || l; continue; }
        if (NOISE_RE.test(l)) continue;
        merchant = l; break;
      }
      for (let j = i + 1; j <= Math.min(lines.length - 1, i + 2) && !channel; j++) if (CHANNEL_RE.test(lines[j])) channel = lines[j];
      if (merchant) found.push({ merchant, text: line, channel });
    });
    return found;
  }

  function addCardOffers(items) {
    const byId = new Map(state.cardOffers.map((o) => [o.id, o]));
    let added = 0;
    for (const it of items) {
      const o = makeCardOffer(it.merchant, it.text, it.channel);
      if (!o) continue;
      if (!byId.has(o.id)) added++;
      byId.set(o.id, o);
    }
    state.cardOffers = Array.from(byId.values());
    saveCardOffers();
    render();
    updateStatusLine();
    return added;
  }

  function updateStatusLine() {
    const el = $("#updated");
    el.textContent = el.textContent.replace(/ · \d+ card offers? imported/, "");
    if (state.cardOffers.length) el.textContent += ` · ${state.cardOffers.length} card offer${state.cardOffers.length === 1 ? "" : "s"} imported`;
  }

  const importer = $("#importer");
  $("#importBtn").addEventListener("click", () => {
    $("#importStatus").textContent = state.cardOffers.length ? `${state.cardOffers.length} card offers currently imported.` : "";
    importer.hidden = false;
  });
  $("#importClose").addEventListener("click", () => { importer.hidden = true; });
  importer.addEventListener("click", (e) => { if (e.target === importer) importer.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !importer.hidden) importer.hidden = true; });
  $("#importRun").addEventListener("click", () => {
    const items = parseCardText($("#importText").value);
    if (!items.length) { $("#importStatus").textContent = "No offers recognised. Make sure lines like “Up to $37 back” are in the pasted text."; return; }
    const added = addCardOffers(items);
    $("#importStatus").textContent = `Imported ${items.length} offers (${added} new): ${items.slice(0, 6).map((i) => i.merchant).join(", ")}${items.length > 6 ? "…" : ""}.`;
    $("#importText").value = "";
  });
  $("#importClear").addEventListener("click", () => { state.cardOffers = []; saveCardOffers(); render(); updateStatusLine(); $("#importStatus").textContent = "Imported card offers removed."; });

  // ---------- data loading ----------
  async function loadConfig() {
    try { const r = await fetch("config.json", { cache: "no-store" }); if (r.ok) state.config = await r.json(); } catch {}
    if (state.config.site_name) { document.title = state.config.site_name; $(".brand h1").textContent = state.config.site_name; }
  }

  async function fetchOffers(force) {
    // Dynamic mode (server.py) first; fall back to the static file built by build_static.py.
    if (!state.staticMode) {
      try {
        const res = await fetch(force ? "api/refresh" : "api/offers", { method: force ? "POST" : "GET", cache: "no-store" });
        const ct = res.headers.get("content-type") || "";
        if (ct.includes("json")) {
          const data = await res.json();
          if (!res.ok || !data.offers) throw new Error(data.error || data.last_error || `HTTP ${res.status}`);
          return data;
        }
      } catch (err) {
        if (force) throw err;
      }
      state.staticMode = true;
    }
    const res = await fetch("data/offers.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status} loading data/offers.json`);
    return res.json();
  }

  async function load(force = false) {
    const btn = $("#refresh");
    btn.disabled = true; btn.textContent = force ? "↻ Refreshing…" : "↻ Loading…";
    $("#updated").textContent = force ? "Pulling today's offers from Capital One Shopping…" : "Loading…";
    try {
      const data = await fetchOffers(force);
      state.data = data;
      const when = new Date(data.generated_at);
      $("#updated").textContent = `Updated ${when.toLocaleString()} · ${data.fixed_offers} dollar offers of ${data.unique_offers} total`;
      const notice = $("#notice");
      if (data.status && data.status.last_error) { notice.hidden = false; notice.className = "notice"; notice.textContent = `Last refresh failed (${data.status.last_error}). Showing the previous data.`; }
      else notice.hidden = true;
      if (state.staticMode) { btn.hidden = true; $("#updated").textContent += " · auto-updates every 6 hours"; }
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
  // Hide-expensive filter: checkbox + editable dollar limit, both remembered in this browser.
  const PREFS_KEY = "c1-filter-prefs";
  try {
    const prefs = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    if (typeof prefs.hideBig === "boolean") state.hideBig = prefs.hideBig;
    if (Number.isFinite(prefs.hideLimit) && prefs.hideLimit >= 0) state.hideLimit = prefs.hideLimit;
  } catch {}
  $("#hideBig").checked = state.hideBig;
  $("#hideLimit").value = String(state.hideLimit);
  const savePrefs = () => { try { localStorage.setItem(PREFS_KEY, JSON.stringify({ hideBig: state.hideBig, hideLimit: state.hideLimit })); } catch {} };
  $("#hideBig").addEventListener("change", (e) => { state.hideBig = e.target.checked; savePrefs(); render(); });
  $("#hideLimit").addEventListener("input", (e) => {
    const v = parseFloat(e.target.value);
    if (Number.isFinite(v) && v >= 0) { state.hideLimit = v; if (!state.hideBig) { state.hideBig = true; $("#hideBig").checked = true; } savePrefs(); render(); }
  });
  $("#hideLimit").addEventListener("click", (e) => e.preventDefault());
  $("#refresh").addEventListener("click", () => load(true));
  loadConfig().then(loadMinSpendTable).then(() => { state.cardOffers = loadCardOffers(); return load(); }).then(() => updateStatusLine());
})();
