"""Outil de carte pour dessiner un polygone (clic gauche = sommet, clic droit = terminer)."""
from qgis.core import QgsGeometry, QgsWkbTypes
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor


def _type_polygone():
    try:
        from qgis.core import Qgis
        return Qgis.GeometryType.Polygon
    except (ImportError, AttributeError):
        return QgsWkbTypes.PolygonGeometry


class OutilPolygone(QgsMapToolEmitPoint):
    """Émet ``termine(QgsGeometry)`` en coordonnées du canevas."""

    termine = pyqtSignal(QgsGeometry)

    def __init__(self, canvas):
        super().__init__(canvas)
        self._canvas = canvas
        self._points = []
        self._rb = QgsRubberBand(canvas, _type_polygone())
        self._rb.setColor(QColor(192, 57, 43, 200))
        self._rb.setFillColor(QColor(192, 57, 43, 50))
        self._rb.setWidth(2)

    def _dessiner(self, curseur=None):
        self._rb.reset(_type_polygone())
        pts = list(self._points) + ([curseur] if curseur is not None else [])
        for p in pts:
            self._rb.addPoint(p, False)
        if pts:
            self._rb.show()

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._points.append(self.toMapCoordinates(event.pos()))
            self._dessiner()
        elif event.button() == Qt.RightButton:
            self._finir()

    def canvasMoveEvent(self, event):
        if self._points:
            self._dessiner(self.toMapCoordinates(event.pos()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reinit()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finir()

    def _finir(self):
        if len(self._points) >= 3:
            geom = QgsGeometry.fromPolygonXY([list(self._points)])
            self._reinit()
            self.termine.emit(geom)
        else:
            self._reinit()

    def _reinit(self):
        self._points = []
        self._rb.reset(_type_polygone())

    def deactivate(self):
        self._reinit()
        super().deactivate()


def _type_ligne():
    try:
        from qgis.core import Qgis
        return Qgis.GeometryType.Line
    except (ImportError, AttributeError):
        return QgsWkbTypes.LineGeometry


class OutilLigne(QgsMapToolEmitPoint):
    """Trace une polyligne (clic gauche = sommet, clic droit ou Entrée = terminer, Échap = annuler).

    Émet ``termine(list)`` : liste de QgsPointXY en coordonnées du canevas.
    """

    termine = pyqtSignal(list)

    def __init__(self, canvas):
        super().__init__(canvas)
        self._points = []
        self._rb = QgsRubberBand(canvas, _type_ligne())
        self._rb.setColor(QColor(31, 95, 168, 220))
        self._rb.setWidth(3)

    def _dessiner(self, curseur=None):
        self._rb.reset(_type_ligne())
        pts = list(self._points) + ([curseur] if curseur is not None else [])
        for p in pts:
            self._rb.addPoint(p, False)
        if pts:
            self._rb.show()

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._points.append(self.toMapCoordinates(event.pos()))
            self._dessiner()
        elif event.button() == Qt.RightButton:
            self._finir()

    def canvasMoveEvent(self, event):
        if self._points:
            self._dessiner(self.toMapCoordinates(event.pos()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._reinit()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._finir()

    def _finir(self):
        pts = list(self._points)
        self._reinit()
        if len(pts) >= 2:
            self.termine.emit(pts)

    def _reinit(self):
        self._points = []
        self._rb.reset(_type_ligne())

    def deactivate(self):
        self._reinit()
        super().deactivate()
