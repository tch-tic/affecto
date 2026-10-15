"""Pont entre le GeoPackage / QGIS et le moteur (engine.py)."""
from qgis.core import Qgis, QgsGeometry, QgsPointXY

from . import engine
from .defauts import SCHEMAS
from .reseau import Reseau
from .store import PREFIX_NOEUDS, PREFIX_TRONCONS

DECALAGE_M = 8.0  # décalage latéral (à droite) des arcs des voies à double sens


def _val(v, defaut=None):
    from qgis.core import NULL
    return defaut if (v is None or v == NULL) else v


def lire_reseau(projet, variante):
    """Construit le Reseau (moteur) et les géométries QGIS d'une variante.

    La topologie vient de la géométrie : les extrémités d'un tronçon sont rapprochées
    des nœuds par leurs coordonnées (0,1 m). Un tronçon dessiné ou déplacé à la main
    reste donc cohérent sans mise à jour des champs u/v. Les identifiants de tronçon
    sont le champ « id » (voir ci-dessous).
    Retourne (reseau, geometries {tid: QgsGeometry}, crs).
    """
    tr = projet.couche(PREFIX_TRONCONS + variante)
    no = projet.couche(PREFIX_NOEUDS + variante)
    if tr is None or no is None:
        raise ValueError(f"Variante de réseau « {variante} » introuvable dans le GeoPackage")

    def cle(x, y):
        return (round(x, 1), round(y, 1))

    noeuds, index = {}, {}
    for f in no.getFeatures():
        p = f.geometry().asPoint()
        nid = int(f["id"])
        noeuds[nid] = (p.x(), p.y())
        index[cle(p.x(), p.y())] = nid
    synthetique = [-1]

    def noeud_en(pt):
        k = cle(pt.x(), pt.y())
        if k not in index:
            index[k] = synthetique[0]
            noeuds[synthetique[0]] = (pt.x(), pt.y())
            synthetique[0] -= 1
        return index[k]

    # Identifiant de tronçon = champ « id » (conservé lors des duplications de variantes).
    # S'il est vide ou en double (tronçon dessiné à la main), un identifiant provisoire est attribué.
    entites = list(tr.getFeatures())
    valides = [int(_val(f["id"])) for f in entites if _val(f["id"]) is not None]
    suivant = (max(valides) if valides else 0) + 1
    vus, provisoires = set(), 0

    segments, geoms = [], {}
    a_actif = tr.fields().indexOf("actif") >= 0
    for f in entites:
        if a_actif and int(_val(f["actif"], 1)) == 0:
            continue  # tronçon désactivé : conservé dans la couche, ignoré par le calcul
        g = QgsGeometry(f.geometry())
        if g.isNull():
            continue
        if g.isMultipart():
            g.convertToSingleType()
            if g.isMultipart():
                continue
        pts = g.asPolyline()
        if len(pts) < 2:
            continue
        tid = _val(f["id"])
        if tid is None or int(tid) in vus:
            tid, suivant, provisoires = suivant, suivant + 1, provisoires + 1
        tid = int(tid)
        vus.add(tid)
        segments.append({
            "tid": tid, "sens": int(_val(f["sens"], 0)), "vitesse": float(_val(f["vitesse"], 30)),
            "longueur": g.length(), "highway": _val(f["highway"], ""), "nom": _val(f["nom"], ""),
            "a": noeud_en(pts[0]), "b": noeud_en(pts[-1]),
            "coords": [(p.x(), p.y()) for p in pts]})
        geoms[tid] = g
    reseau = Reseau(segments, noeuds)
    reseau.avertissements = []
    if provisoires:
        reseau.avertissements.append(
            f"{provisoires} tronçon(s) sans identifiant « id » valide : identifiants provisoires "
            "attribués (renseigner le champ « id » pour les conserver).")
    return reseau, geoms, tr.crs()


def lire_ref(projet, variante):
    return {int(r["tid"]): r for r in projet.lire_lignes(f"trafic_ref__{variante}")}


