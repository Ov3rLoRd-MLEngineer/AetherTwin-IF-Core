"use strict";
// Accueil : état du PC façon Gestionnaire des tâches, lecteurs et périphériques, fiche système, carte mère
// (capteurs, ventilateurs), Inoue (optimisation) et outils ASUS. Dépend de dashboard.js : $, el, api, post.

const sys = { live: null, info: null, sensors: null, perf: "cpu", timer: 0, loaded: {} };
const SYS_POLL = { "Performance": 1500, "Carte mère": 3000 };

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#3b5bdb";
const num = (v, digits = 0) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR",
  { maximumFractionDigits: digits, minimumFractionDigits: digits }));
const rate = (ko) => (ko >= 1024 ? `${num(ko / 1024, 1)} Mo/s` : `${num(ko, 0)} Ko/s`);
const goTo = (go) => (go >= 1000 ? `${num(go / 1024, 2)} To` : `${num(go, 0)} Go`);
function duration(seconds) {
  const d = Math.floor(seconds / 86400), h = Math.floor(seconds % 86400 / 3600), m = Math.floor(seconds % 3600 / 60);
  return `${d}:${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}
function note(box, text, cls = "muted") { box.replaceChildren(el("p", { class: cls }, text)); }

// ---------- fenêtres de Windows et outils : listes fermées côté serveur ----------
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-open], [data-tool], [data-drive]");
  if (!button || !button.closest("section.sys")) return;  // calc_geo a aussi des data-tool
  button.disabled = true;
  try {
    if (button.dataset.tool) await post("/system/tools/launch", { outil: button.dataset.tool });
    else if (button.dataset.drive) await post("/system/open", { cible: "lecteur", lecteur: button.dataset.drive });
    else await post("/system/open", { cible: button.dataset.open });
  } catch (error) {
    alert(`Ouverture impossible : ${error.message}`);
  } finally {
    setTimeout(() => { button.disabled = false; }, 800);
  }
});

// ---------- courbes ----------
function drawSeries(canvas, values, { max = 100, fill = true, grid = false } = {}) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || canvas.width, height = canvas.clientHeight || canvas.height;
  if (canvas.width !== Math.round(width * ratio)) { canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const color = css("--accent");
  if (grid) {
    ctx.strokeStyle = css("--line");
    ctx.lineWidth = 1;
    for (let i = 1; i < 10; i++) { const x = Math.round(width * i / 10) + 0.5; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke(); }
    for (let i = 1; i < 5; i++) { const y = Math.round(height * i / 5) + 0.5; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke(); }
    ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
  }
  if (!values || values.length < 2) return;
  const step = width / 59, start = width - step * (values.length - 1);
  const y = (v) => height - Math.max(0, Math.min(1, v / max)) * (height - 2) - 1;
  ctx.beginPath();
  values.forEach((v, i) => (i ? ctx.lineTo(start + i * step, y(v)) : ctx.moveTo(start, y(v))));
  ctx.strokeStyle = color;
  ctx.lineWidth = grid ? 2 : 1.5;
  ctx.stroke();
  if (fill) {
    ctx.lineTo(width, height); ctx.lineTo(start, height); ctx.closePath();
    ctx.globalAlpha = 0.15; ctx.fillStyle = color; ctx.fill(); ctx.globalAlpha = 1;
  }
}

// ---------- Performance (comme le Gestionnaire des tâches) ----------
function perfEntries(live) {
  const h = live.historique || {}, info = sys.info || {};
  const entries = [{ key: "cpu", title: "Processeur", sub: `${num(live.cpu.utilisation_pct)} % ${live.cpu.frequence_mhz ? `${num(live.cpu.frequence_mhz / 1000, 2)} GHz` : ""}`,
    series: h.cpu, max: 100 },
  { key: "memoire", title: "Mémoire", sub: `${num(live.memoire.utilisee_go, 1)}/${num(live.memoire.totale_go, 1)} Go (${num(live.memoire.pct)} %)`,
    series: h.memoire, max: 100 }];
  for (const [name, r] of Object.entries(live.disques || {})) {
    const index = Number((name.match(/\d+$/) || [""])[0]);
    const vols = (info.volumes || []).filter((v) => v.disque_numero === index).map((v) => v.lecteur);
    const disk = (info.disques || []).find((d) => d.numero === index);
    entries.push({ key: `disque:${name}`, title: `Disque ${num(index)}${vols.length ? ` (${vols.join(" ")})` : ""}`,
      sub: `${disk ? `${disk.type || ""} ${disk.bus || ""}`.trim() : ""} ${rate(r.lecture_ko_s + r.ecriture_ko_s)}`.trim(),
      series: h[`disque:${name}`], max: 100, disk: r, model: disk ? disk.nom : name });
  }
  for (const [name, r] of Object.entries(live.reseau || {})) {
    if (!r.vitesse_mbit && !(r.recu_ko_s + r.envoye_ko_s)) continue;
    const series = h[`reseau:${name}`] || [];
    entries.push({ key: `reseau:${name}`, title: /wi-?fi|wlan|sans fil/i.test(name) ? "Wi-Fi" : "Ethernet",
      sub: `${name} · E : ${rate(r.envoye_ko_s)} R : ${rate(r.recu_ko_s)}`, series,
      max: Math.max(100, ...series) * 1.2, net: r, model: name });
  }
  for (const g of live.gpus || []) {
    entries.push({ key: `gpu:${g.index}`, title: `GPU ${g.index}`, sub: `${g.nom.replace(/^NVIDIA (GeForce )?/, "")} · ${num(g.utilisation_pct)} %`
      + (g.temperature_c !== null && g.temperature_c !== undefined ? ` (${g.temperature_c} °C)` : ""),
    series: h[`gpu:${g.index}`], max: 100, gpu: g, model: g.nom });
  }
  return entries;
}

function perfDetails(entry, live) {
  const cells = [];
  const add = (label, value) => cells.push(el("div", {}, el("span", { class: "muted" }, label), el("b", {}, value)));
  const info = sys.info || {};
  if (entry.key === "cpu") {
    const c = live.cpu, cpu = (info.cpu || [])[0] || {};
    add("Utilisation", `${num(c.utilisation_pct)} %`);
    add("Vitesse", c.frequence_mhz ? `${num(c.frequence_mhz / 1000, 2)} GHz` : "—");
    add("Processus", num(c.processus)); add("Threads", num(c.threads)); add("Handles", num(c.handles));
    add("Temps d'activité", duration(c.duree_fonctionnement_s || 0));
    add("Vitesse de base", cpu.base_mhz ? `${num(cpu.base_mhz / 1000, 2)} GHz` : "—");
    add("Sockets", "1"); add("Cœurs", num(cpu.coeurs)); add("Processeurs logiques", num(cpu.logiques || c.coeurs_pct.length));
    add("Virtualisation", cpu.virtualisation ? "Activé" : "Désactivé");
    add("Cache L2", cpu.l2_ko ? `${num(cpu.l2_ko / 1024, 1)} Mo` : "—"); add("Cache L3", cpu.l3_ko ? `${num(cpu.l3_ko / 1024, 1)} Mo` : "—");
  } else if (entry.key === "memoire") {
    const m = live.memoire, ram = info.memoire || [];
    add("Utilisée", `${num(m.utilisee_go, 1)} Go`); add("Disponible", `${num(m.disponible_go, 1)} Go`);
    add("Validée (échange)", `${num(m.echange_go, 1)}/${num(m.echange_total_go, 1)} Go`);
    add("Vitesse", ram.length && ram[0].vitesse ? `${num(ram[0].vitesse)} MHz` : "—");
    add("Emplacements utilisés", ram.length ? `${ram.length}` : "—");
    add("Barrettes", ram.map((r) => `${r.taille_go} Go`).join(" + ") || "—");
  } else if (entry.disk) {
    const d = entry.disk;
    add("Lecture", rate(d.lecture_ko_s)); add("Écriture", rate(d.ecriture_ko_s));
    add("Temps d'activité", d.actif_pct === null || d.actif_pct === undefined ? "non mesuré par Windows ici" : `${num(d.actif_pct)} %`);
  } else if (entry.net) {
    const n = entry.net;
    add("Envoi", rate(n.envoye_ko_s)); add("Réception", rate(n.recu_ko_s));
    add("Vitesse de la liaison", n.vitesse_mbit ? `${num(n.vitesse_mbit)} Mbit/s` : "—");
  } else if (entry.gpu) {
    const g = entry.gpu;
    add("Utilisation", `${num(g.utilisation_pct)} %`);
    add("Mémoire dédiée", `${num(g.memoire_utilisee_go, 1)}/${num(g.memoire_totale_go, 1)} Go`);
    add("Température", g.temperature_c === null || g.temperature_c === undefined ? "—" : `${g.temperature_c} °C`);
    add("Ventilateur", g.ventilateur_pct === null || g.ventilateur_pct === undefined ? "—" : `${g.ventilateur_pct} %`);
    add("Puissance", g.puissance_w ? `${num(g.puissance_w)} W / ${num(g.limite_puissance_w)} W` : "—");
    add("Fréquence GPU", g.frequence_gpu_mhz ? `${num(g.frequence_gpu_mhz)} MHz (max ${num(g.frequence_max_mhz)})` : "—");
    add("Fréquence mémoire", g.frequence_memoire_mhz ? `${num(g.frequence_memoire_mhz)} MHz` : "—");
    add("Pilote", g.pilote || "—"); add("Liaison", g.pcie || "—");
  }
  return cells;
}

function renderPerf() {
  const live = sys.live;
  if (!live) return;
  const entries = perfEntries(live);
  if (!entries.some((e) => e.key === sys.perf)) sys.perf = "cpu";
  const list = $("perf-list");
  if (list.dataset.keys !== entries.map((e) => e.key).join("|")) {
    list.dataset.keys = entries.map((e) => e.key).join("|");
    list.replaceChildren(...entries.map((e) => {
      const b = el("button", { type: "button", role: "tab", "data-key": e.key },
        el("canvas", { class: "spark", width: "70", height: "40", "aria-hidden": "true" }),
        el("span", {}, el("b", {}, e.title), el("small", { class: "muted" }, "")));
      b.addEventListener("click", () => { sys.perf = e.key; renderPerf(); });
      return b;
    }));
  }
  for (const e of entries) {
    const b = list.querySelector(`[data-key="${CSS.escape(e.key)}"]`);
    b.setAttribute("aria-selected", String(e.key === sys.perf));
    b.querySelector("b").textContent = e.title;
    b.querySelector("small").textContent = e.sub;
    drawSeries(b.querySelector("canvas"), e.series, { max: e.max });
  }
  const current = entries.find((e) => e.key === sys.perf);
  const cpuName = ((sys.info || {}).cpu || [])[0];
  $("perf-name").textContent = current.title;
  $("perf-model").textContent = current.model || (current.key === "cpu" && cpuName ? cpuName.nom
    : current.key === "memoire" ? `${num(live.memoire.totale_go, 1)} Go` : "");
  $("perf-axis").replaceChildren(el("span", {}, current.net ? "Débit (Ko/s)" : "% d'utilisation"),
    el("span", {}, current.net ? rate(current.max) : "100 %"));
  drawSeries($("perf-chart"), current.series, { max: current.max, grid: true });
  $("perf-details").replaceChildren(...perfDetails(current, live));
}

// ---------- lecteurs et périphériques ----------
function renderDrives(info) {
  const vols = info.volumes || [];
  $("sys-drives").replaceChildren(...(vols.length ? vols.map((v) => {
    const fill = el("i", {});
    fill.style.width = `${Math.min(100, v.pct)}%`;
    if (v.pct >= 90) fill.classList.add("full");
    return el("button", { type: "button", class: "drive", "data-drive": v.lecteur, title: `Ouvrir ${v.lecteur} dans l'Explorateur` },
      el("span", { class: "drive-icon", "aria-hidden": "true" }),
      el("span", {}, el("b", {}, `${v.nom} (${v.lecteur})`), el("span", { class: "bar" }, fill),
        el("small", { class: "muted" }, `${goTo(v.libre_go)} libres sur ${goTo(v.total_go)}`),
        el("small", { class: "muted" }, [v.disque, v.systeme_fichiers].filter(Boolean).join(" · "))));
  }) : [el("p", { class: "muted" }, "Lecteurs illisibles pour l'instant.")]));
}

