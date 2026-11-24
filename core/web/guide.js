"use strict";
// Guides d'AetherTwin : affiche un README du dépôt (GET /guides/{id}) en HTML construit nœud par nœud (jamais
// innerHTML). Adresse : /static/guide.html?g=<id>#<titre>. Liens externes dans un nouvel onglet ; liens vers un
// autre README du dépôt → son guide.
(() => {
  const $ = (id) => document.getElementById(id);
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v);
    node.append(...children.flat());
    return node;
  }
  let catalog = [];

  // ---------- thème ----------
  try {
    const theme = localStorage.getItem("aether-guide-theme");
    if (theme) document.documentElement.dataset.theme = theme;
  } catch (error) { /* rien */ }
  $("btn-theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("aether-guide-theme", next); } catch (error) { /* rien */ }
  });

  // ---------- liens ----------
  function guideFor(href) {
    const m = href.match(/(?:^|\/)modules\/([a-z][a-z0-9_]*)\/(app\/)?README\.md$/) || href.match(/^\.\.\/([a-z][a-z0-9_]*)\/README\.md$/);
    if (m) return m[2] && m[1] === "gaming_hud" ? "wow_assistant" : m[1];
    if (/^(\.\.\/)*README\.md$/.test(href)) return "aethertwin";
    return null;
  }
  function link(text, href) {
    if (/^https?:\/\//.test(href)) return el("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);
    if (href.startsWith("#")) return el("a", { href }, text);
    const gid = guideFor(href.split("#")[0]);
    if (gid && catalog.some((g) => g.id === gid)) return el("a", { href: `/static/guide.html?g=${gid}` }, text);
    return el("span", { title: href }, text);  // fichier du dépôt sans guide : texte seul
  }

  // ---------- Markdown ----------
  function inline(text) {
    const out = [];
    const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;
    let last = 0;
    for (const m of text.matchAll(pattern)) {
      if (m.index > last) out.push(text.slice(last, m.index));
      const t = m[0];
      if (t.startsWith("`")) out.push(el("code", {}, t.slice(1, -1)));
      else if (t.startsWith("**")) out.push(el("strong", {}, ...inline(t.slice(2, -2))));
      else if (t.startsWith("[")) {
        const lm = t.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
        out.push(link(lm[1], lm[2]));
      } else out.push(el("em", {}, ...inline(t.slice(1, -1))));
      last = m.index + t.length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }
  const slugs = new Set();
  function slug(text) {
    let base = text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "section";
    let s = base;
    for (let i = 2; slugs.has(s); i += 1) s = `${base}-${i}`;
    slugs.add(s);
    return s;
  }
  const cells = (line) => line.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));

  function render(markdown) {
    slugs.clear();
    const lines = markdown.replace(/\r\n/g, "\n").split("\n");
    const nodes = [];
    const toc = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const code = [];
        for (i += 1; i < lines.length && !/^```/.test(lines[i]); i += 1) code.push(lines[i]);
        i += 1;
        nodes.push(el("pre", {}, el("code", {}, code.join("\n"))));
        continue;
      }
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        const level = h[1].length;
        const id = slug(h[2]);
        nodes.push(el(`h${level}`, { id }, ...inline(h[2])));
        if (level === 2 || level === 3) toc.push({ level, id, text: h[2].replace(/[`*]/g, "") });
        i += 1;
        continue;
      }
      if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])) {
        const head = cells(line);
        const rows = [];
        for (i += 2; i < lines.length && /^\s*\|/.test(lines[i]); i += 1) rows.push(cells(lines[i]));
        nodes.push(el("table", {}, el("thead", {}, el("tr", {}, head.map((c) => el("th", {}, ...inline(c))))),
          el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, ...inline(c))))))));
        continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = [];
        for (; i < lines.length && /^>\s?/.test(lines[i]); i += 1) quote.push(lines[i].replace(/^>\s?/, ""));
        nodes.push(el("blockquote", {}, ...render(quote.join("\n")).nodes));
        continue;
      }
      if (/^\s*([-*]|\d+[.)])\s+/.test(line)) {
        const stack = [];
        let top = null;
        for (; i < lines.length; i += 1) {
          const l = lines[i];
          const item = l.match(/^(\s*)([-*]|\d+[.)])\s+(.*)$/);
          if (!item) {
            if (/^\s{2,}\S/.test(l) && stack.length) { stack[stack.length - 1].li.append(" ", ...inline(l.trim())); continue; }
            break;
          }
          const indent = item[1].length;
          while (stack.length && stack[stack.length - 1].indent > indent) stack.pop();
          let level = stack[stack.length - 1];
          if (!level || indent > level.indent) {
            const list = el(/\d/.test(item[2]) ? "ol" : "ul");
            if (level) level.li.append(list); else top = list;
            level = { indent, list, li: null };
            stack.push(level);
          }
          const li = el("li", {}, ...inline(item[3]));
          level.list.append(li);
          level.li = li;
        }
        nodes.push(top);
        continue;
      }
      if (!line.trim()) { i += 1; continue; }
      const para = [];
      for (; i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\s*\||\s*([-*]|\d+[.)])\s)/.test(lines[i]); i += 1) {
        para.push(lines[i].trim());
      }
      if (!para.length) { para.push(line.trim()); i += 1; }
      nodes.push(el("p", {}, ...inline(para.join(" "))));
    }
    return { nodes, toc };
  }

  // ---------- recherche ----------
  function highlight(query) {
    const doc = $("doc");
    doc.querySelectorAll("mark").forEach((m) => m.replaceWith(m.textContent));
    doc.normalize();
    if (query.length < 2) return;
    const lower = query.toLowerCase();
    const walker = document.createTreeWalker(doc, NodeFilter.SHOW_TEXT);
    const hits = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) if (n.nodeValue.toLowerCase().includes(lower)) hits.push(n);
    let first = null;
    for (const node of hits) {
      const text = node.nodeValue;
      const parts = [];
      let pos = 0;
      for (let at = text.toLowerCase().indexOf(lower); at >= 0; at = text.toLowerCase().indexOf(lower, pos)) {
        parts.push(text.slice(pos, at));
        const mark = el("mark", {}, text.slice(at, at + query.length));
        first = first || mark;
        parts.push(mark);
        pos = at + query.length;
      }
      parts.push(text.slice(pos));
      node.replaceWith(...parts);
    }
    if (first) first.scrollIntoView({ block: "center" });
  }
  let searchTimer = 0;
  $("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => highlight($("search").value.trim()), 200); });

  // ---------- chargement ----------
  async function load() {
    const params = new URLSearchParams(location.search);
    const wanted = params.get("g") || "aethertwin";
    try {
      catalog = await (await fetch("/guides")).json();
    } catch (error) { catalog = []; }
    $("guides").replaceChildren(...catalog.map((g) => el("li", {},
      el("a", { href: `/static/guide.html?g=${g.id}`, class: g.id === wanted ? "current" : null }, g.title))));
    const response = await fetch(`/guides/${encodeURIComponent(wanted)}`);
    if (!response.ok) {
      $("doc").replaceChildren(el("h1", {}, "Guide introuvable"), el("p", { class: "muted" }, `Aucun guide « ${wanted} ». Choisis-en un dans la liste.`));
      return;
    }
    const data = await response.json();
    document.title = `${data.title} — Guides AetherTwin`;
    const { nodes, toc } = render(data.markdown);
    $("doc").replaceChildren(...nodes);
    $("toc").replaceChildren(...toc.map((t) => el("li", { class: t.level === 3 ? "sub" : null }, el("a", { href: `#${t.id}` }, t.text))));
    if (location.hash) document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView();
    const q = params.get("q");
    if (q) { $("search").value = q; highlight(q); }
  }
  load();
})();
