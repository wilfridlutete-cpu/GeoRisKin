/* GeoRisKin – carte web (MapLibre GL JS). Les données viennent de l'API Django :
   /api/v1/couches/ (catalogue raster + légendes), /api/v1/valeurs/ (valeurs au point),
   et les points d'accès GeoJSON (communes, bassins, réseau, ravines). */
"use strict";

const API = "/api/v1";
const VECTEURS = {
  communes: { url: `${API}/unites-administratives/?niveau=commune&simplifier=30&limit=100`, couleur: "#222", largeur: 1.2 },
  bassins: { url: `${API}/bassins/?niveau=bassin&simplifier=60&limit=500`, couleur: "#1d4ed8", largeur: 1.6 },
  sous_bassins: { url: `${API}/bassins/?niveau=sous_bassin&simplifier=40&limit=5000`, couleur: "#60a5fa", largeur: 0.7 },
  reseau: { url: `${API}/reseau/?ordre_strahler__gte=3&simplifier=20&limit=10000`, couleur: "#0369a1", largeur: 1.2, ligne: true },
  ravines: { url: `${API}/observations-ravines/?limit=1000`, couleur: "#06b6d4", largeur: 1.5, remplir: "#06b6d4" },
};
let catalogue = [], active = null;
const fmt = (v, d = 3) => (v === null || v === undefined || Number.isNaN(v)) ? "—" : Number(v).toLocaleString("fr-FR", { maximumSignificantDigits: d });

const map = new maplibregl.Map({
  container: "carte",
  center: [15.55, -4.55], zoom: 9, maxZoom: 16, minZoom: 7,
  style: {
    version: 8,
    sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
      attribution: "© contributeurs OpenStreetMap" } },
    layers: [{ id: "fond-blanc", type: "background", paint: { "background-color": "#f2f0ea" } },
             { id: "osm", type: "raster", source: "osm", paint: { "raster-opacity": 0.55 } }],
  },
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }
function featureCollection(d) { return d.results && d.results.features ? d.results : d; }

map.on("load", async () => {
  const cat = await getJSON(`${API}/couches/`);
  catalogue = cat.couches;
  for (const c of catalogue) {
    const src = { type: "raster", tiles: [c.tuiles], tileSize: 256, minzoom: 8, maxzoom: 13 };
    if (c.id === "ombrage") src.attribution = "MNT SRTM (NASA/NGA, OSFAC), Copernicus GLO-30 · ESA WorldCover · SoilGrids (ISRIC) · CHIRPS (UCSB)";
    map.addSource(`r-${c.id}`, src);
    map.addLayer({ id: `r-${c.id}`, type: "raster", source: `r-${c.id}`,
      layout: { visibility: c.id === "ombrage" ? "visible" : "none" },
      paint: { "raster-opacity": c.id === "ombrage" ? 0.45 : (c.opacite ?? 0.8), "raster-resampling": c.type === "categoriel" ? "nearest" : "linear" } });
  }
  if (cat.relief3d) map.addSource("mnt", { type: "raster-dem", tiles: [cat.relief3d], tileSize: 256, encoding: "terrarium", maxzoom: 12 });
  construireListe();
  choisirCouche("perte");
  // Chargement en parallèle ; les couches lourdes (sous-bassins) seulement à la demande.
  await Promise.all(Object.entries(VECTEURS)
    .filter(([id]) => document.querySelector(`[data-vec=${id}]`).checked)
    .map(([id, v]) => ajouterVecteur(id, v)));
});

function construireListe() {
  const box = document.getElementById("liste-couches");
  let groupe = null;
  for (const c of catalogue.filter(c => c.id !== "ombrage")) {
    if (c.groupe !== groupe) { groupe = c.groupe; box.insertAdjacentHTML("beforeend", `<div class="groupe">${groupe}</div>`); }
    box.insertAdjacentHTML("beforeend",
      `<label class="ligne"><input type="radio" name="couche" value="${c.id}"> ${c.titre}</label>`);
  }
  box.insertAdjacentHTML("beforeend", `<label class="ligne"><input type="radio" name="couche" value=""> Aucune</label>`);
  box.addEventListener("change", e => choisirCouche(e.target.value));
}

