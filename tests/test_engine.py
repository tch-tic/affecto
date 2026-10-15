import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
import engine as e  # noqa: E402
from defauts import RATIOS_DEFAUT  # noqa: E402


def grille(sens_speciaux=None):
    """Grille 3x3 (nœuds 1..9), tronçons de 100 m ; tid = rang de création."""
    sens_speciaux = sens_speciaux or {}
    segs, tid = [], 1
    for r in range(3):
        for c in range(3):
            n = r * 3 + c + 1
            for v in ([n + 1] if c < 2 else []) + ([n + 3] if r < 2 else []):
                segs.append({"tid": tid, "a": n, "b": v, "longueur": 100.0, "vitesse": 30,
                             "sens": sens_speciaux.get(tid, 0), "highway": "residential",
                             "nom": f"rue{tid}"})
                tid += 1
    return segs


def dist(*lignes):
    return [{"portee": p, "porte_id": pid, "part_emis": a, "part_attire": b}
            for p, pid, a, b in lignes]


class TestEngine(unittest.TestCase):
    def test_generation(self):
        flux = e.generer_flux([{"lot_id": "A", "typologie": "logement", "quantite": 100}],
                              RATIOS_DEFAUT)
        # 100 * 4 * 0.45 / 1.10 = 163.6 véh/j ; HPM émis = 10 %
        self.assertAlmostEqual(flux[0]["veh_jour"], 163.636, places=2)
        self.assertAlmostEqual(flux[0]["hpm_emis"], 16.364, places=2)
        directs = [{"lot_id": "A", "typologie": "logement", "hpm_emis": 7, "hpm_attire": 1,
                    "hps_emis": 2, "hps_attire": 3}]
        f2 = e.generer_flux([{"lot_id": "A", "typologie": "logement", "quantite": 100}],
                            RATIOS_DEFAUT, directs)
        self.assertEqual((f2[0]["hpm_emis"], f2[0]["source"]), (7.0, "direct"))
        with self.assertRaises(ValueError):
            e.generer_flux([{"lot_id": "A", "typologie": "zoo", "quantite": 1}], RATIOS_DEFAUT)

    def test_priorite_distribution(self):
        d = dist(("defaut", "P1", 60, 50), ("defaut", "P2", 40, 50),
                 ("A", "P2", 100, 100), ("A|bureaux", "P1", 100, 100))
        av = []
        self.assertEqual(e.parts_distribution(d, "B", "x", "emis", av), {"P1": 0.6, "P2": 0.4})
        self.assertEqual(e.parts_distribution(d, "A", "logement", "emis", av), {"P2": 1.0})
        self.assertEqual(e.parts_distribution(d, "A", "bureaux", "attire", av), {"P1": 1.0})

    def test_sens_unique_et_demi_tour(self):
        g = e.Graphe(grille({1: 1}))  # tronçon 1 : 1 -> 2 seulement
        self.assertEqual([a[0] for a in g.chemin(("noeud", 1), ("noeud", 2))], [1])
        retour = [a[0] for a in g.chemin(("noeud", 2), ("noeud", 1))]
        self.assertNotIn(1, retour)
        self.assertGreater(len(retour), 1)
        # jamais deux fois de suite le même tronçon (pas de demi-tour)
        for o, d in ((1, 9), (9, 1), (3, 7), (5, 1)):
            ch = g.chemin(("noeud", o), ("noeud", d))
            self.assertTrue(all(x[0] != y[0] for x, y in zip(ch[:-1], ch[1:])))

    def test_interdiction(self):
        segs = grille()
        base = e.Graphe(segs).chemin(("noeud", 1), ("noeud", 5))
        a, b = base[0], base[1]
        alt = e.Graphe(segs, interdictions={(a, b)}).chemin(("noeud", 1), ("noeud", 5))
        self.assertNotEqual(base, alt)

    def test_acces_sur_troncon(self):
        g = e.Graphe(grille())
        ch = g.chemin(("troncon", 1), ("noeud", 9))
        self.assertIsNotNone(ch)
        self.assertEqual(ch[0][0], 1)

    def test_conservation(self):
        g = e.Graphe(grille())
        flux = [{"lot_id": "A", "typologie": "t", "hpm_emis": 100.0, "hpm_attire": 0.0,
                 "hps_emis": 0.0, "hps_attire": 40.0}]
        acces = [{"lot_id": "A", "acces_id": "A1", "noeud": 5, "part": 60},
                 {"lot_id": "A", "acces_id": "A2", "noeud": 4, "part": 40}]
        d = dist(("defaut", "P1", 30, 50), ("defaut", "P2", 70, 50))
        f_arc, f_vir, journal, avert = e.affecter(g, flux, acces, {"P1": 1, "P2": 9}, d)
        entrant = {}
        for arc, q in f_arc["hpm"].items():
            v = g.arcs[arc]["v"]
            entrant[v] = entrant.get(v, 0) + q
        self.assertAlmostEqual(entrant[1] + entrant[9], 100.0, places=6)
        sortant = {}
        for arc, q in f_arc["hps"].items():
            u = g.arcs[arc]["u"]
            sortant[u] = sortant.get(u, 0) + q
        self.assertAlmostEqual(sortant[1] + sortant[9], 40.0, places=6)
        self.assertAlmostEqual(sum(j["flux"] for j in journal if j["periode"] == "HPM"), 100.0, 1)
        self.assertEqual(avert, [])

    def test_avertissements(self):
        g = e.Graphe(grille())
        flux = [{"lot_id": "Z", "typologie": "t", "hpm_emis": 10.0, "hpm_attire": 0.0,
                 "hps_emis": 0.0, "hps_attire": 0.0}]
        d = dist(("defaut", "P1", 1, 1))
        _, _, _, avert = e.affecter(g, flux, [], {"P1": 1}, d)
        self.assertTrue(any("aucun accès valide" in a for a in avert))

    def test_resultats_et_ref_fictif(self):
        segs = grille({1: 1})
        ref = e.trafic_ref_fictif(segs)
        self.assertEqual(ref[1]["hpm_ba"], 0.0)
        self.assertGreater(ref[1]["hpm_ab"], 0.0)
        self.assertEqual(ref, e.trafic_ref_fictif(segs))
        g = e.Graphe(segs)
        flux = [{"lot_id": "A", "typologie": "t", "hpm_emis": 50.0, "hpm_attire": 0.0,
                 "hps_emis": 0.0, "hps_attire": 0.0}]
        acces = [{"lot_id": "A", "acces_id": "A1", "noeud": 5, "part": 1}]
        f_arc, f_vir, journal, _ = e.affecter(g, flux, acces, {"P1": 1},
                                              dist(("defaut", "P1", 1, 1)))
        arcs = e.resultats_arcs(g, f_arc, ref)
        s = e.synthese(arcs, flux)
        self.assertEqual((s[0]["periode"], s[0]["flux_emis"]), ("HPM", 50.0))
        self.assertGreater(s[0]["nb_arcs"], 0)
        self.assertEqual(s[1]["veh_km"], 0.0)
        self.assertTrue(e.resultats_virages(g, f_vir, {}))


if __name__ == "__main__":
    unittest.main()
