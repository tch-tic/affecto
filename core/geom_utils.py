"""Géométrie plane sans dépendance (testable hors QGIS) : points = tuples (x, y)."""
import math


def distance(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def longueur(points):
    return sum(distance(p, q) for p, q in zip(points[:-1], points[1:]))


def projeter(points, pt):
    """Point le plus proche de ``pt`` sur la polyligne.

    Retourne (distance au point, abscisse curviligne, point projeté).
    """
    meilleur, cumul = None, 0.0
    for p, q in zip(points[:-1], points[1:]):
        dx, dy = q[0] - p[0], q[1] - p[1]
        n2 = dx * dx + dy * dy
        t = 0.0 if n2 == 0 else max(0.0, min(1.0, ((pt[0] - p[0]) * dx + (pt[1] - p[1]) * dy) / n2))
        c = (p[0] + t * dx, p[1] + t * dy)
        d = distance(pt, c)
        if meilleur is None or d < meilleur[0]:
            meilleur = (d, cumul + t * math.sqrt(n2), c)
        cumul += math.sqrt(n2)
    return meilleur


def decouper(points, d):
    """Coupe une polyligne à l'abscisse curviligne ``d``.

    Retourne (partie_avant, partie_après, point_de_coupe). Les deux parties partagent
    le point de coupe ; aucun point en double n'est créé si la coupe tombe sur un sommet.
    """
    avant, apres, coupe, cumul = [points[0]], None, None, 0.0
    for p, q in zip(points[:-1], points[1:]):
        seg = distance(p, q)
        if apres is None:
            if cumul + seg > d and seg > 0:
                t = (d - cumul) / seg
                coupe = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
                if distance(avant[-1], coupe) > 1e-6:
                    avant.append(coupe)
                apres = [coupe, q]
            else:
                avant.append(q)
        else:
            apres.append(q)
        cumul += seg
    if apres is None or len(apres) < 2:
        raise ValueError("Abscisse de coupe hors de la polyligne")
    return avant, apres, coupe