function choisirCouche(id) {
  for (const c of catalogue) if (c.id !== "ombrage") map.setLayoutProperty(`r-${c.id}`, "visibility", c.id === id ? "visible" : "none");
  active = catalogue.find(c => c.id === id) || null;
  const radio = document.querySelector(`input[name=couche][value="${id}"]`); if (radio) radio.checked = true;
  if (active) document.getElementById("opacite").value = active.opacite ?? 0.8;
  afficherLegende();
}

function afficherLegende() {
  const el = document.getElementById("legende");
  if (!active) { el.innerHTML = ""; return; }
  const estim = /ESTIM|hypoth|non calibr|non valid/i.test(active.statut) ? "estim" : "";
  let corps;
  if (active.type === "categoriel") {
    corps = active.legende.map(l => `<div class="classe"><i style="background:${l.couleur}"></i>${l.valeur}</div>`).join("");
  } else {
    const grad = active.legende.map((l, i) => `${l.couleur} ${(100 * i / (active.legende.length - 1)).toFixed(0)}%`).join(",");
    const pts = [active.legende[0], active.legende[3], active.legende[active.legende.length - 1]];
    corps = `<div class="barre" style="background:linear-gradient(90deg,${grad})"></div>
      <div class="graduations">${pts.map(p => `<span>${fmt(p.valeur)}</span>`).join("")}</div>
      <div class="source">Unité : ${active.unite || "—"} · échelle ${active.echelle === "log" ? "logarithmique" : "linéaire"} · résolution 30 m</div>`;
  }
  el.innerHTML = `<h2>Légende</h2><div><b>${active.titre}</b> <span class="statut ${estim}">${active.statut}</span></div>
    ${corps}<div class="source">Source : ${active.source}</div>`;
}

async function ajouterVecteur(id, v) {
  let data;
  try { data = featureCollection(await getJSON(v.url)); } catch (e) { console.warn(e); return; }
  map.addSource(`v-${id}`, { type: "geojson", data });
  const vis = document.querySelector(`[data-vec=${id}]`).checked ? "visible" : "none";
  if (!v.ligne) map.addLayer({ id: `v-${id}-fill`, type: "fill", source: `v-${id}`, layout: { visibility: vis },
    paint: { "fill-color": v.remplir || "#000", "fill-opacity": v.remplir ? 0.35 : 0 } });
  map.addLayer({ id: `v-${id}`, type: "line", source: `v-${id}`, layout: { visibility: vis },
    paint: { "line-color": v.couleur, "line-width": v.largeur } });
  if (id === "communes") etiquettesCommunes(data, vis);
}

// Étiquettes des communes en HTML (aucune police distante requise : fonctionne hors ligne).
const etiquettes = [];
function centreAnneau(r) {
  let a = 0, x = 0, y = 0;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
    const f = r[j][0] * r[i][1] - r[i][0] * r[j][1]; a += f; x += (r[j][0] + r[i][0]) * f; y += (r[j][1] + r[i][1]) * f;
  }
  return a ? { aire: Math.abs(a / 2), pt: [x / (3 * a), y / (3 * a)] } : { aire: 0, pt: r[0] };
}
function etiquettesCommunes(data, vis) {
  for (const f of data.features) {
    const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
    const best = polys.map(p => centreAnneau(p[0])).sort((a, b) => b.aire - a.aire)[0];
    const el = document.createElement("div"); el.className = "etiquette"; el.textContent = f.properties.nom;
    el.style.display = vis === "visible" ? "" : "none";
    etiquettes.push(new maplibregl.Marker({ element: el }).setLngLat(best.pt).addTo(map));
  }
}

