"""Moteur de génération et d'affectation (sans dépendance, testable hors QGIS).

Enchaînement : programmation -> flux émis/attirés par lot (HPM/HPS) -> distribution
par portes -> plus courts chemins avec mouvements tournants -> bilans.

Modèle : affectation « tout ou rien » au plus court chemin en temps, sans congestion,
sans demi-tour. Les accès des lots se situent sur un tronçon (ou sur un nœud) ; les
portes sont des nœuds du réseau.
"""
import heapq
import itertools
from collections import defaultdict

PERIODES = ("hpm", "hps")
SENS = ("emis", "attire")
INF = float("inf")


# --------------------------------------------------------------------------
# 1. Génération des flux
# --------------------------------------------------------------------------
def generer_flux(programme, ratios, directs=()):
    """Flux en véh/h par lot et typologie. ``directs`` prime sur la programmation."""
    r = {x["typologie"]: x for x in ratios}
    cols = [f"{p}_{s}" for p in PERIODES for s in SENS]
    lignes = {}
    for p in programme:
        cle = (p["lot_id"], p["typologie"])
        k = r.get(p["typologie"])
        if k is None:
            raise ValueError(f"Typologie « {p['typologie']} » absente de la table des ratios")
        q = float(p.get("quantite") or 0)
        veh_jour = q / (k["diviseur"] or 1) * k["dep_jour"] * k["part_vp"] / (k["occupation"] or 1)
        if cle not in lignes:
            lignes[cle] = {"lot_id": cle[0], "typologie": cle[1], "quantite": 0.0,
                           "veh_jour": 0.0, "source": "ratios", **{c: 0.0 for c in cols}}
        l = lignes[cle]
        l["quantite"] += q
        l["veh_jour"] += veh_jour
        for c in cols:
            l[c] += veh_jour * k[c]
    for d in directs:
        cle = (d["lot_id"], d["typologie"])
        l = lignes.setdefault(cle, {"lot_id": cle[0], "typologie": cle[1], "quantite": 0.0,
                                    "veh_jour": 0.0, **{c: 0.0 for c in cols}})
        l["source"] = "direct"
        for c in cols:
            l[c] = float(d.get(c) or 0)
    return list(lignes.values())


def parts_distribution(dist, lot, typo, sens, avertissements):
    """Parts par porte (priorité : 'lot|typologie' > 'lot' > 'defaut'), normalisées."""
    col = f"part_{sens}"
    for portee in (f"{lot}|{typo}", str(lot), "defaut"):
        lignes = [d for d in dist if d["portee"] == portee]
        if lignes:
            parts = defaultdict(float)
            for d in lignes:
                parts[d["porte_id"]] += float(d.get(col) or 0)
            tot = sum(parts.values())
            if tot <= 0:
                raise ValueError(f"Distribution {sens} nulle pour « {portee} »")
            if abs(tot - 1) > 0.01 and abs(tot - 100) > 1:
                avertissements.append(
                    f"Distribution {sens} de « {portee} » = {tot:.1f} : normalisée à 100 %")
            return {p: v / tot for p, v in parts.items() if v > 0}
    raise ValueError(f"Aucune distribution pour {lot}|{typo} (ajouter une ligne « defaut »)")


# --------------------------------------------------------------------------
# 2. Graphe d'arcs orientés et plus courts chemins
# --------------------------------------------------------------------------
class Graphe:
    """Arcs orientés (tid, +1 | -1) ; un virage = passage d'un arc au suivant."""

    def __init__(self, segments, interdictions=(), penalite_virage_s=0.0):
        self.segments = {s["tid"]: s for s in segments}
        self.arcs = {}
        self.out = defaultdict(list)
        self.inc = defaultdict(list)
        self.par_troncon = defaultdict(list)
        self.interdits = set(interdictions)
        self.penalite = penalite_virage_s
        for s in segments:
            v = max(float(s.get("vitesse") or 30), 5.0)
            t = s["longueur"] / (v / 3.6)
            if s["sens"] in (0, 1):
                self._ajouter(s["tid"], 1, s["a"], s["b"], t)
            if s["sens"] in (0, -1):
                self._ajouter(s["tid"], -1, s["b"], s["a"], t)
        self._cache = {}

    def _ajouter(self, tid, d, u, v, t):
        arc = (tid, d)
        self.arcs[arc] = {"u": u, "v": v, "t": t}
        self.out[u].append(arc)
        self.inc[v].append(arc)
        self.par_troncon[tid].append(arc)

    def existe(self, ref):
        kind, val = ref
        return bool(self.out[val] or self.inc[val]) if kind == "noeud" else bool(self.par_troncon[val])

    def _dijkstra(self, sources):
        dist = dict(sources)
        prev = {a: None for a in sources}
        cpt = itertools.count()
        tas = [(d, next(cpt), a) for a, d in dist.items()]
        heapq.heapify(tas)
        while tas:
            d, _, a = heapq.heappop(tas)
            if d > dist.get(a, INF):
                continue
            for b in self.out[self.arcs[a]["v"]]:
                if b[0] == a[0] or (a, b) in self.interdits:  # pas de demi-tour
                    continue
                nd = d + self.arcs[b]["t"] + self.penalite
                if nd < dist.get(b, INF):
                    dist[b] = nd
                    prev[b] = a
                    heapq.heappush(tas, (nd, next(cpt), b))
        return dist, prev

    def chemin(self, origine, destination):
        """Liste d'arcs entre deux références ('noeud', id) ou ('troncon', tid)."""
        if origine not in self._cache:
            depart = self.out[origine[1]] if origine[0] == "noeud" else self.par_troncon[origine[1]]
            self._cache[origine] = self._dijkstra({a: self.arcs[a]["t"] for a in depart})
        dist, prev = self._cache[origine]
        arrivee = self.inc[destination[1]] if destination[0] == "noeud" \
            else self.par_troncon[destination[1]]
        cands = [(dist[a], a) for a in arrivee if a in dist]
        if not cands:
            return None
        arc = min(cands)[1]
        chemin = [arc]
        while prev[chemin[-1]] is not None:
            chemin.append(prev[chemin[-1]])
        return chemin[::-1]

    def temps(self, chemin):
        return sum(self.arcs[a]["t"] for a in chemin)


