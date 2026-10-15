"""État partagé entre les onglets : projet, scénario courant, réseau, sélection sur la carte."""
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..core import donnees, styles

GROUPE = "Affectation – Réseau"
GROUPE_RESULTATS = "Affectation – Résultats"
ROLE = "affectation/role"
VARIANTE = "affectation/variante"


def groupe(nom):
    racine = QgsProject.instance().layerTreeRoot()
    return racine.findGroup(nom) or racine.insertGroup(0, nom)


def retirer_couches(roles, slug=None):
    proj = QgsProject.instance()
    for lyr in list(proj.mapLayers().values()):
        if lyr.customProperty(ROLE) in roles and (
                slug is None or lyr.customProperty(VARIANTE) == slug):
            proj.removeMapLayer(lyr.id())


class Contexte(QObject):
    scenario_change = pyqtSignal()

    def __init__(self, iface, fournir_projet, msg):
        super().__init__()
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self._fournir_projet = fournir_projet
        self.msg = msg
        self.scenario = None  # enregistrement de la table « scenarios »
        self._reseau = self._geoms = self._crs = None
        self._cle = None
        self._outil = None

    def projet(self):
        return self._fournir_projet()

    def nom_scenario(self):
        return self.scenario["nom"] if self.scenario else None

    def variante(self):
        return self.scenario["variante"] if self.scenario else None

    def invalider_reseau(self):
        self._cle = None

    def reseau(self):
        """Reseau (moteur) de la variante du scénario courant, mis en cache."""
        projet = self.projet()
        if projet is None or not self.scenario:
            return None
        cle = (projet.chemin, self.variante())
        if cle != self._cle:
            try:
                self._reseau, self._geoms, self._crs = donnees.lire_reseau(projet, self.variante())
            except Exception as exc:
                self.msg(f"Lecture du réseau impossible : {exc}", "Critical")
                return None
            self._cle = cle
            for a in getattr(self._reseau, "avertissements", []):
                self.msg(a, "Warning")
        return self._reseau

    def crs_reseau(self):
        """SCR du projet : celui du réseau du scénario, à défaut celui du périmètre."""
        if self._crs is None or self._cle is None:
            self.reseau()
        if self._crs is not None:
            return self._crs
        projet = self.projet()
        per = projet.couche("perimetre") if projet else None
        return per.crs() if per is not None else QgsCoordinateReferenceSystem("EPSG:2154")

    # -- sélection d'un tronçon ou d'un nœud sur la carte -------------------------------
    def choisir_sur_carte(self, mode, callback):
        """mode : « troncon » ou « noeud ». callback reçoit {id, dist, x, y} (SCR du réseau)."""
        self.invalider_reseau()  # relire le réseau : il a pu être modifié
        res = self.reseau()
        if res is None:
            self.msg("Définir d'abord un scénario avec un réseau valide.", "Warning")
            return
        outil = QgsMapToolEmitPoint(self.canvas)
        self._outil = outil

        def clic(point, _bouton):
            self.canvas.unsetMapTool(outil)
            tr = QgsCoordinateTransform(self.canvas.mapSettings().destinationCrs(),
                                        self._crs, QgsProject.instance())
            p = tr.transform(point)
            r = (res.plus_proche_troncon(p.x(), p.y()) if mode == "troncon"
                 else res.plus_proche_noeud(p.x(), p.y()))
            if r is None:
                self.msg("Aucun élément du réseau trouvé.", "Warning")
                return
            callback(r)

        outil.canvasClicked.connect(clic)
        self.canvas.setMapTool(outil)
        self.msg("Cliquer sur la carte pour choisir un " +
                 ("tronçon" if mode == "troncon" else "nœud") + " (Échap pour annuler).", "Info", 6)

    # -- couches d'accès et de portes du scénario ----------------------------------------
    def recharger_points(self):
        retirer_couches(("acces", "portes"))
        projet = self.projet()
        if projet is None or not self.scenario:
            return
        g = groupe(GROUPE)
        filtre = f"\"scenario\" = '{self.scenario['nom']}'"
        for table, role, nom, style in (
                ("portes", "portes", "Portes", styles.style_portes),
                ("acces", "acces", "Accès des lots", styles.style_acces)):
            lyr = projet.couche(table)
            if lyr is None:
                continue
            lyr.setSubsetString(filtre)
            lyr.setName(f"{nom} – {self.scenario['libelle']}")
            lyr.setCustomProperty(ROLE, role)
            QgsProject.instance().addMapLayer(lyr, False)
            g.insertLayer(0, lyr)
            style(lyr)