async function loadDevices(refresh = false) {
  try {
    const data = await api(`/system/devices${refresh ? "?refresh=true" : ""}`);
    $("sys-devices").replaceChildren(...data.groupes.map((g) => el("details", { class: "dev-group-box", open: "" },
      el("summary", {}, el("b", {}, g.nom), el("span", { class: "muted" }, ` ${g.appareils.length}`)),
      el("ul", {}, ...g.appareils.map((d) => el("li", { class: d.etat === "ok" ? "" : "warn" },
        d.nom, d.etat === "ok" ? "" : ` (${d.etat})`))))));
    if (!data.groupes.length) note($("sys-devices"), "Aucun périphérique lu (Windows n'a pas répondu à temps).");
  } catch (error) {
    note($("sys-devices"), `Erreur : ${error.message}`, "warn");
  }
}

// ---------- fiche système (comme Paramètres › À propos) ----------
function renderSystem(info) {
  const r = info.resume || {};
  const tile = (icon, label, value, sub) => el("div", { class: "sys-tile" }, el("span", { class: `ico ${icon}`, "aria-hidden": "true" }),
    el("span", { class: "muted" }, label), el("b", {}, value), el("small", { class: "muted" }, sub || ""));
  $("sys-tiles").replaceChildren(
    tile("ram", "RAM installée", `${num(r.memoire_go)} Go`, r.memoire_mhz ? `Vitesse : ${num(r.memoire_mhz)} MHz` : ""),
    tile("cpu", "Processeur", r.processeur ? r.processeur.replace(/\(R\)|\(TM\)|CPU|@.*$/g, "").replace(/\s+/g, " ").trim() : "—",
      r.processeur_ghz ? `${num(r.processeur_ghz, 2)} GHz` : ""),
    tile("gpu", "Carte graphique", r.vram_go ? `${num(r.vram_go)} Go` : "—", r.nb_gpus > 1 ? "Plusieurs GPU installés" : ""),
    tile("disk", "Stockage", goTo(r.stockage_go || 0), `${goTo(r.stockage_utilise_go || 0)} utilisés sur ${goTo(r.stockage_go || 0)}`));
  $("sys-name").textContent = info.nom || "Ce PC";
  const os = info.os || {}, board = info.carte_mere || {}, bios = info.bios || {};
  const specs = [
    ["Nom de l'appareil", info.nom], ["Processeur", r.processeur],
    ["Mémoire RAM installée", `${num(r.memoire_go)} Go${r.memoire_mhz ? ` (${num(r.memoire_mhz)} MHz)` : ""}`],
    ["Barrettes", (info.memoire || []).map((m) => `${m.emplacement || "?"} : ${m.taille_go} Go ${m.reference || ""}`.trim()).join(" · ")],
    ["Cartes graphiques", (info.cartes_graphiques || []).map((g) => g.nom).join(" · ")],
    ["Stockage", (info.disques || []).map((d) => `${d.nom} (${goTo(d.taille_go)}, ${d.bus})`).join(" · ")],
    ["Carte mère", [board.fabricant, board.produit].filter(Boolean).join(" ")],
    ["BIOS", bios.version ? `${bios.version} (${bios.date})` : ""],
    ["Type du système", [os.architecture, info.type_systeme].filter(Boolean).join(" · ")],
    ["Édition", os.nom], ["Version", os.version ? `${os.version} (build ${os.build})` : ""],
    ["Installé le", os.installe ? new Date(os.installe).toLocaleDateString("fr-FR") : ""],
  ].filter(([, v]) => v);
  $("sys-specs").replaceChildren(...specs.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  $("sys-copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText(specs.map(([k, v]) => `${k}\t${v}`).join("\n"));
      $("sys-copy").textContent = "Copié";
    } catch { $("sys-copy").textContent = "Copie refusée"; }
    setTimeout(() => { $("sys-copy").textContent = "Copier"; }, 1500);
  };
  const boardName = [board.fabricant && board.fabricant.replace(/ASUSTeK.*/i, "ASUS"), board.produit].filter(Boolean).join(" ");
  $("board-name").textContent = boardName || "Carte mère";
  $("board-line").textContent = bios.version ? `BIOS ${bios.version} · ${bios.date}` : "";
}