def ecrire_ref_fictif(projet, variante, reseau):
    ref = engine.trafic_ref_fictif(reseau.segments)
    projet.ecrire_lignes(f"trafic_ref__{variante}", SCHEMAS["trafic_ref"],
                         [{"tid": t, **d} for t, d in ref.items()])
    return len(ref)


def _arc_geometrie(g, direction, double):
    """Géométrie de l'arc : sens de circulation, décalée à droite si double sens."""
    if direction < 0:
        g = QgsGeometry.fromPolylineXY(list(reversed(g.asPolyline())))
    if double:
        try:
            join = Qgis.JoinStyle.Round
        except AttributeError:
            join = QgsGeometry.JoinStyleRound
        dec = g.offsetCurve(-DECALAGE_M, 4, join, 2.0)  # distance négative = côté droit
        if dec is not None and not dec.isNull():
            return dec
    return g


def lancer_scenario(projet, scenario):
    """Charge les tables du scénario, exécute le moteur et écrit les résultats.

    Retourne un dict : synthese, arcs, generation, avertissements.
    """
    nom, variante = scenario["nom"], scenario["variante"]
    reseau, geoms, crs = lire_reseau(projet, variante)
    ref = lire_ref(projet, variante)

    def du_scenario(table):
        return [l for l in projet.lire_lignes(table) if l.get("scenario") == nom]

    ratios = projet.lire_lignes("ratios")
    programme = du_scenario("programme")
    directs = du_scenario("flux_directs")
    acces = du_scenario("acces")
    portes = {l["porte_id"]: l["noeud"] for l in du_scenario("portes")}
    dist = du_scenario("distribution")
    if not programme and not directs:
        raise ValueError("Le scénario ne contient ni programmation ni flux saisis directement.")
    if not acces:
        raise ValueError("Aucun accès de lot défini (onglet Programme).")
    if not portes or not dist:
        raise ValueError("Portes et distribution à définir (onglet Distribution).")

    flux = engine.generer_flux(programme, ratios, directs)
    graphe = engine.Graphe(reseau.segments)
    f_arc, f_vir, journal, avert = engine.affecter(graphe, flux, acces, portes, dist)
    arcs = engine.resultats_arcs(graphe, f_arc, ref)
    virages = engine.resultats_virages(graphe, f_vir, reseau.noeuds)
    synth = engine.synthese(arcs, flux, avert)
    avert.extend(reseau.avertissements)
    if not ref:
        avert.append("Pas de trafic de référence pour ce réseau : les hausses (%) ne sont pas calculées.")

    _ecrire_resultats(projet, nom, crs, geoms, arcs, virages, flux, synth, journal)
    return {"synthese": synth, "arcs": arcs, "generation": flux, "avertissements": avert}


def _ecrire_resultats(projet, nom, crs, geoms, arcs, virages, flux, synth, journal):
    schema_arcs = [("tid", "int"), ("dir", "int"), ("double", "int"), ("nom", "str"),
                   ("highway", "str"), ("longueur", "float")]
    for p in engine.PERIODES:
        schema_arcs += [(f"{p}_ref", "float"), (f"{p}_proj", "float"),
                        (f"{p}_tot", "float"), (f"{p}_pct", "float")]
    projet.ecrire_lignes(f"res_arcs__{nom}", schema_arcs, arcs, "LineString", crs,
                         lambda r: _arc_geometrie(geoms[r["tid"]], r["dir"], r["double"]))

    schema_vir = [("noeud", "int"), ("arc_in", "str"), ("arc_out", "str"),
                  ("nom_in", "str"), ("nom_out", "str"),
                  ("hpm_proj", "float"), ("hps_proj", "float"), ("x", "float"), ("y", "float")]
    projet.ecrire_lignes(
        f"res_virages__{nom}", schema_vir, virages, "Point", crs,
        lambda r: QgsGeometry.fromPointXY(QgsPointXY(r["x"], r["y"])) if r["x"] is not None else None)
    projet.ecrire_lignes(f"res_generation__{nom}", SCHEMAS["res_generation"], flux)
    projet.ecrire_lignes(f"res_synthese__{nom}", SCHEMAS["res_synthese"], synth)
    projet.ecrire_lignes(f"res_journal__{nom}", SCHEMAS["res_journal"], journal)
