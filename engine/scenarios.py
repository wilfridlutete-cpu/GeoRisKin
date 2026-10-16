"""Scénarios d'aménagement et de pluie pour RUSLE.

Un scénario modifie, dans une zone, (1) l'occupation du sol (reboisement, urbanisation),
(2) les pratiques de conservation (facteur P : haies, bandes enherbées, terrasses, fascines),
(3) la période de pluie (facteur R). La comparaison avec la référence est faite membre à membre
sur l'ensemble d'hypothèses (R × C × LS × P), ce qui donne une fourchette pour chaque résultat.

Points de vigilance (rappelés dans les résultats) :
- urbaniser fait SORTIR des cellules du domaine RUSLE (bâti > 50 %) : la perte de sol « calculée »
  baisse alors mécaniquement alors que le ruissellement augmente ; on rapporte donc séparément la
  surface sortie du domaine et la surface imperméable ajoutée, propagée vers l'aval ;
- P est appliqué à la part cultivée de la cellule (cible « cultures ») ou à toute la cellule.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import product

import numpy as np

from .c_factor import c_from_fractions, class_values
from .rusle import rusle

CODES = {10: "arbres", 20: "arbustes", 30: "herbacees", 40: "cultures", 50: "bati", 60: "sol_nu", 80: "eau", 90: "zones_humides"}


def changer_occupation(fracs: dict[int, np.ndarray], masque: np.ndarray, de: list[int], vers: int, part: float):
    """Transfère la proportion `part` (0–1) des classes `de` vers la classe `vers`, dans le masque."""
    if not 0 <= part <= 1:
        raise ValueError("part doit être comprise entre 0 et 1")
    out = {k: v.copy() for k, v in fracs.items()}
    moved = np.zeros(masque.shape, "float32")
    for k in de:
        if k == vers or k not in out:
            continue
        f = np.where(np.isfinite(out[k]), out[k], 0)
        d = np.where(masque, f * part, 0).astype("float32")
        out[k] = np.where(np.isfinite(out[k]), out[k] - d, out[k])
        moved += d
    base = out[vers]
    out[vers] = np.where(np.isfinite(base), base + moved, np.where(moved > 0, moved, base))
    return out, moved


def valeur_p(pratique: dict, variante: str, pente_deg: np.ndarray) -> np.ndarray:
    """Valeur de P de la pratique (variante bas/central/haut), éventuellement selon la pente."""
    if "par_pente" in pratique:
        pct = np.tan(np.radians(np.clip(pente_deg, 0, 89))) * 100
        v = np.full(pente_deg.shape, pratique["par_pente"][-1][1], "float32")
        for lim, p in reversed(pratique["par_pente"]):
            v = np.where(pct <= lim, p, v)
        inc = pratique.get("incertitude_relative", 0.0)
        f = {"bas": 1 - inc, "central": 1.0, "haut": 1 + inc}[variante]
        return np.clip(v * f, 0, 1).astype("float32")
    return np.full(pente_deg.shape, float(pratique[variante]), "float32")


def facteur_p(pratique: dict | None, variante: str, pente_deg, masque, frac_cultures, cible="cultures",
              pente_min_deg: float = 0.0):
    """P de cellule = 1 − w·(1 − P_pratique), w = part cultivée (cible cultures) ou 1 (toute la cellule)."""
    P = np.ones(masque.shape, "float32")
    if pratique is None:
        return P
    v = valeur_p(pratique, variante, pente_deg)
    w = np.where(np.isfinite(frac_cultures), frac_cultures, 0) if cible == "cultures" else np.ones_like(P)
    ok = masque & (np.nan_to_num(pente_deg) >= pente_min_deg)
    P[ok] = (1 - w[ok] * (1 - v[ok])).astype("float32")
    return P


@dataclass
class Entrees:
    """Facteurs sur une même fenêtre de grille (tableaux 2D alignés)."""
    K: np.ndarray
    LS: dict                      # {"desmet_govers": arr, "moore_burch": arr} (NaN = écoulement concentré)
    R_ref: dict                   # {methode: arr} période de référence
    R_scen: dict                  # {methode: arr} période du scénario
    fracs: dict                   # {code: arr} fractions d'occupation
    pente_deg: np.ndarray
    zone: np.ndarray              # bool, cellules de la zone
    cell_ha: float
    table_c: dict
    meta: dict = field(default_factory=dict)


def executer(e: Entrees, reboisement=None, urbanisation=None, pratique=None, cible="cultures", pente_min_deg=0.0):
    """Retourne (résultats chiffrés, cartes médianes) pour la référence et le scénario."""
    fr = e.fracs
    bati_ajoute = np.zeros(e.zone.shape, "float32")
    arbres_ajoutes = np.zeros(e.zone.shape, "float32")
    if reboisement and reboisement.get("part", 0) > 0:
        fr, arbres_ajoutes = changer_occupation(fr, e.zone, reboisement["classes"], 10, reboisement["part"])
    if urbanisation and urbanisation.get("part", 0) > 0:
        fr, bati_ajoute = changer_occupation(fr, e.zone, urbanisation["classes"], 50, urbanisation["part"])
    seuil = e.table_c["seuil_hors_domaine"]
    C_ref = {v: c_from_fractions(e.fracs, class_values(e.table_c, v), seuil) for v in ("bas", "central", "haut")}
    C_sc = {v: c_from_fractions(fr, class_values(e.table_c, v), seuil) for v in ("bas", "central", "haut")}
    pvars = ("bas", "central", "haut") if pratique else ("central",)
    P = {v: facteur_p(pratique, v, e.pente_deg, e.zone, fr.get(40), cible, pente_min_deg) for v in pvars}

    tot_ref, tot_sc, names = [], [], []
    a_ref, a_sc = [], []
    for (rn, ln, cv, pv) in product(e.R_ref, e.LS, C_ref, pvars):
        ar = rusle(e.R_ref[rn], e.K, e.LS[ln], C_ref[cv], 1.0)
        asc = rusle(e.R_scen[rn], e.K, e.LS[ln], C_sc[cv], P[pv])
        ar = np.where(e.zone, ar, np.nan); asc = np.where(e.zone, asc, np.nan)
        tot_ref.append(float(np.nansum(ar)) * e.cell_ha); tot_sc.append(float(np.nansum(asc)) * e.cell_ha)
        names.append(f"R={rn}|LS={ln}|C={cv}|P={pv}")
        a_ref.append(ar.astype("float32")); a_sc.append(asc.astype("float32"))
    tot_ref, tot_sc = np.array(tot_ref), np.array(tot_sc)
    with np.errstate(invalid="ignore", divide="ignore"):
        chg = 100 * (tot_sc - tot_ref) / tot_ref
    sr, ss = np.stack(a_ref), np.stack(a_sc)
    import warnings
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med_ref = np.nanmedian(sr, axis=0) if np.isfinite(sr).any() else np.full(e.zone.shape, np.nan)
        med_sc = np.nanmedian(ss, axis=0) if np.isfinite(ss).any() else np.full(e.zone.shape, np.nan)
        diff = np.nanmedian(ss - sr, axis=0) if np.isfinite(ss - sr).any() else np.full(e.zone.shape, np.nan)
    dom_ref = np.isfinite(sr[0]); dom_sc = np.isfinite(ss[0])
    q = lambda a: {"p10": float(np.nanpercentile(a, 10)), "mediane": float(np.nanmedian(a)), "p90": float(np.nanpercentile(a, 90))}  # noqa: E731
    zone_ha = float(e.zone.sum()) * e.cell_ha
    res = {
        "membres": len(names),
        "zone_ha": round(zone_ha, 1),
        "perte_reference_t_an": q(tot_ref),
        "perte_scenario_t_an": q(tot_sc),
        "variation_pct": q(chg),
        "domaine_rusle_reference_ha": round(float(dom_ref.sum()) * e.cell_ha, 1),
        "domaine_rusle_scenario_ha": round(float(dom_sc.sum()) * e.cell_ha, 1),
        "sorti_du_domaine_ha": round(float((dom_ref & ~dom_sc).sum()) * e.cell_ha, 1),
        "bati_ajoute_ha": round(float(bati_ajoute.sum()) * e.cell_ha, 1),
        "arbres_ajoutes_ha": round(float(arbres_ajoutes.sum()) * e.cell_ha, 1),
    }
    if res["sorti_du_domaine_ha"] > 0:
        res["avertissement"] = ("Des cellules urbanisées sortent du domaine de RUSLE : la perte de sol calculée ne porte plus "
                                "que sur le domaine restant, et une baisse éventuelle n'est pas une amélioration. Le ruissellement "
                                "augmente : voir la surface imperméable ajoutée et son report vers l'aval.")
    cartes = {"perte_reference": med_ref, "perte_scenario": med_sc, "difference": diff,
              "sorti_du_domaine": (dom_ref & ~dom_sc), "bati_ajoute": bati_ajoute}
    return res, cartes
