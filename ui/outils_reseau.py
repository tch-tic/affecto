"""Barre d'outils de modification du réseau : inverser, double sens / sens unique,
nouveau tronçon, désactiver / restaurer, et historique des modifications."""
import math

from qgis.core import QgsCoordinateTransform, QgsPointXY, QgsProject
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from ..core import osm_parse
from ..core.edition import EditeurReseau, ErreurEdition, troncon_proche
from ..core.regles_edition import CLASSES_CREATION
from .map_tools import OutilLigne

TOLERANCE_PX = 10  # distance de clic acceptée pour désigner un tronçon ou un nœud

# clé, libellé du bouton, info-bulle, aide affichée une fois l'outil actif
ACTIONS = [
    ("inverser", "Inverser le sens",
     "Inverse le sens d'un tronçon à sens unique",
     "Cliquer sur un tronçon à sens unique pour inverser son sens."),
    ("double", "Double / unique",
     "Passe un tronçon en double sens, ou en sens unique (dans le sens du tracé)",
     "Cliquer sur un tronçon : double sens <-> sens unique."),
    ("creer", "Nouveau tronçon",
     "Trace un nouveau tronçon, raccordé aux nœuds ou tronçons proches",
     "Clic gauche : sommets · clic droit ou Entrée : terminer · Échap : annuler. "
     "Les extrémités s'accrochent aux nœuds ; sur un tronçon, un carrefour est créé."),
    ("supprimer", "Supprimer / restaurer",
     "Désactive un tronçon (conservé mais inutilisable) ou le restaure",
     "Cliquer sur un tronçon pour le désactiver ; le cliquer à nouveau le restaure."),
]


