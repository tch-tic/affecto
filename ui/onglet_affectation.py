"""Onglet 5 : lancement de l'affectation, affichage des charges et bilan."""
import csv

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import donnees, engine, styles
from .contexte import GROUPE_RESULTATS, ROLE, groupe, retirer_couches


class OngletAffectation(QScrollArea):
    def __init__(self, ctx, onglet_programme, onglet_distribution):
        super().__init__()
        self.ctx = ctx
        self.prog = onglet_programme
        self.dist = onglet_distribution
        self._resultat = None

        page = QWidget()
        lay = QVBoxLayout(page)

        g = QGroupBox("Scénario")
        v = QVBoxLayout(g)
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setTextFormat(Qt.RichText)
        v.addWidget(self.lbl_info)
        self.btn_ref = QPushButton("Générer un trafic de référence fictif (test)")
        self.btn_ref.setToolTip("Crée des charges de référence par sens, calées sur les ordres de "
                                "grandeur d'une carte de charges HPM. À remplacer par les comptages.")
        self.btn_ref.clicked.connect(self._ref_fictif)
        v.addWidget(self.btn_ref)
        lay.addWidget(g)

        g = QGroupBox("Affectation")
        v = QVBoxLayout(g)
        self.btn_run = QPushButton("Lancer l'affectation")
        self.btn_run.clicked.connect(self.lancer)
        v.addWidget(self.btn_run)
        self.lbl_avert = QLabel("")
        self.lbl_avert.setWordWrap(True)
        self.lbl_avert.setTextFormat(Qt.RichText)
        v.addWidget(self.lbl_avert)
        lay.addWidget(g)

        g = QGroupBox("Affichage sur la carte")
        v = QVBoxLayout(g)
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Période :"))
        self.rb_hpm = QRadioButton("HPM")
        self.rb_hps = QRadioButton("HPS")
        self.rb_hpm.setChecked(True)
        ligne.addWidget(self.rb_hpm)
        ligne.addWidget(self.rb_hps)
        ligne.addStretch()
        v.addLayout(ligne)
        self.rb_vals = {}
        for cle, (_s, lib, *_r) in styles.VALEURS_RESULTATS.items():
            rb = QRadioButton(lib)
            self.rb_vals[cle] = rb
            v.addWidget(rb)
        self.rb_vals["tot"].setChecked(True)
        for rb in (self.rb_hpm, self.rb_hps, *self.rb_vals.values()):
            rb.toggled.connect(self._restyler)
        self.btn_aff = QPushButton("Afficher / actualiser la carte")
        self.btn_aff.clicked.connect(self.afficher)
        v.addWidget(self.btn_aff)
        lay.addWidget(g)

        g = QGroupBox("Bilan")
        v = QVBoxLayout(g)
        self.t_syn = QTableWidget(0, 3)
        self.t_syn.setHorizontalHeaderLabels(["Indicateur", "HPM", "HPS"])
        self.t_syn.verticalHeader().hide()
        self.t_syn.setEditTriggers(QTableWidget.NoEditTriggers)
        self.t_syn.setMinimumHeight(230)
        v.addWidget(self.t_syn)
        v.addWidget(QLabel("<b>10 tronçons les plus chargés par le projet</b>"))
        self.t_top = QTableWidget(0, 5)
        self.t_top.setHorizontalHeaderLabels(["Voie", "Arc", "HPM proj.", "HPS proj.", "HPM +%"])
        self.t_top.verticalHeader().hide()
        self.t_top.setEditTriggers(QTableWidget.NoEditTriggers)
        self.t_top.setMinimumHeight(250)
        v.addWidget(self.t_top)
        self.btn_exp = QPushButton("Exporter le bilan (CSV)…")
        self.btn_exp.clicked.connect(self._exporter)
        v.addWidget(self.btn_exp)
        lay.addWidget(g)
        lay.addStretch()

        self.setWidgetResizable(True)
        self.setWidget(page)

    # -- état ---------------------------------------------------------------------------
    def charger(self):
        sc = self.ctx.scenario
        projet = self.ctx.projet()
        if not sc or projet is None:
            self.lbl_info.setText("Aucun scénario sélectionné.")
            return
        ref = projet.lire_lignes(f"trafic_ref__{sc['variante']}")
        etat_ref = (f"{len(ref)} tronçons" if ref else "<span style='color:#c0392b'>absent</span>")
        self.lbl_info.setText(f"Scénario : <b>{sc['libelle']}</b> · réseau : <b>{sc['variante']}</b>"
                              f" · trafic de référence : {etat_ref}")
        self._resultat = None
        self.t_syn.setRowCount(0)
        self.t_top.setRowCount(0)
        self.lbl_avert.setText("")
        # résultats déjà calculés ?
        synth = projet.lire_lignes(f"res_synthese__{sc['nom']}")
        if synth:
            self._remplir_bilan(synth, None)

    def _ref_fictif(self):
        projet = self.ctx.projet()
        if projet is None or not self.ctx.scenario:
            self.ctx.msg("Choisir d'abord un scénario.", "Warning")
            return
        v = self.ctx.variante()
        if projet.table_existe(f"trafic_ref__{v}") and QMessageBox.question(
                self, "Trafic de référence",
                "Un trafic de référence existe déjà pour ce réseau. L'écraser par des valeurs "
                "fictives ?") != QMessageBox.Yes:
            return
        reseau = self.ctx.reseau()
        if reseau is None:
            return
        n = donnees.ecrire_ref_fictif(projet, v, reseau)
        self.ctx.msg(f"Trafic de référence fictif écrit pour {n} tronçons.")
        self.charger()

    # -- calcul ---------------------------------------------------------------------------
    def lancer(self):
        projet, sc = self.ctx.projet(), self.ctx.scenario
        if projet is None or not sc:
            self.ctx.msg("Choisir d'abord un scénario.", "Warning")
            return
        self.prog.enregistrer()
        self.dist.enregistrer()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = donnees.lancer_scenario(projet, sc)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self.lbl_avert.setText(f"<span style='color:#c0392b'><b>Échec :</b> {exc}</span>")
            self.ctx.msg(f"Affectation impossible : {exc}", "Critical")
            return
        QApplication.restoreOverrideCursor()
        self._resultat = res
        self.prog.afficher_flux(res["generation"])
        avert = res["avertissements"]
        self.lbl_avert.setText("<br>".join(f"⚠ {a}" for a in avert) if avert
                               else "<span style='color:#2e7d32'>Affectation terminée sans avertissement.</span>")
        self._remplir_bilan(res["synthese"], res["arcs"])
        self.afficher()

    def _remplir_bilan(self, synth, arcs):
        lignes = [
            ("Flux émis (véh/h)", "flux_emis", "{:.0f}"), ("Flux attirés (véh/h)", "flux_attire", "{:.0f}"),
            ("Véh·km ajoutés", "veh_km", "{:.0f}"), ("Arcs impactés", "nb_arcs", "{:.0f}"),
            ("Ajout max sur un arc (véh/h)", "delta_max", "{:.0f}"), ("… sur", "arc_delta_max", "{}"),
            ("Hausse max (%) (réf. ≥ 50)", "hausse_max_pct", "{:.1f}"), ("… sur", "arc_hausse_max", "{}"),
        ]
        par = {s["periode"]: s for s in synth}
        self.t_syn.setRowCount(len(lignes))
        for i, (lib, cle, fmt) in enumerate(lignes):
            self.t_syn.setItem(i, 0, QTableWidgetItem(lib))
            for j, p in enumerate(("HPM", "HPS"), 1):
                v = par.get(p, {}).get(cle)
                self.t_syn.setItem(i, j, QTableWidgetItem("" if v is None else fmt.format(v)))
        self.t_syn.resizeColumnsToContents()
        if arcs is None:
            projet, sc = self.ctx.projet(), self.ctx.scenario
            arcs = projet.lire_lignes(f"res_arcs__{sc['nom']}")
        top = sorted(arcs, key=lambda r: -(r["hpm_proj"] or 0) - (r["hps_proj"] or 0))[:10]
        self.t_top.setRowCount(len(top))
        for i, r in enumerate(top):
            vals = [r["nom"] or "(sans nom)", engine.nom_arc((r["tid"], r["dir"])),
                    f"{r['hpm_proj']:.0f}", f"{r['hps_proj']:.0f}",
                    "" if r["hpm_pct"] is None else f"{r['hpm_pct']:.1f}"]
            for j, t in enumerate(vals):
                self.t_top.setItem(i, j, QTableWidgetItem(t))
        self.t_top.resizeColumnsToContents()

    # -- carte ---------------------------------------------------------------------------
    def _selection(self):
        periode = "hps" if self.rb_hps.isChecked() else "hpm"
        valeur = next(k for k, rb in self.rb_vals.items() if rb.isChecked())
        return periode, valeur

    def afficher(self):
        projet, sc = self.ctx.projet(), self.ctx.scenario
        if projet is None or not sc:
            return
        lyr = projet.couche(f"res_arcs__{sc['nom']}")
        if lyr is None:
            self.ctx.msg("Pas encore de résultats : lancer l'affectation.", "Warning")
            return
        retirer_couches(("resultats",))
        lyr.setName(f"Charges – {sc['libelle']}")
        lyr.setCustomProperty(ROLE, "resultats")
        QgsProject.instance().addMapLayer(lyr, False)
        groupe(GROUPE_RESULTATS).insertLayer(0, lyr)
        self._restyler()
        self.ctx.canvas.setExtent(self.ctx.canvas.mapSettings().layerExtentToOutputExtent(
            lyr, lyr.extent()))
        self.ctx.canvas.refresh()

    def _restyler(self, *_):
        periode, valeur = self._selection()
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.customProperty(ROLE) == "resultats":
                styles.style_resultats(lyr, periode, valeur)

    # -- export ---------------------------------------------------------------------------
    def _exporter(self):
        projet, sc = self.ctx.projet(), self.ctx.scenario
        if projet is None or not sc:
            return
        dossier = QFileDialog.getExistingDirectory(self, "Dossier d'export du bilan")
        if not dossier:
            return
        n = 0
        for table in ("synthese", "generation", "journal"):
            lignes = projet.lire_lignes(f"res_{table}__{sc['nom']}")
            if not lignes:
                continue
            chemin = f"{dossier}/{sc['nom']}_{table}.csv"
            with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(lignes[0]), delimiter=";")
                w.writeheader()
                w.writerows(lignes)
            n += 1
        arcs = projet.lire_lignes(f"res_arcs__{sc['nom']}")
        if arcs:
            with open(f"{dossier}/{sc['nom']}_arcs.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(arcs[0]), delimiter=";")
                w.writeheader()
                w.writerows(arcs)
            n += 1
        vir = projet.lire_lignes(f"res_virages__{sc['nom']}")
        if vir:
            with open(f"{dossier}/{sc['nom']}_virages.csv", "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(vir[0]), delimiter=";")
                w.writeheader()
                w.writerows(vir)
            n += 1
        self.ctx.msg(f"{n} fichiers CSV exportés dans {dossier}.")