document.querySelectorAll("[data-vec]").forEach(cb => cb.addEventListener("change", async () => {
  if (cb.checked && !map.getSource(`v-${cb.dataset.vec}`)) { await ajouterVecteur(cb.dataset.vec, VECTEURS[cb.dataset.vec]); return; }
  if (cb.dataset.vec === "communes") etiquettes.forEach(m => { m.getElement().style.display = cb.checked ? "" : "none"; });
  for (const suffix of ["", "-fill"]) {
    const lid = `v-${cb.dataset.vec}${suffix}`;
    if (map.getLayer(lid)) map.setLayoutProperty(lid, "visibility", cb.checked ? "visible" : "none");
  }
}));
document.getElementById("opacite").addEventListener("input", e => { if (active) map.setPaintProperty(`r-${active.id}`, "raster-opacity", +e.target.value); });
document.getElementById("ombrage").addEventListener("change", e => map.setLayoutProperty("r-ombrage", "visibility", e.target.checked ? "visible" : "none"));
document.getElementById("fond").addEventListener("change", e => map.setLayoutProperty("osm", "visibility", e.target.checked ? "visible" : "none"));
document.getElementById("relief3d").addEventListener("change", e => {
  if (!map.getSource("mnt")) { e.target.checked = false; return; }
  if (e.target.checked) { map.setTerrain({ source: "mnt", exaggeration: 3 }); map.easeTo({ pitch: 60 }); }
  else { map.setTerrain(null); map.easeTo({ pitch: 0 }); }
});

const STATS = [
  ["a_moy_med_t_ha_an", "Perte de sol moyenne (médiane)", "t/ha/an"],
  ["a_moy_p10_t_ha_an", "  hypothèse basse (P10)", "t/ha/an"],
  ["a_moy_p90_t_ha_an", "  hypothèse haute (P90)", "t/ha/an"],
  ["perte_med_t_an", "Perte totale (médiane)", "t/an"],
  ["part_domaine_rusle_pct", "Surface couverte par RUSLE", "%"],
  ["ls_moyen", "LS moyen", ""], ["k_moyen", "K moyen", "t·ha·h/(ha·MJ·mm)"],
  ["pct_bati", "Bâti", "%"], ["pct_arbres", "Arbres", "%"], ["pct_herbacees", "Herbacées", "%"], ["pct_cultures", "Cultures (maraîchage)", "%"],
  ["geol_unite_dominante", "Géologie dominante (1963)", ""],
];
function tableStats(st) {
  const lignes = STATS.filter(([k]) => st && st[k] !== undefined)
    .map(([k, lab, u]) => `<tr><td>${lab}</td><td>${typeof st[k] === "string" ? st[k] : fmt(st[k])} ${u}</td></tr>`).join("");
  const alerte = st && st.part_domaine_rusle_pct !== undefined && st.part_domaine_rusle_pct < 20
    ? `<p class="alerte">Moins de 20 % de la surface est dans le domaine de RUSLE (bâti, eau, écoulement concentré exclus) : la moyenne n'est pas représentative.</p>` : "";
  return `<table>${lignes}</table>${alerte}`;
}

map.on("click", async (e) => {
  const { lng, lat } = e.lngLat;
  const el = document.getElementById("infos");
  el.innerHTML = `<h2>Informations</h2><p class="aide">Point ${lat.toFixed(5)}°, ${lng.toFixed(5)}° – chargement…</p>`;
  const layers = ["v-communes-fill", "v-bassins-fill", "v-sous_bassins-fill", "v-ravines-fill"].filter(l => map.getLayer(l));
  const feats = map.queryRenderedFeatures(e.point, { layers });
  let html = `<h2>Informations</h2><p class="aide">Point ${lat.toFixed(5)}°, ${lng.toFixed(5)}°</p>`;
  if (map.getLayer("v-reseau")) {
    const bb = [[e.point.x - 6, e.point.y - 6], [e.point.x + 6, e.point.y + 6]];
    const riv = map.queryRenderedFeatures(bb, { layers: ["v-reseau"] })[0];
    if (riv) html += `<p><b>Cours d'eau :</b> ${riv.properties.nom || "sans nom"} (ordre de Strahler ${riv.properties.ordre_strahler}, ${fmt(riv.properties.aire_drainee_km2)} km² drainés)</p>`;
  }
  try {
    const d = await getJSON(`${API}/valeurs/?lon=${lng}&lat=${lat}`);
    html += `<table>${d.valeurs.map(v => `<tr><td>${v.titre}</td><td>${v.valeur === null ? "<span title='hors domaine ou sans donnée'>—</span>" : (typeof v.valeur === "string" ? v.valeur : fmt(v.valeur))} ${v.valeur === null ? "" : v.unite}</td></tr>`).join("")}</table>
      <p class="aide">« — » : hors domaine du modèle (bâti dense, eau, écoulement concentré) ou sans donnée.</p>`;
  } catch (err) { html += `<p class="alerte">Valeurs indisponibles (${err.message}).</p>`; }
  for (const f of feats) {
    const p = f.properties; const st = typeof p.statistiques === "string" ? JSON.parse(p.statistiques) : p.statistiques;
    const btn = (type, lib) => `<button class="secondaire" data-zone-type="${type}" data-zone-id="${f.id}" data-zone-lib="${lib.replace(/"/g, "")}">Utiliser comme zone du scénario</button>`;
    if (f.layer.id === "v-communes-fill") html += `<h2>Commune : ${p.nom}</h2>${btn("unite", "Commune " + p.nom)}${tableStats(st)}`;
    if (f.layer.id === "v-bassins-fill") { const lib = `Bassin ${p.code}${p.nom ? " – " + p.nom : ""}`; html += `<h2>${lib}</h2><p class="aide">${fmt(p.superficie_km2)} km² · exutoire : ${p.exutoire_type}</p>${btn("bassin", lib)}${tableStats(st)}`; }
    if (f.layer.id === "v-sous_bassins-fill") { const lib = `Sous-bassin ${p.code}${p.nom ? " – " + p.nom : ""}`; html += `<h2>${lib}</h2><p class="aide">${fmt(p.superficie_km2)} km²</p>${btn("bassin", lib)}${tableStats(st)}`; }
    if (f.layer.id === "v-ravines-fill") html += `<h2>Ravine (inventaire indicatif)</h2><p class="aide">${p.ravine_code || ""} ${p.campagne_nom ? "· " + p.campagne_nom : ""}</p>`;
  }
  el.innerHTML = html;
});