async function loadInfo(refresh = false) {
  if (sys.info && !refresh) return sys.info;
  try {
    sys.info = await api(`/system/info${refresh ? "?refresh=true" : ""}`);
    renderDrives(sys.info);
    renderSystem(sys.info);
  } catch (error) {
    note($("sys-drives"), `Erreur : ${error.message}`, "warn");
  }
  return sys.info;
}

// ---------- carte mère : moniteur façon Armoury Crate, ventilateurs ----------
const GPU_HOT = 83, CPU_HOT = 90;
function sensorRows(sensors, live) {
  const lhm = sensors.lhm || {}, gpus = sensors.gpus || [];
  const pick = (list, re, n = 6) => (list || []).filter((s) => re.test(`${s.materiel} ${s.nom}`)).slice(0, n)
    .map((s) => [`${s.nom}`, s.valeur, s.materiel]);
  const rows = {
    "Fréquence": [["Processeur", live && live.cpu.frequence_mhz ? `${num(live.cpu.frequence_mhz)} MHz` : "—", ""],
      ...gpus.map((g) => [`GPU ${g.index}`, g.frequence_gpu_mhz ? `${num(g.frequence_gpu_mhz)} MHz` : "—", g.nom]),
      ...pick(lhm.frequences, /bus|dram|memory/i, 2)],
    "Température": [...pick(lhm.temperatures, /cpu|package|core|motherboard|vrm|chipset|pch|t_sensor|water/i, 6),
      ...gpus.map((g) => [`GPU ${g.index}`, g.temperature_c === null ? "—" : `${g.temperature_c} °C`, g.nom])],
    "Utilisation": [["Processeur", live ? `${num(live.cpu.utilisation_pct)} %` : "—", ""],
      ["Mémoire", live ? `${num(live.memoire.pct)} %` : "—", ""],
      ...gpus.map((g) => [`GPU ${g.index}`, `${num(g.utilisation_pct)} %`, g.nom])],
    "Ventilateur": [...(lhm.ventilateurs || []).slice(0, 10).map((s) => [s.nom, s.valeur, s.materiel]),
      ...gpus.map((g) => [`GPU ${g.index}`, g.ventilateur_pct === null ? "—" : `${g.ventilateur_pct} %`, g.nom])],
    "Tension": pick(lhm.tensions, /vcore|cpu|dram|\+12|\+5|3\.3|vccsa|vccio/i, 8),
  };
  if (!rows["Tension"].length) rows["Tension"] = [["Tensions", "LibreHardwareMonitor requis", ""]];
  return rows;
}

