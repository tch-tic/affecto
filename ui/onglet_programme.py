"""Onglet 3 : programmation des lots, ratios, accès au réseau, calcul des flux générés."""
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import engine
from ..core.defauts import RATIOS_DEFAUT, SCHEMAS
from .tableau import Colonne, TableauEditable


class OngletProgramme(QScrollArea):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._charge = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self.enregistrer)

        page = QWidget()
        lay = QVBoxLayout(page)

        # Ratios (communs à tous les scénarios du projet)
        g = QGroupBox("Typologies et ratios (communs au projet)")
        v = QVBoxLayout(g)
        v.addWidget(self._aide(
            "Déplacements/jour (personnes) par unité, part VP, occupation, puis part de ces "
            "véhicules émis/attirés en HPM et HPS (valeurs entre 0 et 1). "
            "<b>Valeurs par défaut indicatives</b> : à remplacer par celles de l'étude."))
        self.t_ratios = TableauEditable([
            Colonne("typologie", "Typologie"),
            Colonne("unite", "Unité"),
            Colonne("diviseur", "Par…", "float", aide="Quantité de référence (1 logement, 100 m²…)"),
            Colonne("dep_jour", "Dép./jour", "float", aide="Déplacements de personnes par jour et par unité"),
            Colonne("part_vp", "Part VP", "float"),
            Colonne("occupation", "Occup.", "float", aide="Personnes par véhicule"),
            Colonne("hpm_emis", "HPM émis", "float", aide="Part des véhicules/jour émis en HPM"),
            Colonne("hpm_attire", "HPM attiré", "float"),
            Colonne("hps_emis", "HPS émis", "float"),
            Colonne("hps_attire", "HPS attiré", "float"),
        ], hauteur_min=120)
        b = QPushButton("Rétablir les ratios par défaut")
        b.clicked.connect(self._ratios_defaut)
        self.t_ratios.barre.addWidget(b)
        v.addWidget(self.t_ratios)
        lay.addWidget(g)

        # Programmation
        g = QGroupBox("Programmation du scénario")
        v = QVBoxLayout(g)
        self.t_prog = TableauEditable([
            Colonne("lot_id", "Lot", libre=True, type="choix", choix=self._lots),
            Colonne("typologie", "Typologie", "choix", self._typologies),
            Colonne("quantite", "Quantité", "float", aide="Nombre de logements ou m² de surface de plancher"),
        ], hauteur_min=120)
        v.addWidget(self.t_prog)
        lay.addWidget(g)

        # Flux directs
        g = QGroupBox("Flux saisis directement (facultatif)")
        v = QVBoxLayout(g)
        v.addWidget(self._aide("Véh/h par lot et typologie. Ces valeurs <b>remplacent</b> le calcul "
                               "par ratios pour le même lot et la même typologie."))
        self.t_directs = TableauEditable([
            Colonne("lot_id", "Lot", "choix", self._lots, libre=True),
            Colonne("typologie", "Typologie", "choix", self._typologies, libre=True),
            Colonne("hpm_emis", "HPM émis", "float"), Colonne("hpm_attire", "HPM attiré", "float"),
            Colonne("hps_emis", "HPS émis", "float"), Colonne("hps_attire", "HPS attiré", "float"),
        ], hauteur_min=80)
        v.addWidget(self.t_directs)
        lay.addWidget(g)

        # Accès
        g = QGroupBox("Accès des lots au réseau")
        v = QVBoxLayout(g)
        v.addWidget(self._aide("Chaque accès est placé sur un <b>tronçon</b> du réseau du scénario. "
                               "Avec plusieurs accès pour un lot, la part (%) répartit ses flux."))
        self.t_acces = TableauEditable([
            Colonne("lot_id", "Lot", "choix", self._lots, libre=True),
            Colonne("acces_id", "Accès"),
            Colonne("troncon_id", "Tronçon", "int", editable=False),
            Colonne("part", "Part (%)", "float"),
            Colonne("x", "x", "float", cache=True), Colonne("y", "y", "float", cache=True),
            Colonne("noeud", "nœud", "int", cache=True),
        ], hauteur_min=100)
        b1 = QPushButton("Ajouter un accès (clic sur la carte)")
        b1.clicked.connect(lambda: self._placer_acces(None))
        b2 = QPushButton("Déplacer la ligne sélectionnée")
        b2.clicked.connect(self._deplacer_acces)
        self.t_acces.barre.addWidget(b1)
        self.t_acces.barre.addWidget(b2)
        v.addWidget(self.t_acces)
        lay.addWidget(g)

        # Flux générés
        g = QGroupBox("Flux générés (véh/h)")
        v = QVBoxLayout(g)
        ligne = QHBoxLayout()
        b = QPushButton("Calculer les flux")
        b.clicked.connect(self.calculer_flux)
        ligne.addWidget(b)
        ligne.addStretch()
        v.addLayout(ligne)
        self.t_flux = QTableWidget(0, 8)
        self.t_flux.setHorizontalHeaderLabels(
            ["Lot", "Typologie", "Source", "Véh/jour", "HPM émis", "HPM attiré", "HPS émis", "HPS attiré"])
        self.t_flux.verticalHeader().hide()
        self.t_flux.setMinimumHeight(140)
        self.t_flux.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.t_flux)
        self.lbl_flux = QLabel("")
        self.lbl_flux.setWordWrap(True)
        v.addWidget(self.lbl_flux)
        lay.addWidget(g)
        lay.addStretch()

        self.setWidgetResizable(True)
        self.setWidget(page)
        for t in (self.t_ratios, self.t_prog, self.t_directs, self.t_acces):
            t.modifie.connect(self._planifier)
        self.t_ratios.modifie.connect(self._rafraichir_listes)
        self.t_prog.modifie.connect(self._rafraichir_listes)

    @staticmethod
    def _aide(texte):
        lbl = QLabel(texte)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        return lbl

    # -- listes pour les cellules déroulantes -----------------------------------------
    def _typologies(self):
        return [l["typologie"] for l in self.t_ratios.lignes() if l["typologie"]]

    def _lots(self):
        vus = []
        for t in (self.t_prog, self.t_acces):
            for l in t.lignes():
                if l["lot_id"] and l["lot_id"] not in vus:
                    vus.append(l["lot_id"])
        return vus

    def _rafraichir_listes(self):
        if self._charge:
            return
        for t in (self.t_prog, self.t_directs):
            t.rafraichir_choix()

    def lots_connus(self):
        return self._lots()

    # -- chargement et enregistrement ------------------------------------------------------
    def charger(self):
        self._charge = True
        try:
            projet = self.ctx.projet()
            nom = self.ctx.nom_scenario()
            if projet is None:
                return
            ratios = projet.lire_lignes("ratios")
            if not ratios:
                ratios = [dict(r) for r in RATIOS_DEFAUT]
            self.t_ratios.definir_lignes(ratios)

            def du_scenario(table):
                return [l for l in projet.lire_lignes(table) if l.get("scenario") == nom] if nom else []
            self.t_prog.definir_lignes(du_scenario("programme"))
            self.t_directs.definir_lignes(du_scenario("flux_directs"))
            self.t_acces.definir_lignes(du_scenario("acces"))
            self.t_flux.setRowCount(0)
            self.lbl_flux.setText("")
        finally:
            self._charge = False

    def _planifier(self):
        if not self._charge:
            self._timer.start()

    def enregistrer(self):
        if self._charge:
            return
        projet = self.ctx.projet()
        if projet is None:
            return
        try:
            projet.ecrire_lignes("ratios", SCHEMAS["ratios"],
                                 [l for l in self.t_ratios.lignes() if l["typologie"]])
            nom = self.ctx.nom_scenario()
            if nom:
                crs = self.ctx.crs_reseau()
                projet.remplacer_lignes_scenario("programme", nom, [
                    l for l in self.t_prog.lignes() if l["lot_id"] and l["typologie"]], crs)
                projet.remplacer_lignes_scenario("flux_directs", nom, [
                    l for l in self.t_directs.lignes() if l["lot_id"] and l["typologie"]], crs)
                projet.remplacer_lignes_scenario("acces", nom, [
                    l for l in self.t_acces.lignes() if l["lot_id"]], crs)
                self.ctx.recharger_points()
        except Exception as exc:
            self.ctx.msg(f"Enregistrement impossible : {exc}", "Critical")

    def _ratios_defaut(self):
        self.t_ratios.definir_lignes([dict(r) for r in RATIOS_DEFAUT])
        self._planifier()
        self._rafraichir_listes()

    # -- accès -------------------------------------------------------------------------
    def _placer_acces(self, ligne):
        if not self.ctx.nom_scenario():
            self.ctx.msg("Créer ou choisir d'abord un scénario.", "Warning")
            return
        if ligne is None:
            lots = self._lots() or ["A"]
            lot, ok = QInputDialog.getItem(self, "Nouvel accès", "Lot (choisir ou saisir) :",
                                           lots, 0, True)
            if not ok or not lot.strip():
                return
            lot = lot.strip()
        else:
            lot = self.t_acces.valeur(ligne, "lot_id")

        def pose(r):
            if ligne is None:
                existants = [l for l in self.t_acces.lignes() if l["lot_id"] == lot]
                self.t_acces.ajouter_ligne({
                    "lot_id": lot, "acces_id": f"{lot}{len(existants) + 1}",
                    "troncon_id": r["id"], "part": 100.0, "x": r["x"], "y": r["y"]}, emettre=False)
                n = len(existants) + 1
                if n > 1:  # répartition égale par défaut
                    for i in range(self.t_acces.tbl.rowCount()):
                        if self.t_acces.valeur(i, "lot_id") == lot:
                            self.t_acces.definir_valeur(i, "part", round(100.0 / n, 1))
            else:
                self.t_acces.definir_valeur(ligne, "troncon_id", r["id"])
                self.t_acces.definir_valeur(ligne, "x", r["x"])
                self.t_acces.definir_valeur(ligne, "y", r["y"])
            self.enregistrer()
            self.ctx.msg(f"Accès placé sur le tronçon {r['id']} (à {r['dist']:.0f} m du clic).")

        self.ctx.choisir_sur_carte("troncon", pose)

    def _deplacer_acces(self):
        ligne = self.t_acces.ligne_selectionnee()
        if ligne is None:
            self.ctx.msg("Sélectionner d'abord une ligne d'accès.", "Warning")
            return
        self._placer_acces(ligne)

    # -- flux générés ---------------------------------------------------------------------
    def calculer_flux(self):
        try:
            flux = engine.generer_flux(
                [l for l in self.t_prog.lignes() if l["lot_id"] and l["typologie"]],
                [l for l in self.t_ratios.lignes() if l["typologie"]],
                [l for l in self.t_directs.lignes() if l["lot_id"] and l["typologie"]])
        except Exception as exc:
            self.lbl_flux.setText(f"<span style='color:#c0392b'>{exc}</span>")
            return None
        self.afficher_flux(flux)
        return flux

    def afficher_flux(self, flux):
        cles = ["hpm_emis", "hpm_attire", "hps_emis", "hps_attire"]
        self.t_flux.setRowCount(len(flux) + 1)
        for i, l in enumerate(flux):
            vals = [l["lot_id"], l["typologie"], l.get("source", ""), f"{l['veh_jour']:.0f}"] + \
                   [f"{l[c]:.1f}" for c in cles]
            for j, t in enumerate(vals):
                self.t_flux.setItem(i, j, QTableWidgetItem(t))
        tot = ["Total", "", "", f"{sum(l['veh_jour'] for l in flux):.0f}"] + \
              [f"{sum(l[c] for l in flux):.1f}" for c in cles]
        for j, t in enumerate(tot):
            it = QTableWidgetItem(t)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            self.t_flux.setItem(len(flux), j, it)
        self.t_flux.resizeColumnsToContents()
        self.lbl_flux.setText("Véh/jour : trafic VP total (émis + attiré) ; HPM/HPS en véh/h.")
