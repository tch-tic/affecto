"""Onglet 4 : portes d'accès du bassin versant et distribution des flux."""
from collections import defaultdict

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .tableau import Colonne, TableauEditable


class OngletDistribution(QScrollArea):
    def __init__(self, ctx, onglet_programme):
        super().__init__()
        self.ctx = ctx
        self.prog = onglet_programme
        self._charge = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self.enregistrer)

        page = QWidget()
        lay = QVBoxLayout(page)

        g = QGroupBox("Portes d'accès (origines / destinations des flux)")
        v = QVBoxLayout(g)
        aide = QLabel("Une porte est un <b>nœud</b> du réseau par lequel les flux du projet entrent "
                      "ou sortent du secteur (bordure de l'étude).")
        aide.setWordWrap(True)
        aide.setTextFormat(Qt.RichText)
        v.addWidget(aide)
        self.t_portes = TableauEditable([
            Colonne("porte_id", "Porte"),
            Colonne("libelle", "Libellé"),
            Colonne("noeud", "Nœud", "int", editable=False),
            Colonne("x", "x", "float", cache=True), Colonne("y", "y", "float", cache=True),
        ], hauteur_min=110)
        b1 = QPushButton("Ajouter une porte (clic sur la carte)")
        b1.clicked.connect(lambda: self._placer_porte(None))
        b2 = QPushButton("Déplacer la ligne sélectionnée")
        b2.clicked.connect(self._deplacer_porte)
        self.t_portes.barre.addWidget(b1)
        self.t_portes.barre.addWidget(b2)
        v.addWidget(self.t_portes)
        lay.addWidget(g)

        g = QGroupBox("Distribution des flux par porte (%)")
        v = QVBoxLayout(g)
        aide = QLabel(
            "<b>defaut</b> s'applique à tous les lots. Une ligne de portée <b>B</b> (lot) ou "
            "<b>B|bureaux</b> (lot|typologie) remplace la distribution par défaut pour ce lot ou "
            "cette typologie. Les parts sont normalisées à 100 % pour chaque portée.")
        aide.setWordWrap(True)
        aide.setTextFormat(Qt.RichText)
        v.addWidget(aide)
        self.t_dist = TableauEditable([
            Colonne("portee", "Portée", "choix", self._portees, libre=True),
            Colonne("porte_id", "Porte", "choix", self._portes),
            Colonne("part_emis", "Émis (%)", "float", aide="Part des flux émis par le projet vers cette porte"),
            Colonne("part_attire", "Attiré (%)", "float", aide="Part des flux attirés venant de cette porte"),
        ], hauteur_min=180)
        b3 = QPushButton("Répartir également (défaut)")
        b3.clicked.connect(self._repartir_egal)
        self.t_dist.barre.addWidget(b3)
        v.addWidget(self.t_dist)
        self.lbl_verif = QLabel("")
        self.lbl_verif.setWordWrap(True)
        self.lbl_verif.setTextFormat(Qt.RichText)
        v.addWidget(self.lbl_verif)
        lay.addWidget(g)
        lay.addStretch()

        self.setWidgetResizable(True)
        self.setWidget(page)
        self.t_portes.modifie.connect(self._planifier)
        self.t_portes.modifie.connect(lambda: self.t_dist.rafraichir_choix() if not self._charge else None)
        self.t_dist.modifie.connect(self._planifier)
        self.t_dist.modifie.connect(self._verifier)

    # -- listes ----------------------------------------------------------------------
    def _portes(self):
        return [l["porte_id"] for l in self.t_portes.lignes() if l["porte_id"]]

    def _portees(self):
        out = ["defaut"] + self.prog.lots_connus()
        for l in self.t_dist.lignes():
            if l["portee"] and l["portee"] not in out:
                out.append(l["portee"])
        return out

    # -- chargement / enregistrement ---------------------------------------------------------
    def charger(self):
        self._charge = True
        try:
            projet = self.ctx.projet()
            nom = self.ctx.nom_scenario()
            if projet is None or not nom:
                self.t_portes.definir_lignes([])
                self.t_dist.definir_lignes([])
                return
            self.t_portes.definir_lignes(
                [l for l in projet.lire_lignes("portes") if l.get("scenario") == nom])
            self.t_dist.definir_lignes(
                [l for l in projet.lire_lignes("distribution") if l.get("scenario") == nom])
        finally:
            self._charge = False
        self._verifier()

    def _planifier(self):
        if not self._charge:
            self._timer.start()

    def enregistrer(self):
        if self._charge:
            return
        projet, nom = self.ctx.projet(), self.ctx.nom_scenario()
        if projet is None or not nom:
            return
        try:
            crs = self.ctx.crs_reseau()
            projet.remplacer_lignes_scenario(
                "portes", nom, [l for l in self.t_portes.lignes() if l["porte_id"]], crs)
            projet.remplacer_lignes_scenario(
                "distribution", nom,
                [l for l in self.t_dist.lignes() if l["portee"] and l["porte_id"]], crs)
            self.ctx.recharger_points()
        except Exception as exc:
            self.ctx.msg(f"Enregistrement impossible : {exc}", "Critical")

    # -- portes -------------------------------------------------------------------------
    def _placer_porte(self, ligne):
        if not self.ctx.nom_scenario():
            self.ctx.msg("Créer ou choisir d'abord un scénario.", "Warning")
            return

        def pose(r):
            if ligne is None:
                n = self.t_portes.tbl.rowCount() + 1
                self.t_portes.ajouter_ligne({
                    "porte_id": f"P{n}", "libelle": f"Porte {n}", "noeud": r["id"],
                    "x": r["x"], "y": r["y"]}, emettre=False)
            else:
                self.t_portes.definir_valeur(ligne, "noeud", r["id"])
                self.t_portes.definir_valeur(ligne, "x", r["x"])
                self.t_portes.definir_valeur(ligne, "y", r["y"])
            self.enregistrer()
            self.t_dist.rafraichir_choix()
            self.ctx.msg(f"Porte placée sur le nœud {r['id']} (à {r['dist']:.0f} m du clic).")

        self.ctx.choisir_sur_carte("noeud", pose)

    def _deplacer_porte(self):
        ligne = self.t_portes.ligne_selectionnee()
        if ligne is None:
            self.ctx.msg("Sélectionner d'abord une ligne de porte.", "Warning")
            return
        self._placer_porte(ligne)

    # -- distribution -----------------------------------------------------------------------
    def _repartir_egal(self):
        portes = self._portes()
        if not portes:
            self.ctx.msg("Définir d'abord des portes.", "Warning")
            return
        gardees = [l for l in self.t_dist.lignes() if l["portee"] != "defaut"]
        part = round(100.0 / len(portes), 2)
        neuves = [{"portee": "defaut", "porte_id": p, "part_emis": part, "part_attire": part}
                  for p in portes]
        self.t_dist.definir_lignes(neuves + gardees)
        self._planifier()
        self._verifier()

    def _verifier(self):
        sommes = defaultdict(lambda: [0.0, 0.0])
        for l in self.t_dist.lignes():
            if l["portee"]:
                sommes[l["portee"]][0] += l["part_emis"] or 0
                sommes[l["portee"]][1] += l["part_attire"] or 0
        if not sommes:
            self.lbl_verif.setText("<i>Aucune distribution définie.</i>")
            return
        morceaux = []
        for portee, (e, a) in sommes.items():
            ok = abs(e - 100) < 0.5 and abs(a - 100) < 0.5
            couleur = "#2e7d32" if ok else "#c0392b"
            morceaux.append(f"<span style='color:{couleur}'><b>{portee}</b> : émis {e:.0f} % · "
                            f"attiré {a:.0f} %{'' if ok else ' (sera normalisé à 100 %)'}</span>")
        defaut = "defaut" in sommes
        if not defaut:
            morceaux.append("<span style='color:#c0392b'>Ajouter une portée « defaut ».</span>")
        self.lbl_verif.setText("<br>".join(morceaux))