function thermalAlerts(sensors) {
  const alerts = [];
  for (const g of sensors.gpus || []) {
    if ((g.temperature_c || 0) >= GPU_HOT) alerts.push(`GPU ${g.index} à ${g.temperature_c} °C : vérifie sa courbe de ventilation (GPU Tweak III) et le flux d'air du boîtier.`);
  }
  for (const s of (sensors.lhm || {}).temperatures || []) {
    if (/cpu package|core max|tctl/i.test(s.nom) && (s.nombre || 0) >= CPU_HOT) alerts.push(`Processeur à ${s.valeur} : la pompe ou les ventilateurs du radiateur sont peut-être trop lents.`);
  }
  for (const f of ((sensors.lhm || {}).pompe || [])) {
    if ((f.nombre || 0) < 600) alerts.push(`Pompe ${f.nom} à ${f.valeur} : une pompe d'AIO doit tourner en continu (vérifie qu'elle est réglée à 100 % ou en mode DC/PWM fixe).`);
  }
  return alerts;
}

function renderBoard() {
  const sensors = sys.sensors;
  if (!sensors) return;
  const rows = sensorRows(sensors, sys.live);
  $("board-groups").replaceChildren(...Object.entries(rows).map(([title, items]) => el("div", { class: "board-card" },
    el("h3", {}, title), el("dl", {}, ...items.flatMap(([k, v, sub]) => [el("dt", { title: sub || "" }, k), el("dd", {}, v)])))));
  const lhm = sensors.lhm || {};
  const alerts = thermalAlerts(sensors);
  const nodes = alerts.map((a) => el("p", { class: "warn" }, `⚠ ${a}`));
  if (!lhm.disponible) {
    nodes.push(el("p", { class: "muted" }, "Capteurs de la carte mère (tensions, sondes VRM et chipset, vitesse des "
      + "ventilateurs et de la pompe) : Windows ne les donne pas sans pilote. Installe LibreHardwareMonitor (logiciel libre, "
      + "github.com/LibreHardwareMonitor), lance-le en administrateur puis active Options › Remote Web Server (port 8085) : "
      + "le Hub le lira sur 127.0.0.1. Armoury Crate n'a pas d'interface publique que le Hub pourrait lire."));
  } else {
    nodes.push(el("p", { class: "muted" }, `${(lhm.ventilateurs_actifs || []).length} ventilateur(s) en rotation détecté(s)`
      + `${(lhm.pompe || []).length ? `, dont la pompe : ${lhm.pompe.map((p) => `${p.nom} ${p.valeur}`).join(", ")}` : " ; aucune embase nommée pompe (W_PUMP+, AIO_PUMP)"}.`));
  }
  $("board-note").replaceChildren(...nodes);
  renderFans(sensors);
}

