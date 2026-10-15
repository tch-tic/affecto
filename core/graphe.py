"""Réseau orienté et plus courts chemins avec mouvements tournants.

Sans dépendance (ni QGIS ni networkx) : Dijkstra écrit avec ``heapq`` pour que
le plugin fonctionne dans n'importe quelle installation de QGIS.

Modèle :
- un tronçon (ligne avec champ ``sens``) donne 1 ou 2 arcs orientés :
  ``<id>:d`` (sens de numérisation) et ``<id>:i`` (sens inverse) ;
- les nœuds sont déduits des extrémités géométriques des tronçons (tolérance
  de 10 cm), pas des champs u/v : le réseau reste donc valide après édition ;
- le calcul se fait sur les arcs (graphe « de lignes »), ce qui permet de
  compter chaque virage et de ne jamais faire demi-tour sur un même tronçon.
"""
import heapq
import math
from collections import defaultdict

TOL = 0.1  # m : deux extrémités à moins de 10 cm sont le même nœud

# Hiérarchie des voies (0 = la plus importante)
RANG = {
    "motorway": 0, "motorway_link": 0, "trunk": 1, "trunk_link": 1,
    "primary": 2, "primary_link": 2, "secondary": 3, "secondary_link": 3,
    "tertiary": 4, "tertiary_link": 4, "unclassified": 5, "residential": 6,
    "living_street": 7, "service": 8,
}

# Capacité indicative par sens (véh/h), utilisée pour le taux de charge
CAPACITE_DEFAUT = {
    "motorway": 1800, "motorway_link": 1200, "trunk": 1600, "trunk_link": 1000,
    "primary": 1400, "primary_link": 900, "secondary": 1000, "secondary_link": 800,
    "tertiary": 800, "tertiary_link": 700, "unclassified": 600,
    "residential": 500, "living_street": 300, "service": 300,
}

PERIODES = ("hpm", "hps")


def cle_noeud(x, y):
    return (round(x / TOL), round(y / TOL))


def longueur_ligne(pts):
    return sum(math.dist(p, q) for p, q in zip(pts[:-1], pts[1:]))


def decaler_ligne(pts, d):
    """Décale une polyligne de ``d`` mètres vers la DROITE (repère y vers le nord)."""
    if len(pts) < 2 or not d:
        return list(pts)
    normales = []
    for p, q in zip(pts[:-1], pts[1:]):
        dx, dy = q[0] - p[0], q[1] - p[1]
        n = math.hypot(dx, dy) or 1.0
        normales.append((dy / n, -dx / n))
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            nx, ny = normales[0]
        elif i == len(pts) - 1:
            nx, ny = normales[-1]
        else:
            ax, ay = normales[i - 1]
            bx, by = normales[i]
            sx, sy = ax + bx, ay + by
            n = math.hypot(sx, sy)
            if n < 1e-9:
                nx, ny = ax, ay
            else:
                sx, sy = sx / n, sy / n
                cos = max(sx * ax + sy * ay, 0.5)  # limite l'allongement aux angles vifs
                nx, ny = sx / cos, sy / cos
        out.append((p[0] + nx * d, p[1] + ny * d))
    return out