/* ---------------- Scénarios ---------------- */
let zoneScenario = null, pratiques = {};
const $ = (id) => document.getElementById(id);
function csrf() { const el = document.querySelector("[name=csrfmiddlewaretoken]"); return el ? el.value : ""; }

document.getElementById("infos").addEventListener("click", (e) => {
  const b = e.target.closest("[data-zone-type]"); if (!b) return;
  zoneScenario = { type: b.dataset.zoneType, id: +b.dataset.zoneId, lib: b.dataset.zoneLib };
  $("sc-zone").textContent = zoneScenario.lib;
  $("sc-lancer").disabled = false;
  $("scenario").scrollIntoView({ behavior: "smooth" });
});
for (const k of ["reb", "urb"]) $(`sc-${k}`).addEventListener("input", e => { $(`sc-${k}-v`).textContent = `${e.target.value} %`; });

getJSON(`${API}/pratiques/`).then(d => {
  pratiques = d.pratiques;
  for (const [id, p] of Object.entries(pratiques)) $("sc-pratique").insertAdjacentHTML("beforeend", `<option value="${id}">${p.nom}</option>`);
});
$("sc-pratique").addEventListener("change", e => {
  const p = pratiques[e.target.value];
  $("sc-pratique-info").innerHTML = !p ? "" : `P = ${p.par_pente ? "selon la pente (" + p.par_pente.map(x => x[1]).join(" à ") + ")" : `${p.central} (fourchette ${p.bas}–${p.haut})`}
    · <b>${p.statut}</b><br>${p.sources.join("<br>")}`;
});
const classesCochees = (k) => [...document.querySelectorAll(`[data-pour=${k}] input:checked`)].map(i => +i.value);

$("sc-lancer").addEventListener("click", async () => {
  if (!zoneScenario) return;
  const params = { periode_pluie: $("sc-pluie").value };
  if (+$("sc-reb").value > 0) params.reboisement = { part: $("sc-reb").value / 100, classes: classesCochees("reb") };
  if (+$("sc-urb").value > 0) params.urbanisation = { part: $("sc-urb").value / 100, classes: classesCochees("urb") };
  if ($("sc-pratique").value) params.pratique = { id: $("sc-pratique").value, cible: $("sc-cible").value, pente_min_deg: +$("sc-pente").value };
  const body = { nom: `Scénario ${zoneScenario.lib}`, parametres: params };
  body[zoneScenario.type === "bassin" ? "bassin_id" : "unite_id"] = zoneScenario.id;
  $("sc-lancer").disabled = true; $("sc-resultat").innerHTML = `<p class="aide">Calcul en cours…</p>`;
  try {
    const r = await fetch(`${API}/scenarios/`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(body) });
    const d = await r.json();
    if (!r.ok) throw new Error(Object.values(d).flat().join(" ; "));
    if (d.statut !== "termine") throw new Error(d.erreur.split("\n")[0]);
    afficherResultat(d);
  } catch (err) { $("sc-resultat").innerHTML = `<p class="alerte">${err.message}</p>`; }
  $("sc-lancer").disabled = false;
});

