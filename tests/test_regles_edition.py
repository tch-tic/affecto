import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import regles_edition as r  # noqa: E402

NOEUDS = {1: (0.0, 0.0), 2: (100.0, 0.0), 3: (100.0, 100.0)}
TRONCONS = {10: {"coords": [(0.0, 0.0), (100.0, 0.0)]},
            11: {"coords": [(100.0, 0.0), (100.0, 100.0)]}}


class TestRegles(unittest.TestCase):
    def test_sens(self):
        self.assertEqual((r.sens_inverse(1), r.sens_inverse(-1), r.sens_inverse(0)), (-1, 1, 0))
        self.assertEqual((r.sens_bascule(0), r.sens_bascule(1), r.sens_bascule(-1)), (1, 0, 0))

    def test_prochain_id(self):
        self.assertEqual(r.prochain_id([3, 9, 4]), 10)
        self.assertEqual(r.prochain_id([]), 1)
        self.assertEqual(r.prochain_id([5], plancher=100), 101)

    def test_accrochage_noeud_puis_tronçon_puis_libre(self):
        self.assertEqual(r.planifier_extremite((3, 2), NOEUDS, TRONCONS, 10)["id"], 1)
        e = r.planifier_extremite((50, 4), NOEUDS, TRONCONS, 10)
        self.assertEqual((e["type"], e["tid"], e["point"]), ("coupe", 10, (50.0, 0.0)))
        self.assertEqual(e["avant"][-1], (50.0, 0.0))
        self.assertEqual(e["apres"][0], (50.0, 0.0))
        self.assertEqual(r.planifier_extremite((50, 50), NOEUDS, TRONCONS, 10)["type"], "nouveau")

    def test_creation_entre_noeud_et_milieu_de_troncon(self):
        # (100, 52) tombe sur le tronçon 11 (x = 100) : il sera coupé en (100, 52)
        plan = r.planifier_creation([(1, 1), (40, 60), (100, 52)], NOEUDS, TRONCONS, 10)
        self.assertEqual(plan["debut"], {"type": "noeud", "id": 1, "point": (0.0, 0.0)})
        self.assertEqual((plan["fin"]["type"], plan["fin"]["tid"]), ("coupe", 11))
        self.assertEqual(plan["coords"][0], (0.0, 0.0))
        self.assertEqual(plan["coords"][-1], (100.0, 52.0))
        # loin de tout : nouveau nœud libre
        plan = r.planifier_creation([(0, 0), (50, 50), (60, 60)], NOEUDS, TRONCONS, 10)
        self.assertEqual(plan["fin"]["type"], "nouveau")
        self.assertEqual(plan["coords"][-1], (60, 60))
        # extrémité proche d'un nœud existant : on s'y accroche
        plan = r.planifier_creation([(0, 0), (50, 50), (97, 104)], NOEUDS, TRONCONS, 10)
        self.assertEqual(plan["fin"], {"type": "noeud", "id": 3, "point": (100.0, 100.0)})

    def test_refus(self):
        with self.assertRaises(ValueError):
            r.planifier_creation([(0, 0)], NOEUDS, TRONCONS, 10)
        with self.assertRaises(ValueError):  # même tronçon aux deux bouts
            r.planifier_creation([(30, 2), (70, 3)], NOEUDS, TRONCONS, 10)
        with self.assertRaises(ValueError):  # boucle sans point intermédiaire
            r.planifier_creation([(1, 1), (2, 2)], NOEUDS, TRONCONS, 10)
        with self.assertRaises(ValueError):  # trop court
            r.planifier_creation([(500, 500), (500.2, 500)], NOEUDS, TRONCONS, 10)


if __name__ == "__main__":
    unittest.main()