class DialogNouveauTroncon(QDialog):
    """Attributs du tronçon à créer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau tronçon")
        f = QFormLayout(self)
        self.le_nom = QLineEdit()
        f.addRow("Nom (facultatif)", self.le_nom)
        self.cb_classe = QComboBox()
        for valeur, libelle in CLASSES_CREATION:
            self.cb_classe.addItem(libelle, valeur)
        f.addRow("Type de voie", self.cb_classe)
        self.cb_sens = QComboBox()
        self.cb_sens.addItem("Double sens", 0)
        self.cb_sens.addItem("Sens unique (sens du tracé)", 1)
        f.addRow("Circulation", self.cb_sens)
        self.sp_vitesse = QSpinBox()
        self.sp_vitesse.setRange(5, 130)
        self.sp_vitesse.setSuffix(" km/h")
        f.addRow("Vitesse", self.sp_vitesse)
        self.sp_voies = QSpinBox()
        self.sp_voies.setRange(0, 8)
        self.sp_voies.setSpecialValueText("non renseigné")
        f.addRow("Nombre de voies", self.sp_voies)
        self.cb_ouvrage = QComboBox()
        self.cb_ouvrage.addItem("Au sol", "")
        self.cb_ouvrage.addItem("Pont", "pont")
        self.cb_ouvrage.addItem("Tunnel", "tunnel")
        f.addRow("Ouvrage", self.cb_ouvrage)
        boutons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        f.addRow(boutons)
        self.cb_classe.currentIndexChanged.connect(self._vitesse_par_defaut)
        self._vitesse_par_defaut()

    def _vitesse_par_defaut(self, *_):
        self.sp_vitesse.setValue(osm_parse.VITESSE_DEFAUT.get(self.cb_classe.currentData(), 50))

    def valeurs(self):
        return {
            "nom": self.le_nom.text().strip(), "highway": self.cb_classe.currentData(),
            "sens": self.cb_sens.currentData(), "vitesse": self.sp_vitesse.value(),
            "voies": self.sp_voies.value() or None, "ouvrage": self.cb_ouvrage.currentData(),
        }


class DialogHistorique(QDialog):
    """Journal des modifications d'une variante de réseau."""

    def __init__(self, variante, lignes, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Historique des modifications – {variante}")
        self.resize(640, 380)
        lay = QVBoxLayout(self)
        if not lignes:
            lay.addWidget(QLabel("Aucune modification enregistrée pour cette variante."))
        tbl = QTableWidget(len(lignes), 4)
        tbl.setHorizontalHeaderLabels(["Date", "Tronçon", "Action", "Détail"])
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.verticalHeader().hide()
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setStretchLastSection(True)
        for i, l in enumerate(sorted(lignes, key=lambda x: x.get("date") or "", reverse=True)):
            for j, texte in enumerate([(l.get("date") or "").replace("T", " "),
                                       "" if l.get("tid") is None else str(l["tid"]),
                                       l.get("action") or "", l.get("detail") or ""]):
                tbl.setItem(i, j, QTableWidgetItem(texte))
        lay.addWidget(tbl)
        fermer = QDialogButtonBox(QDialogButtonBox.Close)
        fermer.rejected.connect(self.reject)
        lay.addWidget(fermer)


class BarreEditionReseau(QGroupBox):
    """Quatre outils de carte exclusifs, appliqués à la variante affichée."""

    def __init__(self, dock):
        super().__init__("4. Modification du réseau")
        self.dock = dock
        self.canvas = dock.canvas
        self._outil = None
        self._boutons = {}
        self._aides = {}
        lay = QVBoxLayout(self)
        ligne = QHBoxLayout()
        for cle, libelle, info, aide in ACTIONS:
            b = QToolButton()
            b.setText(libelle)
            b.setToolTip(info)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.toggled.connect(lambda etat, c=cle: self._bascule(c, etat))
            ligne.addWidget(b)
            self._boutons[cle] = b
            self._aides[cle] = aide
        lay.addLayout(ligne)
        self.lbl = QLabel("Afficher une variante, puis choisir un outil. Un tronçon désactivé "
                          "reste dans la couche (tracé rouge en tirets) mais n'est plus utilisé "
                          "par le calcul.")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        hist = QPushButton("Historique des modifications…")
        hist.clicked.connect(self._historique)
        lay.addWidget(hist)
        self.canvas.mapToolSet.connect(self._outil_change)

    # -- activation des outils --------------------------------------------------------------
    def _bascule(self, cle, etat):
        if not etat:
            if self._outil is not None and self.canvas.mapTool() is self._outil:
                self.canvas.unsetMapTool(self._outil)
            return
        for autre, b in self._boutons.items():  # un seul outil actif à la fois
            if autre != cle and b.isChecked():
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
        if self.dock.couche_troncons() is None:
            self.dock._msg("Afficher d'abord une variante de réseau (liste ci-dessus).", "Warning")
            self._boutons[cle].blockSignals(True)
            self._boutons[cle].setChecked(False)
            self._boutons[cle].blockSignals(False)
            return
        if cle == "creer":
            outil = OutilLigne(self.canvas)
            outil.termine.connect(self._creer)
        else:
            outil = QgsMapToolEmitPoint(self.canvas)
            outil.canvasClicked.connect(lambda pt, _b, c=cle: self._clic(c, pt))
        self._outil = outil
        self.canvas.setMapTool(outil)
        self.lbl.setText(self._aides[cle])

    def _outil_change(self, nouveau, _ancien):
        if nouveau is not self._outil:
            for b in self._boutons.values():
                if b.isChecked():
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)

    # -- géométrie : canevas -> couche -----------------------------------------------------
    def _transformation(self, layer):
        return QgsCoordinateTransform(self.canvas.mapSettings().destinationCrs(),
                                      layer.crs(), QgsProject.instance())

    def _tolerance(self, tr, point):
        decalage = QgsPointXY(point.x() + TOLERANCE_PX * self.canvas.mapUnitsPerPixel(), point.y())
        a, b = tr.transform(point), tr.transform(decalage)
        return math.hypot(b.x() - a.x(), b.y() - a.y())

    def _editeur(self, layer):
        projet = self.dock.projet_courant()
        noeuds = self.dock.couche_noeuds()
        slug = layer.customProperty("affectation/variante")
        if projet is None or noeuds is None or not slug:
            raise ErreurEdition("Variante de réseau non affichée.")
        return EditeurReseau(projet, slug, layer, noeuds)

    # -- actions ------------------------------------------------------------------------------
    def _clic(self, cle, point):
        layer = self.dock.couche_troncons()
        if layer is None:
            return
        tr = self._transformation(layer)
        fid = troncon_proche(layer, tr.transform(point), self._tolerance(tr, point))
        if fid is None:
            self.dock._msg("Aucun tronçon à proximité du clic.", "Warning", 3)
            return
        try:
            editeur = self._editeur(layer)
            action = {"inverser": editeur.inverser, "double": editeur.basculer_double,
                      "supprimer": editeur.basculer_actif}[cle]
            texte = action(fid)
        except ErreurEdition as exc:
            self.dock._msg(str(exc), "Warning")
            return
        except Exception as exc:
            self.dock._msg(f"Modification impossible : {exc}", "Critical")
            return
        self.dock.apres_edition()
        self.lbl.setText(texte)

    def _creer(self, points):
        layer = self.dock.couche_troncons()
        if layer is None:
            return
        dlg = DialogNouveauTroncon(self.dock)
        if dlg.exec_() != QDialog.Accepted:
            return
        tr = self._transformation(layer)
        pts = [QgsPointXY(tr.transform(p)) for p in points]
        tol = self._tolerance(tr, points[0])
        try:
            texte = self._editeur(layer).creer(pts, dlg.valeurs(), tol)
        except ErreurEdition as exc:
            self.dock._msg(str(exc), "Warning")
            return
        except Exception as exc:
            self.dock._msg(f"Création impossible : {exc}", "Critical")
            return
        self.dock.apres_edition()
        self.lbl.setText(texte)

    def _historique(self):
        layer = self.dock.couche_troncons()
        projet = self.dock.projet_courant()
        if layer is None or projet is None:
            self.dock._msg("Afficher d'abord une variante de réseau.", "Warning")
            return
        slug = layer.customProperty("affectation/variante")
        DialogHistorique(slug, projet.lire_journal(slug), self.dock).exec_()
