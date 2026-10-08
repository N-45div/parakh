const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const STEPS = { gstin: "GSTIN", registry: "GST registries", company: "Company registry", phone: "Phone number", listing: "Google Maps", reviews: "Reviews", news: "News", court: "Court records", complaints: "Complaints", judge: "Open model" };
const STATUS = { strike_off: "struck off", under_liquidation: "under liquidation" };
const ENGINE = { google: "Google Search", google_maps: "Google Maps", google_maps_reviews: "Google Maps Reviews", google_news: "Google News" };
const VERDICT = { hold: "Hold", verify: "Verify first", clear: "No red flags" };

async function status() {
  const s = await (await fetch("/api/status")).json();
  $("#status").innerHTML = `<span class="${s.serpapi ? "on" : "off"}">SerpApi ${s.serpapi ? "connected" : "missing key"}</span>
    <span class="${s.model ? "on" : "off"}">${s.model ? esc(s.model) + " on Tinker" : "No model key: keyword labels"}</span>`;
}

// Briefs are private to the browser that ran them: only their IDs are kept here, never shared
const mine = () => { try { return JSON.parse(localStorage.getItem("parakh-checks") || "[]"); } catch { return []; } };
const keep = (b) => { try { localStorage.setItem("parakh-checks", JSON.stringify([{ id: b.id, name: b.vendor.name, city: b.vendor.city, verdict: b.verdict, created_at: b.created_at }, ...mine().filter((c) => c.id !== b.id)].slice(0, 12))); } catch {} };
const row = (c, note) => `<li><button data-id="${c.id}"><span class="dot ${c.verdict}"></span><b>${esc(c.name)}</b>
  <small>${esc(note || c.city + " · " + new Date(c.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }))}</small></button></li>`;

async function recent() {
  const own = mine();
  $("#recent").innerHTML = own.length ? own.map((c) => row(c)).join("") : `<li class="fine">None yet. Your checks stay in this browser.</li>`;
  const examples = await (await fetch("/api/examples")).json();
  $("#examples").innerHTML = examples.map((c) => row(c, `${c.city}${c.gstin ? " · " + c.gstin : ""}${c.note ? " · " + c.note : ""}`)).join("");
  $("#examples-panel").hidden = !examples.length;
  document.querySelectorAll(".side li button").forEach((b) => b.onclick = async () => show(await (await fetch(`/api/checks/${b.dataset.id}`)).json()));
}

function step(e) {
  const li = document.createElement("li");
  const n = e.results === undefined ? "" : e.error ? `<em class="err">${esc(e.error)}</em>` : `<em>${e.results} result${e.results === 1 ? "" : "s"}${e.cached ? " · cached" : ""}</em>`;
  li.innerHTML = `<span class="tick"></span><b>${STEPS[e.step] || e.step}</b><span>${esc(e.detail)}</span>${n}`;
  $("#progress").appendChild(li);
}

const source = (f) => [f.publisher, f.date].filter(Boolean).map(esc).join(" · ");
const quote = (f) => f.quote ? `<blockquote>“${esc(f.quote)}”</blockquote>` : "";
const link = (href, text) => href ? `<a href="${esc(href)}" target="_blank" rel="noreferrer">${text}</a>` : "";

function flag(f) {
  const items = f.items ? `<details><summary>Show ${f.items.length}</summary><ul>${f.items.map((i) => `<li>${esc(i.text)} ${link(i.link, "Source")}</li>`).join("")}</ul></details>` : "";
  return `<li class="flag ${f.severity}"><span class="sev">${f.severity}</span><div><p>${esc(f.text)}</p>${quote(f)}
    <div class="meta">${esc(f.source)}${source(f) ? " · " + source(f) : ""} ${link(f.link, "Open source ↗")}</div>${items}</div></li>`;
}