class Reseau:
    """Arcs orientés construits à partir d'une liste de tronçons.

    Chaque tronçon : dict avec ``id``, ``coords`` [(x, y), …], ``sens``
    (0 double sens, 1 sens de numérisation, -1 inverse), ``vitesse`` (km/h),
    ``highway``, ``nom`` et, facultatif, ``hpm_dir``/``hpm_inv``/``hps_dir``/``hps_inv``
    (trafic de référence par sens, véh/h).
    """

    def __init__(self, troncons):
        self.arcs = {}
        self.noeuds = {}
        self.sortants = defaultdict(list)
        self.entrants = defaultdict(list)
        self.ignores = []
        self._suivants = {}
        self._arbres = {}
        for t in troncons:
            pts = [tuple(p) for p in t["coords"]]
            if len(pts) < 2:
                self.ignores.append(t["id"])
                continue
            sens = t.get("sens")
            sens = sens if sens in (0, 1, -1) else 0
            a, b = cle_noeud(*pts[0]), cle_noeud(*pts[-1])
            self.noeuds.setdefault(a, pts[0])
            self.noeuds.setdefault(b, pts[-1])
            longueur = t.get("longueur") or longueur_ligne(pts)
            vitesse = max(float(t.get("vitesse") or 30), 5.0)
            temps = longueur / (vitesse / 3.6)
            highway = t.get("highway") or ""
            for suf, dep, arr, coords, ok in (
                    ("d", a, b, pts, sens in (0, 1)),
                    ("i", b, a, pts[::-1], sens in (0, -1))):
                if not ok:
                    continue
                arc_id = f"{t['id']}:{suf}"
                self.arcs[arc_id] = {
                    "id": arc_id, "tron": t["id"], "dir": suf,
                    "depart": dep, "arrivee": arr, "coords": coords,
                    "longueur": longueur, "temps": temps,
                    "nom": t.get("nom") or "", "highway": highway,
                    "capacite": CAPACITE_DEFAUT.get(highway, 600),
                    "deux_sens": sens == 0,
                    "ref": {p: float(t.get(f"{p}_{'dir' if suf == 'd' else 'inv'}") or 0)
                            for p in PERIODES},
                }
                self.sortants[dep].append(arc_id)
                self.entrants[arr].append(arc_id)

    # -- voisinage ------------------------------------------------------------
    def suivants(self, arc_id):
        """Arcs atteignables depuis ``arc_id`` (sans demi-tour sur le même tronçon)."""
        if arc_id not in self._suivants:
            a = self.arcs[arc_id]
            self._suivants[arc_id] = [
                b for b in self.sortants[a["arrivee"]]
                if not (self.arcs[b]["tron"] == a["tron"] and self.arcs[b]["dir"] != a["dir"])]
        return self._suivants[arc_id]

    def noeud_proche(self, x, y):
        """(clé du nœud le plus proche, distance en m)."""
        best, dmin = None, float("inf")
        for k, (nx, ny) in self.noeuds.items():
            d = math.hypot(nx - x, ny - y)
            if d < dmin:
                best, dmin = k, d
        return best, dmin

    # -- plus courts chemins -------------------------------------------------------
    def _arbre(self, origine):
        if origine in self._arbres:
            return self._arbres[origine]
        dist, pred, tas = {}, {}, []
        for a in self.sortants[origine]:
            dist[a] = self.arcs[a]["temps"]
            pred[a] = None
            heapq.heappush(tas, (dist[a], a))
        while tas:
            d, a = heapq.heappop(tas)
            if d > dist[a]:
                continue
            for b in self.suivants(a):
                nd = d + self.arcs[b]["temps"]
                if nd < dist.get(b, float("inf")):
                    dist[b] = nd
                    pred[b] = a
                    heapq.heappush(tas, (nd, b))
        self._arbres[origine] = (dist, pred)
        return dist, pred

    def chemin(self, origine, destination):
        """Liste ordonnée d'arcs de ``origine`` à ``destination`` (None si inaccessible)."""
        if origine == destination:
            return None
        dist, pred = self._arbre(origine)
        candidats = [a for a in self.entrants[destination] if a in dist]
        if not candidats:
            return None
        a = min(candidats, key=lambda x: (dist[x], x))
        chemin = []
        while a is not None:
            chemin.append(a)
            a = pred[a]
        return chemin[::-1]

    def type_virage(self, a_id, b_id):
        """'TD' tout droit, 'TG' à gauche, 'TAD' à droite (seuil de 30°)."""
        a, b = self.arcs[a_id]["coords"], self.arcs[b_id]["coords"]
        ax, ay = a[-1][0] - a[-2][0], a[-1][1] - a[-2][1]
        bx, by = b[1][0] - b[0][0], b[1][1] - b[0][1]
        ang = math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
        if ang > 30:
            return "TG"
        if ang < -30:
            return "TAD"
        return "TD"