function afficherResultat(d) {
  const r = d.resultats, v = r.variation_pct;
  const cls = v.mediane < 0 ? "baisse" : "hausse";
  const t = (q) => `${fmt(q.mediane)} t/an <span class="aide">(${fmt(q.p10)} – ${fmt(q.p90)})</span>`;
  let h = `<p class="resultat-cle ${cls}">Variation : <b>${v.mediane > 0 ? "+" : ""}${fmt(v.mediane, 2)} %</b>
      <span class="aide">(${fmt(v.p10, 2)} à ${fmt(v.p90, 2)} % selon ${r.membres} hypothèses)</span></p>
    <table><tr><td>Perte de sol – référence (1991–2020, P = 1)</td><td>${t(r.perte_reference_t_an)}</td></tr>
    <tr><td>Perte de sol – scénario</td><td>${t(r.perte_scenario_t_an)}</td></tr>
    <tr><td>Surface de la zone</td><td>${fmt(r.zone_ha, 4)} ha</td></tr>
    <tr><td>dont domaine RUSLE (référence → scénario)</td><td>${fmt(r.domaine_rusle_reference_ha, 4)} → ${fmt(r.domaine_rusle_scenario_ha, 4)} ha</td></tr>
    ${r.arbres_ajoutes_ha ? `<tr><td>Arbres ajoutés</td><td>${fmt(r.arbres_ajoutes_ha, 4)} ha</td></tr>` : ""}
    ${r.bati_ajoute_ha ? `<tr><td>Bâti ajouté</td><td>${fmt(r.bati_ajoute_ha, 4)} ha</td></tr>
       <tr><td>Réseau en aval recevant ≥ 1 ha imperméable de plus</td><td>${fmt(r.impermeable.lineaire_aval_km_recevant_plus_de_1ha)} km</td></tr>` : ""}
    </table>`;
  if (r.avertissement) h += `<p class="alerte">${r.avertissement}</p>`;
  if (r.domaine_rusle_reference_ha < 0.2 * r.zone_ha) h += `<p class="alerte">Moins de 20 % de la zone est dans le domaine de RUSLE : le résultat ne concerne qu'une petite partie de la zone.</p>`;
  const L = r.legende_difference;
  h += `<h2>Carte</h2>
    <label class="ligne"><input type="radio" name="sc-carte" value="difference" checked> Différence (scénario − référence)</label>
    <label class="ligne"><input type="radio" name="sc-carte" value="perte_scenario"> Perte de sol du scénario</label>
    <label class="ligne"><input type="radio" name="sc-carte" value="sorti_du_domaine"> Cellules sorties du domaine RUSLE</label>
    <div class="barre" style="background:linear-gradient(90deg,${L.couleurs.join(",")})"></div>
    <div class="graduations"><span>−${L.max} (baisse)</span><span>0</span><span>+${L.max} (hausse) ${L.unite}</span></div>
    <p class="source"><a href="${r.telechargement_geotiff}">Télécharger la différence (GeoTIFF)</a> · ${r.rappel}</p>`;
  $("sc-resultat").innerHTML = h;
  montrerImage(r.images.difference);
  document.querySelectorAll("[name=sc-carte]").forEach(i => i.addEventListener("change", () => montrerImage(r.images[i.value])));
  const c = r.images.difference.coordonnees;
  map.fitBounds([[c[0][0], c[2][1]], [c[1][0], c[0][1]]], { padding: 40 });
}

function montrerImage(img) {
  const src = map.getSource("sc-img");
  if (src) src.updateImage({ url: img.url, coordinates: img.coordonnees });
  else {
    map.addSource("sc-img", { type: "image", url: img.url, coordinates: img.coordonnees });
    const avant = map.getLayer("v-communes-fill") ? "v-communes-fill" : undefined;
    map.addLayer({ id: "sc-img", type: "raster", source: "sc-img", paint: { "raster-opacity": 0.9, "raster-resampling": "nearest" } }, avant);
  }
}
