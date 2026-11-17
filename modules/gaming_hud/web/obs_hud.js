// Overlay OBS d'AetherTwin. Reçoit l'état par SSE et l'affiche.
// Tout texte venant du flux est écrit avec textContent : rien n'est jamais interprété comme du HTML.
"use strict";

const $ = (id) => document.getElementById(id);
const hud = $("hud");

function setText(id, text) {
  $(id).textContent = text == null ? "" : String(text);
}

function show(id, visible) {
  $(id).hidden = !visible;
}

function number(value, digits = 0) {
  return typeof value === "number" && isFinite(value) ? value.toFixed(digits) : null;
}

function gold(copper) {
  if (typeof copper !== "number") return null;
  return Math.floor(copper / 10000).toLocaleString("fr-FR") + " po";
}

function meter(label, ratio, text) {
  const row = document.createElement("div");
  row.className = "meter";
  const name = document.createElement("span");
  name.className = "label";
  name.textContent = label;
  const track = document.createElement("div");
  track.className = "track";
  const fill = document.createElement("div");
  const clamped = Math.max(0, Math.min(1, ratio || 0));
  fill.className = "fill" + (clamped >= 0.9 ? " hot" : clamped >= 0.75 ? " warn" : "");
  fill.style.width = (clamped * 100).toFixed(1) + "%";
  track.appendChild(fill);
  const value = document.createElement("span");
  value.className = "value";
  value.textContent = text;
  row.append(name, track, value);
  return row;
}

function renderGpus(gpus) {
  const list = $("gpu-list");
  list.replaceChildren();
  for (const gpu of gpus) {
    const box = document.createElement("div");
    box.className = "gpu";
    const head = document.createElement("div");
    head.className = "gpu-name";
    const name = document.createElement("span");
    name.textContent = String(gpu.name || "GPU " + gpu.index).replace(/^NVIDIA GeForce /, "");
    const side = document.createElement("span");
    const temp = number(gpu.temp);
    const power = number(gpu.power);
    side.textContent = [temp && temp + " °C", power && power + " W"].filter(Boolean).join(" · ");
    head.append(name, side);
    box.appendChild(head);
    const util = number(gpu.util);
    if (util !== null) box.appendChild(meter("Charge", gpu.util / 100, util + " %"));
    if (typeof gpu.vram_used === "number" && gpu.vram_total) {
      const used = (gpu.vram_used / 1024).toFixed(1);
      const total = (gpu.vram_total / 1024).toFixed(0);
      box.appendChild(meter("VRAM", gpu.vram_used / gpu.vram_total, used + " / " + total + " Go"));
    }
    list.appendChild(box);
  }
  show("gpus", gpus.length > 0);
}

function render(state) {
  hud.classList.remove("waiting", "offline");
  setText("status", state.showcase ? "mode Showcase · 100 % local" : "100 % local");

  const c = state.character;
  show("character", Boolean(c && (c.name || c.level)));
  if (c) {
    setText("char-name", c.name || "");
    setText("char-line", [c.level != null && "Niveau " + c.level, c.class, c.spec].filter(Boolean).join(" · "));
    setText("char-zone", c.zone || "");
    const ilvl = number(c.ilvl, 1);
    setText("char-extra", [ilvl && Number(ilvl) > 0 && "Niveau d'objet " + Number(ilvl), gold(c.money)]
      .filter(Boolean).join(" · "));
  }

  const q = state.quests;
  show("quests", Boolean(q && q.count));
  if (q) {
    setText("quests-title", "Quêtes · " + q.count);
    const items = (q.titles || []).map((title) => {
      const li = document.createElement("li");
      li.textContent = title;
      return li;
    });
    $("quests-list").replaceChildren(...items);
  }

  const f = state.fields;
  show("fields", Boolean(f && Object.keys(f).length));
  if (f) {
    const rows = [];
    for (const [key, value] of Object.entries(f)) {
      const dt = document.createElement("dt");
      dt.textContent = key;
      const dd = document.createElement("dd");
      dd.textContent = Array.isArray(value) ? value.join(", ") : String(value);
      rows.push(dt, dd);
    }
    $("fields-list").replaceChildren(...rows);
  }

  renderGpus(Array.isArray(state.gpus) ? state.gpus : []);
}

function connect() {
  const source = new EventSource("/obs-hud/events");
  source.onmessage = (event) => {
    try {
      render(JSON.parse(event.data));
    } catch (error) {
      setText("status", "données illisibles");
    }
  };
  source.onerror = () => {
    hud.classList.add("offline");
    setText("status", "hub hors ligne — nouvelle tentative…");
  };
}

connect();
