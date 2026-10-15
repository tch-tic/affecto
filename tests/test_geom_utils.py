import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import geom_utils as g  # noqa: E402


class TestGeom(unittest.TestCase):
    def test_longueur_et_projection(self):
        ligne = [(0, 0), (100, 0), (100, 50)]
        self.assertAlmostEqual(g.longueur(ligne), 150)
        d, s, c = g.projeter(ligne, (40, 10))
        self.assertAlmostEqual(d, 10)
        self.assertAlmostEqual(s, 40)
        self.assertEqual(c, (40.0, 0.0))
        d, s, c = g.projeter(ligne, (120, 30))
        self.assertAlmostEqual(d, 20)
        self.assertAlmostEqual(s, 130)

    def test_decoupe_milieu_de_segment(self):
        avant, apres, c = g.decouper([(0, 0), (100, 0), (100, 50)], 40)
        self.assertEqual(avant, [(0, 0), (40.0, 0.0)])
        self.assertEqual(apres, [(40.0, 0.0), (100, 0), (100, 50)])
        self.assertEqual(c, (40.0, 0.0))
        self.assertAlmostEqual(g.longueur(avant) + g.longueur(apres), 150)

    def test_decoupe_sur_un_sommet_sans_doublon(self):
        avant, apres, c = g.decouper([(0, 0), (100, 0), (100, 50)], 100)
        self.assertEqual(avant, [(0, 0), (100, 0)])
        self.assertEqual(apres, [(100, 0), (100, 50)])

    def test_decoupe_hors_ligne(self):
        with self.assertRaises(ValueError):
            g.decouper([(0, 0), (10, 0)], 10)
        with self.assertRaises(ValueError):
            g.decouper([(0, 0), (10, 0)], 50)


if __name__ == "__main__":
    unittest.main()