# --------------------------------------------------------------------------
# 3. Affectation
# --------------------------------------------------------------------------
def nom_arc(arc):
    return f"{arc[0]}{'+' if arc[1] > 0 else '-'}"


def affecter(graphe, flux, acces, portes, dist):
    """Affecte les flux de chaque lot/typologie, sens et période.

    ``acces``  : dicts lot_id, acces_id, troncon_id (ou None), noeud (ou None), part
    ``portes`` : dict porte_id -> id de nœud
    Retourne (flux par arc, flux par virage, journal, avertissements).
    """
    avert = []
    f_arc = {p: defaultdict(float) for p in PERIODES}
    f_vir = {p: defaultdict(float) for p in PERIODES}
    journal = []
    perdu = {p: 0.0 for p in PERIODES}
    sans_chemin = defaultdict(lambda: {p: 0.0 for p in PERIODES})

    par_lot = defaultdict(list)
    for a in acces:
        if a.get("troncon_id") not in (None, ""):
            ref = ("troncon", int(a["troncon_id"]))
        elif a.get("noeud") not in (None, ""):
            ref = ("noeud", int(a["noeud"]))
        else:
            avert.append(f"Accès {a['lot_id']}/{a['acces_id']} sans position : ignoré")
            continue
        if not graphe.existe(ref):
            avert.append(f"Accès {a['lot_id']}/{a['acces_id']} : tronçon ou nœud introuvable "
                         "dans le réseau du scénario")
            continue
        par_lot[a["lot_id"]].append({**a, "ref": ref, "part": float(a.get("part") or 0)})
    for lot, liste in par_lot.items():
        tot = sum(a["part"] for a in liste)
        for a in liste:
            a["part"] = a["part"] / tot if tot > 0 else 1.0 / len(liste)

    for l in flux:
        lot = l["lot_id"]
        if lot not in par_lot:
            avert.append(f"Lot {lot} : aucun accès valide, flux non affectés")
            for p in PERIODES:
                perdu[p] += l[f"{p}_emis"] + l[f"{p}_attire"]
            continue
        for sens in SENS:
            parts = parts_distribution(dist, lot, l["typologie"], sens, avert)
            for p in PERIODES:
                q_tot = l[f"{p}_{sens}"]
                if q_tot <= 0:
                    continue
                for a in par_lot[lot]:
                    for porte, s in parts.items():
                        q = q_tot * a["part"] * s
                        if porte not in portes:
                            avert.append(f"Porte « {porte} » inconnue : {q:.1f} véh/h ignorés")
                            perdu[p] += q
                            continue
                        ref_p = ("noeud", int(portes[porte]))
                        o, d = (a["ref"], ref_p) if sens == "emis" else (ref_p, a["ref"])
                        if o == d:
                            continue
                        chemin = graphe.chemin(o, d)
                        if not chemin:
                            sans_chemin[(lot, a["acces_id"], porte)][p] += q
                            perdu[p] += q
                            continue
                        for arc in chemin:
                            f_arc[p][arc] += q
                        for x, y in zip(chemin[:-1], chemin[1:]):
                            f_vir[p][(x, y)] += q
                        journal.append({
                            "lot_id": lot, "typologie": l["typologie"], "sens": sens,
                            "periode": p.upper(), "acces": a["acces_id"], "porte": porte,
                            "flux": round(q, 2), "temps_s": round(graphe.temps(chemin), 1),
                            "chemin": ">".join(nom_arc(x) for x in chemin)})
    for (lot, acc, porte), v in sans_chemin.items():
        avert.append(f"Aucun chemin entre l'accès {lot}/{acc} et la porte {porte} (réseau non "
                     "connexe ou sens uniques) : " +
                     ", ".join(f"{p.upper()} {q:.0f}" for p, q in v.items()) + " véh/h non affectés")
    if any(v > 0 for v in perdu.values()):
        avert.append("Total des flux non affectés (véh/h) : " +
                     ", ".join(f"{p.upper()} {v:.0f}" for p, v in perdu.items()))
    return f_arc, f_vir, journal, list(dict.fromkeys(avert))


