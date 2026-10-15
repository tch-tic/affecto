"""Règles d'édition du réseau (sans dépendance QGIS, testables hors QGIS).

Points = tuples (x, y) en mètres (SCR projeté). Ce module décide quoi faire ; les couches
QGIS sont modifiées dans edition.py.
"""
try:
    from . import geom_utils as g
except ImportError:  # exécution des tests hors paquet
    import geom_utils as g

# Classes proposées à la création d'un tronçon : (valeur OSM, libellé)
CLASSES_CREATION = [
    ("residential", "Rue résidentielle"),
    ("tertiary", "Voie tertiaire"),
    ("secondary", "Voie secondaire"),
    ("primary", "Voie primaire"),
    ("unclassified", "Voie non classée"),
    ("living_street", "Zone de rencontre"),
    ("service", "Voie de service"),
]
LONGUEUR_MIN = 1.0  # m : en dessous, le tracé est jugé accidentel


def sens_inverse(sens):
    """1 <-> -1 ; un double sens reste un double sens."""
    return -int(sens)


def sens_bascule(sens):
    """Double sens -> sens unique (sens du tracé) ; sens unique -> double sens."""
    return 1 if int(sens) == 0 else 0


def prochain_id(ids, plancher=0):
    return max([plancher, *ids]) + 1


def noeud_proche(pt, noeuds, tol):
    """(id, distance) du nœud le plus proche à moins de ``tol``, sinon None."""
    meilleur = None
    for nid, xy in noeuds.items():
        d = g.distance(pt, xy)
        if d <= tol and (meilleur is None or d < meilleur[1]):
            meilleur = (nid, d)
    return meilleur


def troncon_proche(pt, troncons, tol):
    """(id, distance, abscisse, point projeté) du tronçon le plus proche, sinon None.

    ``troncons`` : {id: {"coords": [(x, y), ...]}} (tronçons actifs).
    """
    meilleur = None
    for tid, t in troncons.items():
        d, s, c = g.projeter(t["coords"], pt)
        if d <= tol and (meilleur is None or d < meilleur[1]):
            meilleur = (tid, d, s, c)
    return meilleur


def planifier_extremite(pt, noeuds, troncons, tol):
    """Où raccorder une extrémité : nœud existant, tronçon à couper, ou nouveau nœud."""
    n = noeud_proche(pt, noeuds, tol)
    if n is not None:
        return {"type": "noeud", "id": n[0], "point": noeuds[n[0]]}
    t = troncon_proche(pt, troncons, tol)
    if t is not None:
        tid, _d, s, _c = t
        try:
            avant, apres, coupe = g.decouper(troncons[tid]["coords"], s)
        except ValueError:
            return {"type": "nouveau", "point": pt}
        return {"type": "coupe", "tid": tid, "point": coupe, "avant": avant, "apres": apres}
    return {"type": "nouveau", "point": pt}


def planifier_creation(points, noeuds, troncons, tol):
    """Plan de création d'un tronçon tracé par ``points``.

    Retourne {"debut", "fin", "coords"}. Les extrémités sont raccordées aux nœuds proches ;
    à défaut, au tronçon proche (qui sera coupé en deux) ; à défaut, un nouveau nœud est créé.
    """
    if len(points) < 2:
        raise ValueError("Un tronçon demande au moins deux points.")
    debut = planifier_extremite(points[0], noeuds, troncons, tol)
    fin = planifier_extremite(points[-1], noeuds, troncons, tol)
    if debut["type"] == "coupe" and fin["type"] == "coupe" and debut["tid"] == fin["tid"]:
        raise ValueError("Les deux extrémités tombent sur le même tronçon : raccorder d'abord "
                         "l'une d'elles à un nœud.")
    if debut["type"] == "noeud" and fin["type"] == "noeud" and debut["id"] == fin["id"] \
            and len(points) < 3:
        raise ValueError("Début et fin sur le même nœud : ajouter un point intermédiaire.")
    coords = [debut["point"]] + list(points[1:-1]) + [fin["point"]]
    if g.longueur(coords) < LONGUEUR_MIN:
        raise ValueError("Tracé trop court.")
    return {"debut": debut, "fin": fin, "coords": coords}
