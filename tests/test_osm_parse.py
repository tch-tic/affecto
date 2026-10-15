import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import osm_parse as op  # noqa: E402


def way(wid, nodes, tags):
    return {"type": "way", "id": wid, "nodes": nodes, "tags": tags,
            "geometry": [{"lat": 48.0 + n * 1e-4, "lon": 2.0 + n * 1e-4} for n in nodes]}


class TestOsmParse(unittest.TestCase):
    def test_sens(self):
        self.assertEqual(op.sens_osm({"oneway": "yes"}), 1)
        self.assertEqual(op.sens_osm({"oneway": "-1"}), -1)
        self.assertEqual(op.sens_osm({"oneway": "no", "junction": "roundabout"}), 0)
        self.assertEqual(op.sens_osm({"junction": "roundabout"}), 1)
        self.assertEqual(op.sens_osm({"highway": "motorway"}), 1)
        self.assertEqual(op.sens_osm({"highway": "residential"}), 0)

    def test_vitesse(self):
        self.assertEqual(op.vitesse_osm({"maxspeed": "30"}), 30)
        self.assertEqual(op.vitesse_osm({"maxspeed": "30 mph"}), 48)
        self.assertEqual(op.vitesse_osm({"maxspeed": "FR:urban"}), 50)
        self.assertEqual(op.vitesse_osm({"highway": "living_street"}), 20)
        self.assertEqual(op.vitesse_osm({}), 50)

    def test_vitesse_disponible_ou_non(self):
        self.assertEqual(op.vitesse_tag({"maxspeed": "30"}), 30)
        self.assertIsNone(op.vitesse_tag({"highway": "residential"}))
        self.assertIsNone(op.vitesse_tag({"maxspeed": "signals"}))
        self.assertEqual(op.vitesse_osm({"maxspeed": "signals", "highway": "living_street"}), 20)

    def test_rond_point_ouvrage_niveau(self):
        self.assertEqual(op.rond_point_osm({"junction": "roundabout"}), 1)
        self.assertEqual(op.rond_point_osm({"highway": "primary"}), 0)
        self.assertEqual(op.ouvrage_osm({"bridge": "yes"}), "pont")
        self.assertEqual(op.ouvrage_osm({"bridge": "viaduct"}), "pont")
        self.assertEqual(op.ouvrage_osm({"tunnel": "yes"}), "tunnel")
        self.assertEqual(op.ouvrage_osm({"tunnel": "no", "bridge": "no"}), "")
        self.assertEqual(op.niveau_osm({"layer": "-1"}), -1)
        self.assertEqual(op.niveau_osm({"layer": "x"}), 0)

    def test_champs_des_troncons(self):
        elements = [
            way(20, [1, 2, 3], {"highway": "primary", "maxspeed": "50", "lanes": "2",
                                "bridge": "yes", "layer": "1"}),
            way(21, [3, 4, 5, 3], {"highway": "secondary", "junction": "roundabout"}),
        ]
        a, b = op.decouper(elements)
        self.assertEqual((a["vit_osm"], a["vitesse"], a["voies"]), (50, 50, 2))
        self.assertEqual((a["ouvrage"], a["niveau"], a["rond_point"]), ("pont", 1, 0))
        self.assertIsNone(b["vit_osm"])
        self.assertEqual((b["rond_point"], b["sens"], b["vitesse"]), (1, 1, 50))

    def test_decoupage_aux_intersections(self):
        # A traverse de 1 à 5 ; B démarre au nœud 3 : A est coupée en 3
        elements = [
            way(10, [1, 2, 3, 4, 5], {"highway": "primary", "name": "Rue A"}),
            way(11, [3, 6, 7], {"highway": "residential", "oneway": "yes"}),
        ]
        segs = op.decouper(elements)
        a = [s for s in segs if s["osm_id"] == 10]
        self.assertEqual([(s["u"], s["v"]) for s in a], [(1, 3), (3, 5)])
        self.assertEqual(len(a[0]["coords"]), 3)
        b = [s for s in segs if s["osm_id"] == 11]
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["sens"], 1)
        self.assertEqual([s["id"] for s in segs], [1, 2, 3])

    def test_voies_invalides_ignorees(self):
        cassee = {"type": "way", "id": 1, "nodes": [1, 2], "geometry": [], "tags": {}}
        self.assertEqual(op.decouper([cassee, {"type": "node", "id": 2}]), [])

    def test_requete(self):
        anneau = [(2.0, 48.0), (2.1, 48.0), (2.1, 48.1), (2.0, 48.0)]
        q = op.requete_overpass(anneau, "structurant")
        self.assertIn('poly:"48.000000 2.000000 48.000000 2.100000', q)
        self.assertIn("primary", q)
        self.assertNotIn("residential", q)
        self.assertIn("service", op.requete_overpass(anneau, "complet"))
        with self.assertRaises(ValueError):
            op.requete_overpass(anneau[:2])


class TestReponseOverpass(unittest.TestCase):
    def test_reponses(self):
        self.assertEqual(op.verifier_reponse({"elements": []}), (True, ""))
        ok, msg = op.verifier_reponse({"elements": [{}], "remark": "runtime error: Query timed out"})
        self.assertFalse(ok)
        self.assertIn("timed out", msg)
        self.assertFalse(op.verifier_reponse({"remark": "overloaded"})[0])
        self.assertFalse(op.verifier_reponse([])[0])
        self.assertIn("maxsize", op.requete_overpass(
            [(2.0, 48.0), (2.1, 48.0), (2.1, 48.1), (2.0, 48.0)]))


if __name__ == "__main__":
    unittest.main()