# --------------------------------------------------------------------------
# 4. Résultats
# --------------------------------------------------------------------------
def resultats_arcs(graphe, f_arc, ref):
    """Une ligne par arc : trafic de référence, projet, total, hausse en %."""
    rows = []
    for (tid, d), _arc in sorted(graphe.arcs.items()):
        s = graphe.segments[tid]
        row = {"tid": tid, "dir": d, "double": 1 if s["sens"] == 0 else 0,
               "nom": s.get("nom") or "", "highway": s.get("highway") or "",
               "longueur": round(s["longueur"], 1)}
        for p in PERIODES:
            r = (ref.get(tid, {}).get(f"{p}_{'ab' if d == 1 else 'ba'}") or 0.0)
            proj = f_arc[p].get((tid, d), 0.0)
            row[f"{p}_ref"] = round(r, 1)
            row[f"{p}_proj"] = round(proj, 1)
            row[f"{p}_tot"] = round(r + proj, 1)
            row[f"{p}_pct"] = round(proj / r * 100, 1) if r > 0 else None
        rows.append(row)
    return rows


def resultats_virages(graphe, f_vir, noeuds):
    cles = set()
    for p in PERIODES:
        cles |= set(f_vir[p])
    rows = []
    for (a, b) in sorted(cles):
        nid = graphe.arcs[a]["v"]
        x, y = noeuds.get(nid, (None, None))
        sa, sb = graphe.segments[a[0]], graphe.segments[b[0]]
        row = {"noeud": nid, "x": x, "y": y, "arc_in": nom_arc(a), "arc_out": nom_arc(b),
               "nom_in": sa.get("nom") or "", "nom_out": sb.get("nom") or ""}
        for p in PERIODES:
            row[f"{p}_proj"] = round(f_vir[p].get((a, b), 0.0), 1)
        rows.append(row)
    return rows


def synthese(arcs, flux, avertissements=()):
    """Indicateurs par période. La hausse max ignore les arcs de référence < 50 véh/h."""
    out = []
    for p in PERIODES:
        impactes = [r for r in arcs if r[f"{p}_proj"] > 0]
        r_delta = max(impactes, key=lambda r: r[f"{p}_proj"], default=None)
        cand = [r for r in impactes if r[f"{p}_ref"] >= 50 and r[f"{p}_pct"] is not None]
        r_pct = max(cand, key=lambda r: r[f"{p}_pct"], default=None)

        def lib(r):
            return f"{r['nom'] or '(sans nom)'} [{r['tid']}{'+' if r['dir'] > 0 else '-'}]" if r else ""
        out.append({
            "periode": p.upper(),
            "flux_emis": round(sum(l[f"{p}_emis"] for l in flux), 1),
            "flux_attire": round(sum(l[f"{p}_attire"] for l in flux), 1),
            "veh_km": round(sum(r[f"{p}_proj"] * r["longueur"] / 1000 for r in arcs), 1),
            "nb_arcs": len(impactes),
            "delta_max": r_delta[f"{p}_proj"] if r_delta else 0,
            "arc_delta_max": lib(r_delta),
            "hausse_max_pct": r_pct[f"{p}_pct"] if r_pct else 0,
            "arc_hausse_max": lib(r_pct),
        })
    return out


# --------------------------------------------------------------------------
# 5. Trafic de référence fictif (pour tester sans comptages)
# --------------------------------------------------------------------------
# Ordre de grandeur par direction (véh/h), calé sur une carte de charges HPM réelle :
# axes structurants 700-1900, secondaires 300-1000, desserte 30-300.
_PLAGES = {
    "primary": (700, 1900), "primary_link": (100, 500),
    "secondary": (300, 1000), "secondary_link": (100, 400),
    "tertiary": (150, 600), "tertiary_link": (50, 300),
    "unclassified": (50, 300), "residential": (30, 300), "living_street": (10, 120),
}


def trafic_ref_fictif(segments, graine=42):
    import random
    rnd = random.Random(graine)
    out = {}
    for s in sorted(segments, key=lambda x: x["tid"]):
        lo, hi = _PLAGES.get(s.get("highway"), (50, 300))
        base_m = rnd.uniform(lo, hi)
        base_s = base_m * rnd.uniform(0.8, 1.2)
        ligne = {}
        for per, base in (("hpm", base_m), ("hps", base_s)):
            for d, suffixe in ((1, "ab"), (-1, "ba")):
                permis = s["sens"] == 0 or s["sens"] == d
                v = base * rnd.uniform(0.6, 1.4) * (1.0 if s["sens"] == 0 else 1.4)
                ligne[f"{per}_{suffixe}"] = float(round(v / 10) * 10) if permis else 0.0
        out[s["tid"]] = ligne
    return out
