"""Requête Overpass et découpage des voies OSM en tronçons.

Module volontairement sans dépendance à QGIS : il est testable seul
(voir tests/test_osm_parse.py).
"""
import re
from collections import Counter

_STRUCTURANT = [
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link",
]
_STANDARD = _STRUCTURANT + ["unclassified", "residential", "living_street"]

# Niveaux de détail proposés dans l'interface (clé -> classes highway OSM)
NIVEAUX = {
    "structurant": _STRUCTURANT,
    "standard": _STANDARD,
    "complet": _STANDARD + ["service"],
}

# Vitesses par défaut (km/h) quand maxspeed est absent : à adapter au pays.
VITESSE_DEFAUT = {
    "motorway": 110, "motorway_link": 70, "trunk": 80, "trunk_link": 60,
    "primary": 50, "primary_link": 40, "secondary": 50, "secondary_link": 40,
    "tertiary": 50, "tertiary_link": 40, "unclassified": 50,
    "residential": 50, "living_street": 20, "service": 20,
}

_ALIAS_VITESSE = {
    "walk": 10, "urban": 50, "rural": 80,
    "fr:urban": 50, "fr:rural": 80, "fr:motorway": 130,
    "ch:urban": 50, "ch:rural": 80, "ch:motorway": 120,
}


def requete_overpass(anneau_lonlat, niveau="standard", timeout=120):
    """Construit la requête Overpass QL pour un anneau [(lon, lat), ...]."""
    if niveau not in NIVEAUX:
        raise ValueError(f"Niveau de détail inconnu : {niveau}")
    if len(anneau_lonlat) < 4:
        raise ValueError("Le périmètre doit comporter au moins 3 sommets")
    poly = " ".join(f"{lat:.6f} {lon:.6f}" for lon, lat in anneau_lonlat)
    classes = "|".join(NIVEAUX[niveau])
    return (f'[out:json][timeout:{timeout}][maxsize:536870912];'
            f'way["highway"~"^({classes})$"]["area"!="yes"](poly:"{poly}");'
            f'out geom;')


def verifier_reponse(data):
    """(utilisable, message). Overpass peut répondre 200 avec une réponse tronquée et un
    « remark » (délai dépassé, mémoire) : elle ne doit pas être prise pour un réseau complet."""
    if not isinstance(data, dict) or "elements" not in data:
        return False, (data.get("remark") if isinstance(data, dict) else None) \
            or "réponse inattendue"
    remarque = (data.get("remark") or "")
    if any(m in remarque.lower() for m in ("timed out", "out of memory", "runtime error")):
        return False, remarque
    return True, ""


def sens_osm(tags):
    """Sens de circulation : 0 double sens, 1 sens de numérisation, -1 inverse."""
    oneway = (tags.get("oneway") or "").lower()
    if oneway in ("yes", "true", "1"):
        return 1
    if oneway == "-1":
        return -1
    if oneway in ("no", "false", "0", "reversible", "alternating"):
        return 0
    if tags.get("junction") in ("roundabout", "circular"):
        return 1
    if tags.get("highway") in ("motorway", "motorway_link"):
        return 1
    return 0


def vitesse_tag(tags):
    """Vitesse (km/h) lue dans maxspeed, ou None si le tag est absent ou inexploitable."""
    brut = (tags.get("maxspeed") or "").strip().lower()
    if not brut:
        return None
    m = re.match(r"^(\d+)\s*(mph)?", brut)
    if m:
        v = int(m.group(1))
        return round(v * 1.609) if m.group(2) else v
    return _ALIAS_VITESSE.get(brut)


def vitesse_osm(tags):
    """Vitesse utilisée pour le calcul : maxspeed si disponible, sinon valeur par défaut."""
    v = vitesse_tag(tags)
    return v if v is not None else VITESSE_DEFAUT.get(tags.get("highway"), 50)


def rond_point_osm(tags):
    """1 pour un giratoire (utile pour ne pas dessiner de flèches), sinon 0."""
    return 1 if tags.get("junction") in ("roundabout", "circular") else 0


def ouvrage_osm(tags):
    """'tunnel', 'pont' ou '' (voie au niveau du sol)."""
    tunnel = (tags.get("tunnel") or "").lower()
    pont = (tags.get("bridge") or "").lower()
    if tunnel and tunnel != "no":
        return "tunnel"
    if pont and pont != "no":
        return "pont"
    return ""


def niveau_osm(tags):
    """Valeur du tag layer (entier), 0 par défaut."""
    brut = (tags.get("layer") or "").strip()
    try:
        return int(brut)
    except ValueError:
        return 0


def voies_osm(tags):
    brut = (tags.get("lanes") or "").strip()
    return int(brut) if brut.isdigit() else None


def decouper(elements):
    """Découpe les voies OSM en tronçons entre intersections.

    Un tronçon va d'un nœud partagé (ou extrémité de voie) au suivant.
    Retourne une liste de dictionnaires (coords en lon/lat).
    """
    voies = [
        e for e in elements
        if e.get("type") == "way" and e.get("geometry")
        and len(e.get("nodes", [])) == len(e["geometry"]) >= 2
    ]
    usage = Counter()
    for v in voies:
        usage.update(v["nodes"])

    segments = []
    for v in voies:
        noeuds = v["nodes"]
        coords = [(p["lon"], p["lat"]) for p in v["geometry"]]
        tags = v.get("tags", {})
        base = {
            "osm_id": v["id"],
            "nom": tags.get("name") or tags.get("ref") or "",
            "highway": tags.get("highway", ""),
            "sens": sens_osm(tags),
            "vitesse": vitesse_osm(tags),
            "vit_osm": vitesse_tag(tags),
            "voies": voies_osm(tags),
            "rond_point": rond_point_osm(tags),
            "ouvrage": ouvrage_osm(tags),
            "niveau": niveau_osm(tags),
        }
        coupes = [0] + [i for i in range(1, len(noeuds) - 1) if usage[noeuds[i]] > 1] \
            + [len(noeuds) - 1]
        for a, b in zip(coupes[:-1], coupes[1:]):
            segments.append({**base, "u": noeuds[a], "v": noeuds[b],
                             "coords": coords[a:b + 1]})
    for i, s in enumerate(segments, 1):
        s["id"] = i
    return segments
