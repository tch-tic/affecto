"""Schémas des tables du GeoPackage et valeurs par défaut (sans dépendance QGIS).

Types : "str", "float", "int". Les ratios par défaut sont INDICATIFS : à remplacer par
ceux de l'étude (ratios, parts modales et parts HPM/HPS dépendent du contexte).
"""

SCHEMAS = {
    "scenarios": [("nom", "str"), ("libelle", "str"), ("variante", "str"),
                  ("description", "str"), ("cree_le", "str")],
    "ratios": [("typologie", "str"), ("unite", "str"), ("diviseur", "float"),
               ("dep_jour", "float"), ("part_vp", "float"), ("occupation", "float"),
               ("hpm_emis", "float"), ("hpm_attire", "float"),
               ("hps_emis", "float"), ("hps_attire", "float")],
    "programme": [("scenario", "str"), ("lot_id", "str"), ("typologie", "str"),
                  ("quantite", "float")],
    "flux_directs": [("scenario", "str"), ("lot_id", "str"), ("typologie", "str"),
                     ("hpm_emis", "float"), ("hpm_attire", "float"),
                     ("hps_emis", "float"), ("hps_attire", "float")],
    "acces": [("scenario", "str"), ("lot_id", "str"), ("acces_id", "str"),
              ("troncon_id", "int"), ("noeud", "int"), ("part", "float"),
              ("x", "float"), ("y", "float")],
    "portes": [("scenario", "str"), ("porte_id", "str"), ("noeud", "int"),
               ("libelle", "str"), ("x", "float"), ("y", "float")],
    "distribution": [("scenario", "str"), ("portee", "str"), ("porte_id", "str"),
                     ("part_emis", "float"), ("part_attire", "float")],
    "trafic_ref": [("tid", "int"), ("hpm_ab", "float"), ("hpm_ba", "float"),
                   ("hps_ab", "float"), ("hps_ba", "float")],
    "journal_reseau": [("variante", "str"), ("date", "str"), ("tid", "int"),
                       ("action", "str"), ("detail", "str")],
    "res_generation": [("lot_id", "str"), ("typologie", "str"), ("source", "str"),
                       ("quantite", "float"), ("veh_jour", "float"),
                       ("hpm_emis", "float"), ("hpm_attire", "float"),
                       ("hps_emis", "float"), ("hps_attire", "float")],
    "res_synthese": [("periode", "str"), ("flux_emis", "float"), ("flux_attire", "float"),
                     ("veh_km", "float"), ("nb_arcs", "int"), ("delta_max", "float"),
                     ("arc_delta_max", "str"), ("hausse_max_pct", "float"),
                     ("arc_hausse_max", "str")],
    "res_journal": [("lot_id", "str"), ("typologie", "str"), ("sens", "str"),
                    ("periode", "str"), ("acces", "str"), ("porte", "str"),
                    ("flux", "float"), ("temps_s", "float"), ("chemin", "str")],
}

# Tables rattachées à un scénario (supprimées avec lui)
TABLES_SCENARIO = ("programme", "flux_directs", "acces", "portes", "distribution")

RATIOS_DEFAUT = [
    dict(typologie="logement", unite="logement", diviseur=1, dep_jour=4.0, part_vp=0.45,
         occupation=1.10, hpm_emis=0.10, hpm_attire=0.03, hps_emis=0.05, hps_attire=0.09),
    dict(typologie="bureaux", unite="m2 SDP", diviseur=100, dep_jour=12.0, part_vp=0.30,
         occupation=1.10, hpm_emis=0.02, hpm_attire=0.22, hps_emis=0.20, hps_attire=0.03),
    dict(typologie="commerce", unite="m2 SDP", diviseur=100, dep_jour=25.0, part_vp=0.50,
         occupation=1.40, hpm_emis=0.02, hpm_attire=0.02, hps_emis=0.06, hps_attire=0.06),
    dict(typologie="equipement", unite="m2 SDP", diviseur=100, dep_jour=20.0, part_vp=0.35,
         occupation=1.20, hpm_emis=0.05, hpm_attire=0.10, hps_emis=0.05, hps_attire=0.05),
]
