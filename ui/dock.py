"""Panneau principal : un onglet par étape. Seul l'onglet 1 est actif pour l'instant."""
from datetime import datetime

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMapLayerProxyModel,
    QgsProject,
)
from qgis.gui import QgsMapLayerComboBox, QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import styles
from ..core.store import PREFIX_NOEUDS, PREFIX_TRONCONS, ProjetGpkg, slugify
from ..core.tasks import TelechargementReseau
from .contexte import GROUPE, ROLE, VARIANTE, Contexte
from .map_tools import OutilPolygone
from .outils_reseau import BarreEditionReseau
from .onglet_affectation import OngletAffectation
from .onglet_distribution import OngletDistribution
from .onglet_programme import OngletProgramme

SEUIL_KM2 = 25.0  # au-delà, demander confirmation avant d'interroger Overpass


def _niveau(nom):
    return getattr(getattr(Qgis, "MessageLevel", Qgis), nom)


class AffectationDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("Affectation trafic", parent)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.geom_perimetre = None
        self.geom_zone = None
        self._task = None
        self._outil = None

        self.ctx = Contexte(iface, self._projet_silencieux, self._msg)
        self.o_prog = OngletProgramme(self.ctx)
        self.o_dist = OngletDistribution(self.ctx, self.o_prog)
        self.o_aff = OngletAffectation(self.ctx, self.o_prog, self.o_dist)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._onglet_reseau(), "1 Réseau")
        lbl = QLabel("<b>À venir</b><br>Import des comptages, mouvements tournants, mise à plat du "
                     "trafic de référence (HPM/HPS). En attendant, l'onglet 5 permet de générer un "
                     "trafic de référence fictif pour tester.")
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignTop)
        page = QWidget()
        QVBoxLayout(page).addWidget(lbl)
        i = self.tabs.addTab(page, "2 Trafic actuel")
        self.tabs.setTabEnabled(i, False)
        self.tabs.addTab(self.o_prog, "3 Programme")
        self.tabs.addTab(self.o_dist, "4 Distribution")
        self.tabs.addTab(self.o_aff, "5 Affectation")

        conteneur = QWidget()
        lay = QVBoxLayout(conteneur)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._barre_scenario())
        lay.addWidget(self.tabs)
        self.setWidget(conteneur)

    # ------------------------------------------------------------------ scénarios
    def _barre_scenario(self):
        """Sélecteur de scénario (commun aux onglets 3 à 5) et de sa variante de réseau."""
        barre = QWidget()
        grille = QVBoxLayout(barre)
        grille.setContentsMargins(6, 6, 6, 0)
        grille.setSpacing(3)

        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Scénario"))
        self.cb_scenario = QComboBox()
        self.cb_scenario.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_scenario.setMinimumContentsLength(12)
        self.cb_scenario.currentIndexChanged.connect(self._scenario_choisi)
        ligne.addWidget(self.cb_scenario, 1)
        grille.addLayout(ligne)

        ligne = QHBoxLayout()
        for texte, slot in (("Nouveau…", self._scenario_nouveau),
                            ("Dupliquer…", self._scenario_dupliquer),
                            ("Commentaire…", self._scenario_commentaire),
                            ("Supprimer", self._scenario_supprimer)):
            b = QPushButton(texte)
            b.clicked.connect(slot)
            ligne.addWidget(b)
        grille.addLayout(ligne)

        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Réseau"))
        self.cb_variante_scn = QComboBox()
        self.cb_variante_scn.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cb_variante_scn.setMinimumContentsLength(12)
        self.cb_variante_scn.currentIndexChanged.connect(self._variante_scenario_change)
        ligne.addWidget(self.cb_variante_scn, 1)
        grille.addLayout(ligne)
        return barre

    def _rafraichir_scenarios(self, selection=None):
        """Recharge les listes de scénarios et de variantes ; crée « Scénario 1 » au besoin."""
        projet = self._projet_silencieux()
        existe = projet is not None and projet.existe()
        scenarios = projet.lister_scenarios() if existe else []
        variantes = projet.lister_variantes() if existe else []
        if existe and not scenarios and variantes:
            try:
                projet.ecrire_scenario({
                    "nom": "scenario_1", "libelle": "Scénario 1", "variante": variantes[0]["nom"],
                    "description": "", "cree_le": datetime.now().isoformat(timespec="seconds")})
                scenarios = projet.lister_scenarios()
            except Exception as exc:
                self._msg(f"Création du premier scénario impossible : {exc}", "Critical")
        courant = selection or self.ctx.nom_scenario()

        for cb in (self.cb_scenario, self.cb_variante_scn):
            cb.blockSignals(True)
        self.cb_scenario.clear()
        for sc in scenarios:
            self.cb_scenario.addItem(sc["libelle"] or sc["nom"], sc["nom"])
        self.cb_variante_scn.clear()
        for v in variantes:
            self.cb_variante_scn.addItem(v["libelle"] or v["nom"], v["nom"])
        i = self.cb_scenario.findData(courant) if courant else -1
        self.cb_scenario.setCurrentIndex(i if i >= 0 else (0 if scenarios else -1))
        for cb in (self.cb_scenario, self.cb_variante_scn):
            cb.blockSignals(False)

        nom = self.cb_scenario.currentData()
        rec = next((sc for sc in scenarios if sc["nom"] == nom), None)
        if rec != self.ctx.scenario or selection:
            self._appliquer_scenario(rec)
        else:  # inchangé : on se contente de resynchroniser la liste des réseaux
            self._synchroniser_variante(rec)

    def _synchroniser_variante(self, rec):
        self.cb_variante_scn.blockSignals(True)
        i = self.cb_variante_scn.findData(rec["variante"]) if rec else -1
        self.cb_variante_scn.setCurrentIndex(i)
        self.cb_variante_scn.blockSignals(False)

    def _appliquer_scenario(self, rec):
        """Rend ``rec`` courant : réseau affiché, points de saisie et onglets rechargés."""
        self.ctx.scenario = rec
        self.ctx.invalider_reseau()
        self.cb_scenario.setToolTip((rec or {}).get("description") or "")
        self._synchroniser_variante(rec)
        if rec is not None:
            affichees = {lyr.customProperty(VARIANTE) for lyr in self._couches_role("troncons")}
            if rec["variante"] not in affichees:
                self._afficher(rec["variante"])
        self.ctx.recharger_points()
        for onglet in (self.o_prog, self.o_dist, self.o_aff):  # l'ordre compte
            onglet.charger()
        self.ctx.scenario_change.emit()

    def _scenario_choisi(self, *_):
        projet = self._projet_silencieux()
        nom = self.cb_scenario.currentData()
        rec = None
        if projet is not None and projet.existe() and nom:
            rec = next((sc for sc in projet.lister_scenarios() if sc["nom"] == nom), None)
        self._appliquer_scenario(rec)

    def _variante_scenario_change(self, *_):
        sc, slug = self.ctx.scenario, self.cb_variante_scn.currentData()
        projet = self._projet_silencieux()
        if not sc or not slug or slug == sc["variante"] or projet is None:
            return
        nouveau = {**sc, "variante": slug}
        try:
            projet.ecrire_scenario(nouveau)
        except Exception as exc:
            self._msg(f"Changement de réseau impossible : {exc}", "Critical")
            self._synchroniser_variante(sc)
            return
        self._appliquer_scenario(nouveau)
        self._msg("Réseau du scénario changé : vérifier les accès (onglet Programme), ils sont "
                  "rattachés aux tronçons par leur identifiant.", "Info", 10)

    def _scenario_nouveau(self):
        projet = self._projet()
        if projet is None:
            return
        variantes = projet.lister_variantes() if projet.existe() else []
        if not variantes:
            self._msg("Télécharger d'abord un réseau (onglet 1).", "Warning")
            return
        scenarios = projet.lister_scenarios()
        libelle, ok = QInputDialog.getText(
            self, "Nouveau scénario", "Nom du scénario :", text=f"Scénario {len(scenarios) + 1}")
        libelle = libelle.strip()
        if not ok or not libelle:
            return
        nom = slugify(libelle)
        if any(sc["nom"] == nom for sc in scenarios):
            self._msg(f"Le scénario « {nom} » existe déjà.", "Warning")
            return
        try:
            projet.ecrire_scenario({
                "nom": nom, "libelle": libelle,
                "variante": self.cb_variante_scn.currentData() or variantes[0]["nom"],
                "description": "", "cree_le": datetime.now().isoformat(timespec="seconds")})
        except Exception as exc:
            self._msg(f"Création du scénario impossible : {exc}", "Critical")
            return
        self._rafraichir_scenarios(selection=nom)

    def _scenario_dupliquer(self):
        sc, projet = self.ctx.scenario, self._projet()
        if not sc or projet is None:
            self._msg("Sélectionner d'abord un scénario.", "Warning")
            return
        libelle, ok = QInputDialog.getText(
            self, "Dupliquer le scénario", "Nom de la copie :", text=f"{sc['libelle']} (copie)")
        libelle = libelle.strip()
        if not ok or not libelle:
            return
        try:
            nouveau = projet.dupliquer_scenario(sc["nom"], libelle, self.ctx.crs_reseau())
        except Exception as exc:
            self._msg(f"Duplication impossible : {exc}", "Critical")
            return
        self._rafraichir_scenarios(selection=nouveau)

    def _scenario_commentaire(self):
        sc, projet = self.ctx.scenario, self._projet()
        if not sc or projet is None:
            self._msg("Sélectionner d'abord un scénario.", "Warning")
            return
        texte, ok = QInputDialog.getMultiLineText(
            self, "Commentaire du scénario", f"Commentaire sur « {sc['libelle']} » :",
            sc.get("description") or "")
        if not ok:
            return
        nouveau = {**sc, "description": texte.strip()}
        try:
            projet.ecrire_scenario(nouveau)
        except Exception as exc:
            self._msg(f"Enregistrement du commentaire impossible : {exc}", "Critical")
            return
        self.ctx.scenario = nouveau
        self.cb_scenario.setToolTip(nouveau["description"])

    def _scenario_supprimer(self):
        sc, projet = self.ctx.scenario, self._projet()
        if not sc or projet is None:
            self._msg("Sélectionner d'abord un scénario.", "Warning")
            return
        if QMessageBox.question(
                self, "Supprimer le scénario",
                f"Supprimer « {sc['libelle']} » (programme, accès, portes, distribution et "
                "résultats) ?") != QMessageBox.Yes:
            return
        crs = self.ctx.crs_reseau()
        self._retirer_couches(("resultats", "acces", "portes"))  # libère les tables du fichier
        try:
            projet.supprimer_scenario(sc["nom"], crs)
        except Exception as exc:
            self._msg(f"Suppression impossible : {exc}", "Critical")
            return
        self.ctx.scenario = None
        self._rafraichir_scenarios()

    # ------------------------------------------------------------------ UI
    def _onglet_reseau(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        # Projet
        g = QGroupBox("Projet")
        f = QFormLayout(g)
        ligne = QHBoxLayout()
        self.le_gpkg = QLineEdit()
        self.le_gpkg.setPlaceholderText("GeoPackage du projet (nouveau ou existant)")
        self.le_gpkg.editingFinished.connect(self._projet_change)
        btn = QPushButton("Parcourir…")
        btn.clicked.connect(self._choisir_gpkg)
        ligne.addWidget(self.le_gpkg)
        ligne.addWidget(btn)
        f.addRow("Fichier", ligne)
        self.w_crs = QgsProjectionSelectionWidget()
        crs_proj = QgsProject.instance().crs()
        self.w_crs.setCrs(crs_proj if not crs_proj.isGeographic()
                          else QgsCoordinateReferenceSystem("EPSG:2154"))
        f.addRow("SCR du projet", self.w_crs)
        lay.addWidget(g)

        # Périmètre
        g = QGroupBox("1. Périmètre d'étude")
        v = QVBoxLayout(g)
        self.rb_emprise = QRadioButton("Emprise actuelle de la carte")
        self.rb_couche = QRadioButton("Couche polygonale")
        self.rb_dessin = QRadioButton("Dessiner sur la carte")
        self.rb_emprise.setChecked(True)
        v.addWidget(self.rb_emprise)
        v.addWidget(self.rb_couche)
        self.w_couche = QgsMapLayerComboBox()
        self.w_couche.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        v.addWidget(self.w_couche)
        v.addWidget(self.rb_dessin)
        f = QFormLayout()
        self.sp_tampon = QDoubleSpinBox()
        self.sp_tampon.setRange(0, 5000)
        self.sp_tampon.setSingleStep(50)
        self.sp_tampon.setValue(300)
        self.sp_tampon.setSuffix(" m")
        f.addRow("Tampon autour du périmètre", self.sp_tampon)
        v.addLayout(f)
        self.btn_perimetre = QPushButton("Définir le périmètre")
        self.btn_perimetre.clicked.connect(self._definir_perimetre)
        v.addWidget(self.btn_perimetre)
        self.lbl_perimetre = QLabel("Aucun périmètre défini.")
        self.lbl_perimetre.setWordWrap(True)
        v.addWidget(self.lbl_perimetre)
        lay.addWidget(g)

        # Téléchargement
        g = QGroupBox("2. Réseau OSM")
        f = QFormLayout(g)
        self.cb_niveau = QComboBox()
        self.cb_niveau.addItem("Standard (jusqu'aux rues résidentielles)", "standard")
        self.cb_niveau.addItem("Structurant (jusqu'aux tertiaires)", "structurant")
        self.cb_niveau.addItem("Complet (avec voies de service)", "complet")
        f.addRow("Niveau de détail", self.cb_niveau)
        self.le_variante = QLineEdit("base")
        f.addRow("Nom de la variante", self.le_variante)
        self.le_desc = QLineEdit()
        self.le_desc.setPlaceholderText("Description (facultatif)")
        f.addRow("Description", self.le_desc)
        ligne = QHBoxLayout()
        self.btn_dl = QPushButton("Télécharger le réseau")
        self.btn_dl.clicked.connect(self._telecharger)
        self.btn_stop = QPushButton("Annuler")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(lambda: self._task and self._task.cancel())
        ligne.addWidget(self.btn_dl)
        ligne.addWidget(self.btn_stop)
        f.addRow(ligne)
        self.lbl_etat = QLabel("")
        self.lbl_etat.setWordWrap(True)
        f.addRow(self.lbl_etat)
        lay.addWidget(g)

        # Variantes
        g = QGroupBox("3. Variantes de réseau")
        v = QVBoxLayout(g)
        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(
            ["Variante", "Parent", "Créée le", "Tronçons", "km", "Commentaire"])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.verticalHeader().hide()
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setMinimumHeight(110)
        self.tbl.itemDoubleClicked.connect(lambda _i: self._afficher(self._variante_choisie()))
        self.tbl.itemSelectionChanged.connect(self._charger_commentaire)
        v.addWidget(self.tbl)
        ligne = QHBoxLayout()
        for texte, slot in (("Afficher", lambda: self._afficher(self._variante_choisie())),
                            ("Dupliquer…", self._dupliquer),
                            ("Supprimer", self._supprimer),
                            ("Actualiser", self._actualiser)):
            b = QPushButton(texte)
            b.clicked.connect(slot)
            ligne.addWidget(b)
        v.addLayout(ligne)
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Style :"))
        self.rb_neutre = QRadioButton("Neutre")
        self.rb_sens = QRadioButton("Sens de circulation")
        self.rb_neutre.setChecked(True)
        self.rb_neutre.toggled.connect(self._appliquer_style)
        ligne.addWidget(self.rb_neutre)
        ligne.addWidget(self.rb_sens)
        ligne.addStretch()
        v.addLayout(ligne)
        v.addWidget(QLabel("Commentaire de la variante sélectionnée :"))
        self.te_comm = QPlainTextEdit()
        self.te_comm.setPlaceholderText("Objet de la variante, hypothèses, différences avec la "
                                        "variante d'origine…")
        self.te_comm.setFixedHeight(64)
        v.addWidget(self.te_comm)
        self.btn_comm = QPushButton("Enregistrer le commentaire")
        self.btn_comm.clicked.connect(self._enregistrer_commentaire)
        v.addWidget(self.btn_comm)
        aide = QLabel("Pour modifier le réseau : <b>dupliquer</b> d'abord la variante pour "
                      "conserver l'originale, l'afficher, puis utiliser les outils ci-dessous. "
                      "« Actualiser » recalcule les statistiques.")
        aide.setWordWrap(True)
        v.addWidget(aide)
        lay.addWidget(g)
        self.barre_edition = BarreEditionReseau(self)
        lay.addWidget(self.barre_edition)
        lay.addStretch()

        zone = QScrollArea()
        zone.setWidgetResizable(True)
        zone.setWidget(page)
        return zone

    # --------------------------------------------------------------- utilitaires
    def _msg(self, texte, niveau="Info", duree=8):
        self.iface.messageBar().pushMessage("Affectation trafic", texte, _niveau(niveau), duree)

    def _projet(self):
        chemin = self.le_gpkg.text().strip()
        if not chemin:
            self._msg("Choisir d'abord un GeoPackage de projet.", "Warning")
            return None
        if not chemin.lower().endswith(".gpkg"):
            chemin += ".gpkg"
            self.le_gpkg.setText(chemin)
        return ProjetGpkg(chemin)

    def _choisir_gpkg(self):
        chemin, _ = QFileDialog.getSaveFileName(
            self, "GeoPackage du projet", QgsProject.instance().homePath(),
            "GeoPackage (*.gpkg)", options=QFileDialog.DontConfirmOverwrite)
        if chemin:
            self.le_gpkg.setText(chemin)
            self._projet_change()

    def _groupe(self):
        racine = QgsProject.instance().layerTreeRoot()
        return racine.findGroup(GROUPE) or racine.insertGroup(0, GROUPE)

    def _retirer_couches(self, roles, slug=None):
        proj = QgsProject.instance()
        for lyr in list(proj.mapLayers().values()):
            if lyr.customProperty(ROLE) in roles and (
                    slug is None or lyr.customProperty(VARIANTE) == slug):
                proj.removeMapLayer(lyr.id())

    def _couches_role(self, role):
        return [lyr for lyr in QgsProject.instance().mapLayers().values()
                if lyr.customProperty(ROLE) == role]

    def _variante_choisie(self):
        lignes = self.tbl.selectionModel().selectedRows()
        if not lignes:
            self._msg("Sélectionner une variante dans la liste.", "Warning")
            return None
        return self.tbl.item(lignes[0].row(), 0).data(Qt.UserRole)

    # ------------------------------------------------------------------ projet
    def _projet_change(self):
        projet = self._projet_silencieux()
        if projet is None:
            return
        self._remplir_table()
        lu = projet.lire_perimetre() if projet.existe() else None
        if lu:
            self.geom_perimetre, self.geom_zone, crs, tampon = lu
            self.w_crs.setCrs(crs)
            self.sp_tampon.setValue(tampon)
            self._maj_label_perimetre()

    def _projet_silencieux(self):
        chemin = self.le_gpkg.text().strip()
        if not chemin:
            return None
        if not chemin.lower().endswith(".gpkg"):
            chemin += ".gpkg"
        return ProjetGpkg(chemin)

    # ---------------------------------------------------------------- périmètre
    def _definir_perimetre(self):
        if self._projet() is None:
            return
        if self.w_crs.crs().isGeographic():
            self._msg("Choisir un SCR projeté (mètres), par ex. Lambert-93.", "Warning")
            return
        if self.rb_emprise.isChecked():
            geom = QgsGeometry.fromRect(self.canvas.extent())
            self._appliquer_geometrie(geom, self.canvas.mapSettings().destinationCrs())
        elif self.rb_couche.isChecked():
            lyr = self.w_couche.currentLayer()
            if lyr is None:
                self._msg("Aucune couche polygonale disponible.", "Warning")
                return
            feats = (lyr.selectedFeatures() if lyr.selectedFeatureCount()
                     else list(lyr.getFeatures()))
            geoms = [f.geometry() for f in feats if f.hasGeometry()]
            if not geoms:
                self._msg("La couche ne contient aucune entité.", "Warning")
                return
            self._appliquer_geometrie(QgsGeometry.unaryUnion(geoms), lyr.crs())
        else:
            self._outil = OutilPolygone(self.canvas)
            self._outil.termine.connect(self._polygone_dessine)
            self.canvas.setMapTool(self._outil)
            self._msg("Clic gauche : sommet · clic droit ou Entrée : terminer · Échap : annuler.")

    def _polygone_dessine(self, geom):
        self.canvas.unsetMapTool(self._outil)
        self._appliquer_geometrie(geom, self.canvas.mapSettings().destinationCrs())

    def _appliquer_geometrie(self, geom, crs_source):
        crs = self.w_crs.crs()
        g = QgsGeometry(geom)
        if crs_source != crs:
            g.transform(QgsCoordinateTransform(crs_source, crs, QgsProject.instance()))
        if not g.isGeosValid():
            g = g.makeValid()
        tampon = self.sp_tampon.value()
        zone = g.buffer(tampon, 12) if tampon > 0 else QgsGeometry(g)
        self.geom_perimetre, self.geom_zone = g, zone
        projet = self._projet()
        try:
            projet.ecrire_perimetre(g, zone, crs, tampon)
        except Exception as exc:
            self._msg(f"Écriture du périmètre impossible : {exc}", "Critical")
            return
        self._maj_label_perimetre()
        self._charger_perimetre(projet, zoom=True)

    def _maj_label_perimetre(self):
        if self.geom_perimetre is None:
            self.lbl_perimetre.setText("Aucun périmètre défini.")
            return
        ha = self.geom_perimetre.area() / 1e4
        km2 = self.geom_zone.area() / 1e6
        txt = f"Périmètre : {ha:,.1f} ha · zone de téléchargement : {km2:,.2f} km²".replace(",", " ")
        if km2 > SEUIL_KM2:
            txt += " — <b>zone étendue</b>, le téléchargement peut être long."
        self.lbl_perimetre.setText(txt)

    def _charger_perimetre(self, projet, zoom=False):
        self._retirer_couches(("perimetre",))
        lyr = projet.couche("perimetre")
        if lyr is None:
            return
        lyr.setName("Périmètre d'étude")
        lyr.setCustomProperty(ROLE, "perimetre")
        QgsProject.instance().addMapLayer(lyr, False)
        self._groupe().insertLayer(0, lyr)
        styles.style_perimetre(lyr)
        if zoom:
            self._zoom(lyr)

    def _zoom(self, lyr):
        ext = self.canvas.mapSettings().layerExtentToOutputExtent(lyr, lyr.extent())
        ext.scale(1.1)
        self.canvas.setExtent(ext)
        self.canvas.refresh()

    # ------------------------------------------------------------ téléchargement
    def _telecharger(self):
        projet = self._projet()
        if projet is None:
            return
        if self.geom_zone is None:
            self._msg("Définir d'abord le périmètre.", "Warning")
            return
        libelle = self.le_variante.text().strip() or "base"
        slug = slugify(libelle)
        if projet.variante_existe(slug) and QMessageBox.question(
                self, "Variante existante",
                f"La variante « {slug} » existe déjà : l'écraser ?\n\nLes identifiants de "
                "tronçons changent : le trafic de référence et le journal de cette variante "
                "sont supprimés, et les accès qui y sont rattachés sont à vérifier.\n"
                "Pour garder l'existante, choisir un autre nom.") != QMessageBox.Yes:
            return
        km2 = self.geom_zone.area() / 1e6
        if km2 > SEUIL_KM2 and QMessageBox.question(
                self, "Zone étendue",
                f"La zone fait {km2:.0f} km². Le téléchargement peut être long, voire refusé "
                "par le serveur. Continuer ?") != QMessageBox.Yes:
            return
        try:
            anneau = self._anneau_lonlat()
        except Exception as exc:
            self._msg(f"Périmètre inexploitable : {exc}", "Critical")
            return

        crs = self.w_crs.crs()
        description = self.le_desc.text().strip()
        niveau = self.cb_niveau.currentData()
        self._task = TelechargementReseau(
            anneau, self.geom_zone.asWkt(), crs.toWkt(), niveau,
            QgsProject.instance().transformContext(),
            lambda t, ok: self._telechargement_fini(t, ok, projet, libelle, description, crs))
        self._task.progressChanged.connect(
            lambda p: self.lbl_etat.setText(f"Téléchargement et découpage… {p:.0f} %"))
        self.btn_dl.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.lbl_etat.setText("Requête envoyée à Overpass…")
        QgsApplication.taskManager().addTask(self._task)

    def _anneau_lonlat(self):
        """Contour du périmètre élargi (tampon) en lon/lat, simplifié pour Overpass."""
        g = QgsGeometry(self.geom_zone)
        g.transform(QgsCoordinateTransform(
            self.w_crs.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()))
        if g.isMultipart():
            g = g.convexHull()
        simple = g.simplify(0.0002)  # ≈ 20 m
        if simple is not None and not simple.isNull() and not simple.isMultipart():
            g = simple
        else:
            g = g.convexHull()
        anneau = g.asPolygon()[0]
        return [(p.x(), p.y()) for p in anneau]

    def _telechargement_fini(self, task, ok, projet, libelle, description, crs):
        self.btn_dl.setEnabled(True)
        self.btn_stop.setEnabled(False)
        if not ok:
            texte = task.erreur or "Téléchargement annulé."
            self.lbl_etat.setText(texte)
            self._msg(f"Échec du téléchargement : {texte}", "Warning")
            return
        # Écraser une variante déjà affichée : ses couches doivent quitter le projet avant que
        # le GeoPackage ne remplace les tables, sinon QGIS lit une table qui n'existe plus.
        self._retirer_couches(("troncons", "noeuds"), slug=slugify(libelle))
        try:
            slug = projet.ecrire_variante(
                libelle, description, "", "OSM (Overpass)", task.segments, crs)
        except Exception as exc:
            self.lbl_etat.setText(str(exc))
            self._msg(f"Écriture de la variante impossible : {exc}", "Critical")
            return
        n = len(task.segments)
        km = sum(s["longueur"] for s in task.segments) / 1000
        uni = 100 * sum(1 for s in task.segments if s["sens"] != 0) / n
        ponts = sum(1 for s in task.segments if s.get("ouvrage") == "pont")
        tunnels = sum(1 for s in task.segments if s.get("ouvrage") == "tunnel")
        giratoires = sum(1 for s in task.segments if s.get("rond_point"))
        vit = sum(1 for s in task.segments if s.get("vit_osm") is not None)
        self.lbl_etat.setText(
            f"{n} tronçons · {km:.1f} km · {uni:.0f} % en sens unique · {ponts} pont(s), "
            f"{tunnels} tunnel(s), {giratoires} tronçon(s) de giratoire · vitesse autorisée "
            f"renseignée sur {100 * vit / n:.0f} % des tronçons.")
        self._remplir_table()  # peut déjà afficher la variante (premier scénario créé)
        if slug not in {lyr.customProperty(VARIANTE) for lyr in self._couches_role("troncons")}:
            self._afficher(slug)

    # ------------------------------------------------------------------ variantes
    def _remplir_table(self):
        projet = self._projet_silencieux()
        variantes = projet.lister_variantes() if projet and projet.existe() else []
        lignes = self.tbl.selectionModel().selectedRows()
        selection = (self.tbl.item(lignes[0].row(), 0).data(Qt.UserRole)
                     if lignes and self.tbl.item(lignes[0].row(), 0) else None)
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(variantes))
        for i, v in enumerate(variantes):
            comment = (v["description"] or "").replace("\n", " ")
            valeurs = [v["libelle"], v["parent"] or "—", (v["cree_le"] or "")[:16].replace("T", " "),
                       str(v["nb_troncons"]), f"{v['longueur_km']:.1f}",
                       comment if len(comment) <= 60 else comment[:57] + "…"]
            for j, texte in enumerate(valeurs):
                item = QTableWidgetItem(texte)
                if j == 0:
                    item.setData(Qt.UserRole, v["nom"])
                    item.setToolTip(v["description"] or "")
                self.tbl.setItem(i, j, item)
            if v["nom"] == selection:
                self.tbl.selectRow(i)
        self.tbl.blockSignals(False)
        self._charger_commentaire()
        self._rafraichir_scenarios()

    def _slug_selectionne(self):
        lignes = self.tbl.selectionModel().selectedRows()
        if not lignes or self.tbl.item(lignes[0].row(), 0) is None:
            return None
        return self.tbl.item(lignes[0].row(), 0).data(Qt.UserRole)

    def _charger_commentaire(self):
        slug = self._slug_selectionne()
        projet = self._projet_silencieux()
        texte = ""
        if slug and projet is not None and projet.existe():
            v = next((v for v in projet.lister_variantes() if v["nom"] == slug), None)
            texte = (v["description"] if v else "") or ""
        self.te_comm.setPlainText(texte)
        self.te_comm.setEnabled(bool(slug))
        self.btn_comm.setEnabled(bool(slug))

    def _enregistrer_commentaire(self):
        slug, projet = self._slug_selectionne(), self._projet()
        if not slug or projet is None:
            self._msg("Sélectionner une variante dans la liste.", "Warning")
            return
        try:
            projet.maj_description(slug, self.te_comm.toPlainText().strip())
        except Exception as exc:
            self._msg(f"Enregistrement du commentaire impossible : {exc}", "Critical")
            return
        self._remplir_table()

    # -- accès pour la barre d'outils d'édition ------------------------------------------------
    def projet_courant(self):
        return self._projet_silencieux()

    def couche_troncons(self):
        couches = self._couches_role("troncons")
        return couches[0] if couches else None

    def couche_noeuds(self):
        couches = self._couches_role("noeuds")
        return couches[0] if couches else None

    def apres_edition(self):
        """Statistiques de la variante, cache du réseau et affichage après une modification."""
        self.ctx.invalider_reseau()
        troncons, projet = self.couche_troncons(), self._projet_silencieux()
        if troncons is not None and projet is not None and not troncons.isEditable():
            slug = troncons.customProperty(VARIANTE)
            try:
                projet.mettre_a_jour_stats(slug)
            except Exception as exc:
                self._msg(f"Statistiques de la variante non mises à jour : {exc}", "Warning")
            self._remplir_table()
        for lyr in (troncons, self.couche_noeuds()):
            if lyr is not None:
                lyr.triggerRepaint()

    def _actualiser(self):
        projet = self._projet()
        if projet is None or not projet.existe():
            return
        for v in projet.lister_variantes():
            projet.mettre_a_jour_stats(v["nom"])
        self._remplir_table()

    def _afficher(self, slug):
        if not slug:
            return
        projet = self._projet()
        try:
            if projet.assurer_champs(slug):
                self._msg("Variante créée avec une version antérieure : champs ajoutés (actif, "
                          "giratoire, pont/tunnel…) avec des valeurs par défaut. Pour obtenir "
                          "les attributs OSM, télécharger le réseau sous un nouveau nom.", "Info", 12)
        except Exception as exc:
            self._msg(f"Mise à niveau de la variante impossible : {exc}", "Critical")
            return
        troncons = projet.couche(PREFIX_TRONCONS + slug)
        noeuds = projet.couche(PREFIX_NOEUDS + slug)
        if troncons is None or noeuds is None:
            self._msg(f"Couches de la variante « {slug} » introuvables.", "Critical")
            return
        libelle = next((v["libelle"] for v in projet.lister_variantes() if v["nom"] == slug), slug)

        self._retirer_couches(("troncons", "noeuds"))
        proj = QgsProject.instance()
        groupe = self._groupe()
        for lyr, role, nom in ((troncons, "troncons", f"Réseau – {libelle}"),
                               (noeuds, "noeuds", f"Nœuds – {libelle}")):
            lyr.setName(nom)
            lyr.setCustomProperty(ROLE, role)
            lyr.setCustomProperty(VARIANTE, slug)
            proj.addMapLayer(lyr, False)
        groupe.addLayer(troncons)
        groupe.addLayer(noeuds).setItemVisibilityChecked(False)
        styles.configurer_champs(troncons)
        styles.style_noeuds(noeuds)
        self._appliquer_style()
        if not self._couches_role("perimetre") and projet.couche("perimetre") is not None:
            self._charger_perimetre(projet)
        self._zoom(troncons)

    def _appliquer_style(self, *_):
        mode = styles.STYLE_SENS if self.rb_sens.isChecked() else styles.STYLE_NEUTRE
        for lyr in self._couches_role("troncons"):
            styles.appliquer(lyr, mode)

    def _dupliquer(self):
        slug = self._variante_choisie()
        if not slug:
            return
        projet = self._projet()
        nom, ok = QInputDialog.getText(
            self, "Dupliquer la variante", "Nom de la nouvelle variante :", text=f"{slug}_v2")
        if not ok or not nom.strip():
            return
        try:
            nouveau = projet.dupliquer(slug, nom.strip())
        except Exception as exc:
            self._msg(f"Duplication impossible : {exc}", "Critical")
            return
        self._remplir_table()
        self._afficher(nouveau)

    def _supprimer(self):
        slug = self._variante_choisie()
        if not slug:
            return
        projet = self._projet()
        utilisee = [sc["libelle"] for sc in projet.lister_scenarios() if sc["variante"] == slug]
        if utilisee:
            self._msg(f"Variante utilisée par le(s) scénario(s) : {', '.join(utilisee)}. "
                      "Changer leur réseau ou les supprimer d'abord.", "Warning")
            return
        if QMessageBox.question(
                self, "Supprimer la variante",
                f"Supprimer définitivement la variante « {slug} » du GeoPackage ?"
        ) != QMessageBox.Yes:
            return
        self._retirer_couches(("troncons", "noeuds"), slug=slug)
        try:
            projet.supprimer(slug)
        except Exception as exc:
            self._msg(f"Suppression impossible : {exc}", "Critical")
            return
        self._remplir_table()

