import faulthandler
import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

from .ui.dock import AffectationDock


_JOURNAL_PLANTAGE = None


def _activer_journal_plantage():
    """En cas de plantage de QGIS, la ligne de code Python en cours est écrite dans
    <profil QGIS>/affectation_trafic_plantage.log (à joindre à un signalement)."""
    global _JOURNAL_PLANTAGE
    try:
        chemin = os.path.join(QgsApplication.qgisSettingsDirPath(),
                              "affectation_trafic_plantage.log")
        _JOURNAL_PLANTAGE = open(chemin, "a", buffering=1, encoding="utf-8")
        faulthandler.enable(file=_JOURNAL_PLANTAGE, all_threads=True)
    except Exception:
        _JOURNAL_PLANTAGE = None  # diagnostic facultatif : ne jamais gêner le plugin


class AffectationPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        _activer_journal_plantage()

    def initGui(self):
        icone = QgsApplication.getThemeIcon("/mIconLineLayer.svg")
        self.action = QAction(icone, "Affectation trafic", self.iface.mainWindow())
        self.action.triggered.connect(self.afficher)
        self.iface.addPluginToMenu("&Affectation trafic", self.action)
        self.iface.addToolBarIcon(self.action)

    def afficher(self):
        if self.dock is None:
            self.dock = AffectationDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu("&Affectation trafic", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        global _JOURNAL_PLANTAGE
        if _JOURNAL_PLANTAGE is not None:
            faulthandler.disable()
            _JOURNAL_PLANTAGE.close()
            _JOURNAL_PLANTAGE = None