function curveSvg(curve) {
  const W = 300, H = 160, P = 28;
  const x = (t) => P + (t / 100) * (W - P - 8), y = (d) => H - P - (d / 100) * (H - P - 8);
  const pts = [[0, curve.bas[1]], curve.bas, curve.milieu, curve.haut, [100, 100]];
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "curve");
  const add = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text) n.textContent = text;
    svg.append(n);
  };
  for (const t of [0, 25, 50, 75, 100]) {
    add("line", { x1: x(t), x2: x(t), y1: y(0), y2: y(100), class: "grid" });
    add("text", { x: x(t), y: H - 8, "text-anchor": "middle" }, `${t}°`);
    add("line", { x1: x(0), x2: x(100), y1: y(t), y2: y(t), class: "grid" });
    add("text", { x: 4, y: y(t) + 4 }, `${t}%`);
  }
  add("polyline", { points: pts.map(([t, d]) => `${x(t)},${y(d)}`).join(" "), class: "line" });
  for (const [t, d] of [curve.bas, curve.milieu, curve.haut]) add("circle", { cx: x(t), cy: y(d), r: 4, class: "dot" });
  return svg;
}

function renderFans(sensors) {
  const lhm = sensors.lhm || {};
  $("fans").replaceChildren(...(lhm.disponible && (lhm.ventilateurs || []).length
    ? (lhm.ventilateurs || []).map((f) => el("div", { class: `fan ${(f.nombre || 0) > 0 ? "on" : ""}` },
      el("span", { class: "fan-ico", "aria-hidden": "true" }), el("b", {}, f.nom), el("span", {}, f.valeur),
      el("small", { class: "muted" }, /pump|pompe|aio/i.test(f.nom) ? "pompe" : f.materiel)))
    : [el("p", { class: "muted" }, "Vitesses des embases : LibreHardwareMonitor requis (voir plus haut).")]));
  const bios = sensors.ventilateurs_bios;
  if (!bios) {
    note($("fan-curves"), "Courbes du BIOS pas encore lues.");
    return;
  }
  if (!bios.ok) {
    note($("fan-curves"), `Lecture du ${new Date(bios.date).toLocaleString("fr-FR")} : échec (${bios.erreur || "raison inconnue"}).`, "warn");
    return;
  }
  const fans = bios.ventilateurs || [];
  $("fan-curves").replaceChildren(
    el("p", { class: "muted" }, `Lu le ${new Date(bios.date).toLocaleString("fr-FR")} : ${fans.length} embase(s) déclarée(s) par le BIOS.`),
    ...fans.map((f) => el("div", { class: "fan-curve" },
      el("b", {}, `Embase n° ${f.type}`), el("span", { class: "muted" }, ` · mode ${f.mode || "?"} · profil ${f.profil || "?"}`
        + (f.seuil_bas !== undefined && f.seuil_bas !== null ? ` · vitesse plancher ${f.seuil_bas} %` : "")),
      f.courbe ? curveSvg(f.courbe) : el("p", { class: "muted" }, `Courbe illisible (${f.erreur_courbe ?? "?"}).`))),
    el("p", { class: "muted" }, "Modifier une courbe : en cours. Le Hub n'écrira dans le BIOS qu'après une lecture réussie, "
      + "avec une sauvegarde des réglages, des planchers de sécurité (pompe jamais sous 60 %, ventilateurs jamais à l'arrêt "
      + "au-delà de 60 °C) et ton clic de confirmation. En attendant : Armoury Crate › Fan Xpert."));
}

