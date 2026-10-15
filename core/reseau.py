"""Réseau en mémoire (sans dépendance QGIS) : tronçons, nœuds, accrochage.

Un tronçon est un dictionnaire :
    tid (identifiant unique), sens (0 double, 1 sens de numérisation, -1 inverse),
    vitesse (km/h), longueur (m), highway, nom, a / b (nœuds de départ / d'arrivée
    de la géométrie), coords [(x, y), ...].
"""
import math


def _proj_point_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    n2 = dx * dx + dy * dy
    t = 0.0 if n2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n2))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy), qx, qy


class Reseau:
    def __init__(self, segments, noeuds):
        self.segments = segments
        self.noeuds = noeuds  # nid -> (x, y)
        self.par_tid = {s["tid"]: s for s in segments}

    def plus_proche_troncon(self, x, y):
        """Tronçon le plus proche et point d'accrochage sur ce tronçon."""
        meilleur = None
        for s in self.segments:
            c = s["coords"]
            for (ax, ay), (bx, by) in zip(c[:-1], c[1:]):
                d, qx, qy = _proj_point_segment(x, y, ax, ay, bx, by)
                if meilleur is None or d < meilleur["dist"]:
                    meilleur = {"id": s["tid"], "dist": d, "x": qx, "y": qy}
        return meilleur

    def plus_proche_noeud(self, x, y):
        meilleur = None
        for nid, (nx, ny) in self.noeuds.items():
            d = math.hypot(x - nx, y - ny)
            if meilleur is None or d < meilleur["dist"]:
                meilleur = {"id": nid, "dist": d, "x": nx, "y": ny}
        return meilleur