function show(b) {
  $("#empty").hidden = true;
  const g = b.identity.gstin, r = b.identity.registry, l = b.identity.listing;
  const gstRows = g.given ? (g.valid ? `<dt>GSTIN</dt><dd class="mono">${esc(g.gstin)}</dd><dt>State</dt><dd>${esc(g.state || "Unknown code " + g.state_code)}</dd>
      <dt>PAN</dt><dd class="mono">${esc(g.pan)} · ${esc(g.entity_type || "unknown type")}</dd><dt>Registration</dt><dd>No. ${g.registration_number} under this PAN in ${esc(g.state)}</dd>`
      : `<dt>GSTIN</dt><dd class="mono bad">${esc(g.gstin)} · not valid</dd>`) : `<dt>GSTIN</dt><dd>Not given</dd>`;
  const regRows = r.status ? `<dt>Directory status</dt><dd><span class="pill ${r.status}">${esc(r.status)}</span> ${r.sources.slice(0, 2).map((s) => link(s.link, "source")).join(" ")}</dd>
      ${r.registered_on ? `<dt>GST registered</dt><dd>${esc(r.registered_on)}</dd>` : ""}
      ${r.legal_names.length ? `<dt>Legal name seen</dt><dd>${r.legal_names.slice(0, 3).map(esc).join("<br>")}</dd>` : ""}` : g.given && g.valid ? `<dt>Directory status</dt><dd>Not found in public directories</dd>` : "";
  const c = b.identity.company;
  const companyRows = c ? `<dt>Company record</dt><dd>${c.status ? `<span class="pill ${c.status}">${esc(STATUS[c.status] || c.status)}</span> ` : ""}${c.sources.slice(0, 2).map((s) => link(s.link, "source")).join(" ")}
      ${c.incorporated ? `<br>Incorporated ${esc(c.incorporated)}` : ""}${c.cin ? `<br><span class="mono">${esc(c.cin)}</span>` : ""}</dd>` : "";
  const mapRows = l ? `<dt>Google Maps</dt><dd>${esc(l.title)}<br><small>${esc(l.address || "")}</small><br>
      ${l.rating ? `${l.rating}★ from ${l.reviews} reviews · ` : ""}${esc(l.type || "")} ${link(l.maps_link, "Open in Maps ↗")}</dd>` : `<dt>Google Maps</dt><dd>No listing found</dd>`;
  const reads = Object.entries(b.read).map(([k, v]) => `${STEPS[k] || k}: ${v.read} read, ${v.about_vendor} about this supplier`).join(" · ");
  $("#brief").innerHTML = `
    <div class="verdict ${b.verdict}"><span class="label">${VERDICT[b.verdict]}</span><h2>${esc(b.headline)}</h2>
      <p>${esc(b.vendor.name)} · ${esc(b.vendor.city)}${b.vendor.gstin ? " · " + esc(b.vendor.gstin) : ""}</p>
      <div class="actions"><button onclick="copyText()">Copy for WhatsApp</button><button onclick="copyLink()">Copy link</button><button onclick="window.print()">Save as PDF</button></div></div>
    <div class="grid">
      <section class="panel"><h3>Who they are</h3><dl>${gstRows}${regRows}${companyRows}${mapRows}</dl></section>
      <section class="panel"><h3>Before you pay</h3><ol class="steps">${b.next_steps.map((s) => `<li>${esc(s.text)} ${link(s.link, "Open ↗")}</li>`).join("")}</ol></section>
    </div>
    <section class="panel"><h3>What the public record shows <small>${b.flags.length ? b.flags.length + " finding" + (b.flags.length > 1 ? "s" : "") : ""}</small></h3>
      ${b.flags.length ? `<ul class="flags">${b.flags.map(flag).join("")}</ul>` : `<p class="fine">Nothing in the searched sources raises a concern about this supplier.</p>`}</section>
    ${b.clashes.length ? `<section class="panel"><h3>Possibly a different business with a similar name <small>rule these out</small></h3>
      <ul class="flags">${b.clashes.map(flag).join("")}</ul></section>` : ""}
    <section class="panel"><h3>What this check cannot tell you</h3><ul class="limits">${b.limits.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></section>
    <section class="panel searches"><h3>Searches run <small>${b.searches.length} SerpApi calls · ${esc(b.model)}</small></h3>
      <table><thead><tr><th>Purpose</th><th>SerpApi engine</th><th>Query</th><th>Results</th></tr></thead><tbody>
      ${b.searches.map((s) => `<tr><td>${esc(s.purpose)}</td><td>${ENGINE[s.engine] || esc(s.engine)}</td><td class="mono">${esc(s.query)}</td>
        <td>${s.error ? `<span class="bad">${esc(s.error)}</span>` : s.results}${s.cached ? " <small>cached</small>" : ""}</td></tr>`).join("")}</tbody></table>
      <p class="fine">${esc(reads)}</p></section>`;
  $("#brief").hidden = false;
  current = b;
  history.replaceState(null, "", `?check=${b.id}`);
}

let current = null;
const SEV = { high: "HIGH", medium: "MEDIUM", low: "low" };
function summary(b) {
  const r = b.identity.registry, c = b.identity.company;
  const lines = [`*Parakh check: ${b.vendor.name}, ${b.vendor.city}*`, `${VERDICT[b.verdict]}: ${b.headline}`];
  if (b.vendor.gstin) lines.push(`GSTIN ${b.vendor.gstin}${r.status ? `: ${r.status} in public directories` : ""}${r.registered_on ? `, registered ${r.registered_on}` : ""}`);
  if (c && c.status) lines.push(`Company: ${STATUS[c.status] || c.status}${c.incorporated ? `, incorporated ${c.incorporated}` : ""}`);
  const serious = b.flags.filter((f) => f.severity !== "low");
  if (serious.length) lines.push("", "Findings:", ...serious.map((f) => `• [${SEV[f.severity]}] ${f.text}${f.link ? ` ${f.link}` : ""}`));
  lines.push("", "Before you pay:", ...b.next_steps.map((s, i) => `${i + 1}. ${s.text}`), "", `Full brief: ${location.origin}/?check=${b.id}`);
  return lines.join("\n");
}
async function copyText() { await navigator.clipboard.writeText(summary(current)); toast("Summary copied. Paste it into WhatsApp."); }
async function copyLink() { await navigator.clipboard.writeText(`${location.origin}/?check=${current.id}`); toast("Link copied. Anyone with it can open this brief."); }
function toast(text) { const t = document.createElement("div"); t.className = "toast"; t.textContent = text; document.body.appendChild(t); setTimeout(() => t.remove(), 2600); }

$("#form").onsubmit = async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.target));
  $("#go").disabled = true; $("#go").textContent = "Checking…";
  $("#empty").hidden = true; $("#brief").hidden = true;
  $("#progress").innerHTML = ""; $("#progress").hidden = false;
  try {
    const response = await fetch("/api/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!response.ok) { const d = (await response.json()).detail; throw new Error(typeof d === "string" ? d : d?.[0]?.msg || "Check failed"); }
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const e = JSON.parse(buffer.slice(0, nl)); buffer = buffer.slice(nl + 1);
        if (e.step === "done") { $("#progress").hidden = true; keep(e.brief); show(e.brief); recent(); } else step(e);
      }
    }
  } catch (error) {
    step({ step: "error", detail: error.message });
  } finally {
    $("#go").disabled = false; $("#go").textContent = "Check this supplier";
  }
};

status(); recent();
const shared = new URLSearchParams(location.search).get("check");
if (shared) fetch(`/api/checks/${encodeURIComponent(shared)}`).then((r) => r.ok ? r.json() : null).then((b) => b && show(b));