async function readFans(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await post("/system/fans/read");
    note($("fan-curves"), "Windows demande l'autorisation (fenêtre du contrôle de compte) ; la lecture prend quelques secondes…");
    for (let i = 0; i < 12; i++) {
      await new Promise((resolve) => setTimeout(resolve, 2500));
      sys.sensors = await api("/system/sensors");
      if (sys.sensors.ventilateurs_bios && Date.now() - new Date(sys.sensors.ventilateurs_bios.date).getTime() < 60000) break;
    }
    renderBoard();
  } catch (error) {
    note($("fan-curves"), `Erreur : ${error.message}`, "warn");
  } finally {
    button.disabled = false;
  }
}

// ---------- Inoue : optimisation ----------
async function loadOptimisation() {
  const button = $("opt-refresh");
  button.disabled = true;
  try {
    const [data, live] = await Promise.all([api("/system/processes"), api("/system/live")]);
    sys.live = live;
    const plans = data.alimentation || [];
    $("power-plan").replaceChildren(...plans.map((p) => el("option", { value: p.guid, ...(p.actif ? { selected: "" } : {}) },
      `${p.nom}${p.actif ? " (actif)" : ""}`)));
    $("opt-procs").replaceChildren(...data.processus.map((p) => {
      const cell = el("td", {});
      if (!p.protege) {
        const stop = el("button", { type: "button", class: "ghost danger small" }, "Fermer");
        stop.addEventListener("click", async () => {
          if (!confirm(`Fermer ${p.nom} (processus ${p.pid}) ? Le travail non enregistré dans ce programme sera perdu.`)) return;
          stop.disabled = true;
          try {
            const result = await post("/system/process/stop", { pid: p.pid, nom: p.nom });
            cell.replaceChildren(el("span", { class: result.ferme ? "good" : "warn" }, result.detail));
          } catch (error) {
            cell.replaceChildren(el("span", { class: "warn" }, error.message));
          }
        });
        cell.append(stop);
      } else cell.append(el("span", { class: "muted" }, "protégé"));
      return el("tr", {}, el("td", {}, p.nom), el("td", {}, `${num(p.cpu_pct, 1)} %`), el("td", {}, `${num(p.memoire_mo)} Mo`), cell);
    }));
    const advice = [];
    if (live.memoire.pct >= 85) advice.push(`Mémoire à ${num(live.memoire.pct)} % : ferme un programme gourmand ou décharge un modèle (Vue d'ensemble).`);
    if (live.cpu.utilisation_pct >= 85) advice.push(`Processeur à ${num(live.cpu.utilisation_pct)} % : un programme de la liste le monopolise.`);
    for (const g of live.gpus || []) {
      if ((g.temperature_c || 0) >= GPU_HOT) advice.push(`GPU ${g.index} chaud (${g.temperature_c} °C) : courbe de ventilation plus agressive dans GPU Tweak III.`);
      if (g.memoire_totale_go && g.memoire_utilisee_go / g.memoire_totale_go > 0.9) advice.push(`VRAM du GPU ${g.index} presque pleine : décharge un modèle avant de jouer.`);
    }
    const active = plans.find((p) => p.actif);
    if (active && /économie|economie|saver/i.test(active.nom)) advice.push("Mode « Économie d'énergie » actif : le processeur est bridé ; « Performances élevées » pour jouer ou calculer.");
    if (!advice.length) advice.push("Rien d'anormal : le PC a de la marge.");
    $("opt-advice").replaceChildren(...advice.map((a) => el("p", {}, a)));
  } catch (error) {
    note($("opt-advice"), `Erreur : ${error.message}`, "warn");
  } finally {
    button.disabled = false;
  }
}

