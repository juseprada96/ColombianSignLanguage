"use strict";

const DATA_URL = "vocabulary.json";
const ROOT_MARGIN = "300px";

const state = { entries: [], sections: [] };

const el = (tag, props = {}, children = []) => {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of [].concat(children)) {
    if (child != null) node.append(child);
  }
  return node;
};

/** Case-insensitive, accent-insensitive (á→a, ñ→n) normalisation. */
function normalize(value) {
  return String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function slugify(value) {
  return normalize(value).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function buildCard(key, path) {
  const img = el("img", {
    alt: `Seña: ${key}`,
    loading: "lazy",
    decoding: "async",
  });
  img.dataset.src = path;

  const card = el("figure", { className: "card" }, [
    img,
    el("figcaption", { textContent: key }),
  ]);
  img.addEventListener("click", () => openLightbox(key, path));
  return { card, img };
}

function buildSection(name, entries) {
  const id = `sec-${slugify(name)}`;
  const grid = el("div", { className: "grid" });
  const section = el("section", { className: "section", id }, [
    el("h2", { textContent: name }),
    grid,
  ]);

  for (const entry of entries) {
    const { card, img } = buildCard(entry.key, entry.path);
    grid.append(card);
    state.entries.push({
      key: entry.key,
      norm: normalize(entry.key),
      card,
      img,
      section,
    });
  }
  return section;
}

function observeLazyImages() {
  const load = (img) => {
    if (img.dataset.src && !img.src) img.src = img.dataset.src;
  };

  if (!("IntersectionObserver" in window)) {
    state.entries.forEach((e) => load(e.img));
    return;
  }

  const observer = new IntersectionObserver(
    (items, obs) => {
      for (const item of items) {
        if (!item.isIntersecting) continue;
        load(item.target);
        obs.unobserve(item.target);
      }
    },
    { rootMargin: ROOT_MARGIN }
  );

  state.entries.forEach((e) => observer.observe(e.card));
}

/* ---------- search ---------- */
function applyFilter() {
  const query = normalize(document.getElementById("search").value);
  let visible = 0;

  for (const entry of state.entries) {
    const match = !query || entry.norm.includes(query);
    entry.card.hidden = !match;
    if (match) visible += 1;
  }

  for (const section of state.sections) {
    const hasVisible = [...section.querySelectorAll(".card")].some((c) => !c.hidden);
    section.hidden = !hasVisible;
  }

  const total = state.entries.length;
  document.getElementById("count").textContent = query
    ? `${visible} de ${total} resultados`
    : `${total} palabras`;

  document.getElementById("clear").hidden = document.getElementById("search").value === "";
}

/* ---------- lightbox ---------- */
function openLightbox(key, path) {
  let box = document.getElementById("lightbox");
  if (!box) {
    const img = el("img", { alt: `Seña: ${key}` });
    const caption = el("p");
    const close = el("button", { className: "close", textContent: "×", ariaLabel: "Cerrar" });
    box = el("div", { id: "lightbox", className: "lightbox", role: "dialog", ariaModal: "true" }, [
      close,
      img,
      caption,
    ]);
    close.addEventListener("click", () => (box.hidden = true));
    box.addEventListener("click", (ev) => {
      if (ev.target === box) box.hidden = true;
    });
    document.body.append(box);
  }
  box.querySelector("img").src = path;
  box.querySelector("p").textContent = key;
  box.hidden = false;
}

/* ---------- render ---------- */
function render(vocabulary) {
  const content = document.getElementById("content");
  const nav = document.getElementById("nav");
  content.textContent = "";

  const fragment = document.createDocumentFragment();

  for (const [sectionName, words] of Object.entries(vocabulary)) {
    const entries = Object.entries(words).map(([key, path]) => ({ key, path: String(path) }));
    const section = buildSection(sectionName, entries);
    state.sections.push(section);
    fragment.append(section);

    nav.append(el("a", { href: `#${section.id}`, textContent: sectionName }));
  }

  content.append(fragment);
  observeLazyImages();
  applyFilter();
}

async function init() {
  const status = document.getElementById("status");
  const search = document.getElementById("search");
  const clear = document.getElementById("clear");

  search.addEventListener("input", applyFilter);
  clear.addEventListener("click", () => {
    search.value = "";
    search.focus();
    applyFilter();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      const box = document.getElementById("lightbox");
      if (box && !box.hidden) box.hidden = true;
    }
  });

  try {
    const response = await fetch(DATA_URL, { cache: "no-cache" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const vocabulary = await response.json();
    render(vocabulary);
  } catch (error) {
    status.classList.add("error");
    status.textContent =
      "No se pudo cargar vocabulary.json. Asegúrate de servir la página por HTTP (GitHub Pages o un servidor local).";
    console.error(error);
  }
}

document.addEventListener("DOMContentLoaded", init);