async function applyPower(event) {
  const guid = $("power-plan").value, button = event.currentTarget;
  if (!guid) return;
  button.disabled = true;
  try {
    await post("/system/power", { guid });
    await loadOptimisation();
  } catch (error) {
    note($("opt-advice"), `Erreur : ${error.message}`, "warn");
  } finally {
    button.disabled = false;
  }
}

// ---------- outils ASUS ----------
async function loadTools() {
  try {
    const tools = await api("/system/tools");
    $("sys-tools").replaceChildren(...tools.map((t) => el("div", { class: `tool ${t.installe ? "" : "absent"}` },
      el("b", {}, t.nom), el("span", { class: "muted" }, t.role),
      el("small", { class: t.en_cours ? "good" : "muted" }, t.installe ? (t.en_cours ? "ouvert" : "installé") : "non installé"),
      t.installe ? el("button", { type: "button", class: "ghost small", "data-tool": t.id }, "Ouvrir") : "")));
  } catch (error) {
    note($("sys-tools"), `Erreur : ${error.message}`, "warn");
  }
}

// ---------- cycle : seul le sous-onglet visible est mesuré ----------
async function tick() {
  clearTimeout(sys.timer);
  if (currentTab() !== "accueil" || document.hidden) return;
  const label = currentSubtab("accueil");
  try {
    if (label === "Performance") {
      sys.live = await api("/system/live", { timeoutMs: 15000 });
      renderPerf();
    } else if (label === "Carte mère") {
      [sys.live, sys.sensors] = await Promise.all([api("/system/live", { timeoutMs: 15000 }), api("/system/sensors", { timeoutMs: 15000 })]);
      renderBoard();
    }
  } catch { /* le Hub redémarre peut-être : on réessaie au prochain tour */ }
  if (SYS_POLL[label]) sys.timer = setTimeout(tick, SYS_POLL[label]);
}

function onSubtab(label) {
  if (currentTab() !== "accueil") return;
  if (["Performance", "Stockage et périphériques", "Système", "Carte mère"].includes(label)) loadInfo();
  if (label === "Stockage et périphériques" && !sys.loaded.devices) { sys.loaded.devices = true; loadDevices(); }
  if (label === "Optimisation (Inoue)" && !sys.loaded.opt) { sys.loaded.opt = true; loadOptimisation(); }
  if (label === "Outils ASUS") loadTools();
  tick();
}

document.addEventListener("subtab", (event) => { if (event.detail.panel === "accueil") onSubtab(event.detail.label); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) onSubtab(currentSubtab("accueil")); });
window.addEventListener("hashchange", () => onSubtab(currentSubtab("accueil")));
for (const tab of document.querySelectorAll("#tabs button")) tab.addEventListener("click", () => setTimeout(() => onSubtab(currentSubtab("accueil")), 0));
$("fans-read").addEventListener("click", readFans);
$("opt-refresh").addEventListener("click", loadOptimisation);
$("power-apply").addEventListener("click", applyPower);
onSubtab(currentSubtab("accueil"));
