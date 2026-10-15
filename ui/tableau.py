"""Tableau éditable générique (saisie de la programmation, des ratios, de la distribution…)."""
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class Colonne:
    """nom : clé du dict ; type : str | float | int | choix ; choix : callable -> liste."""

    def __init__(self, nom, titre, type="str", choix=None, editable=True, cache=False,
                 aide="", libre=False):
        self.nom, self.titre, self.type = nom, titre, type
        self.choix, self.editable, self.cache = choix, editable, cache
        self.aide, self.libre = aide, libre  # libre : liste déroulante modifiable


def _nombre(texte, type_):
    texte = (texte or "").strip().replace(",", ".")
    if texte == "":
        return None
    try:
        v = float(texte)
    except ValueError:
        return None
    return int(v) if type_ == "int" else v


def _texte(valeur):
    if valeur is None:
        return ""
    if isinstance(valeur, float):
        return f"{valeur:.6g}"
    return str(valeur)


class TableauEditable(QWidget):
    modifie = pyqtSignal()

    def __init__(self, colonnes, boutons=True, hauteur_min=110, parent=None):
        super().__init__(parent)
        self.colonnes = colonnes
        self._bloque = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tbl = QTableWidget(0, len(colonnes))
        self.tbl.setHorizontalHeaderLabels([c.titre for c in colonnes])
        for i, c in enumerate(colonnes):
            if c.cache:
                self.tbl.setColumnHidden(i, True)
            if c.aide:
                self.tbl.horizontalHeaderItem(i).setToolTip(c.aide)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.verticalHeader().hide()
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setMinimumHeight(hauteur_min)
        self.tbl.itemChanged.connect(self._changement)
        lay.addWidget(self.tbl)
        self.barre = QHBoxLayout()
        if boutons:
            b1 = QPushButton("+ Ligne")
            b1.clicked.connect(lambda: self.ajouter_ligne())
            b2 = QPushButton("– Supprimer la ligne")
            b2.clicked.connect(self.supprimer_selection)
            self.barre.addWidget(b1)
            self.barre.addWidget(b2)
        self.barre.addStretch()
        lay.addLayout(self.barre)

    # -- données ------------------------------------------------------------
    def _changement(self, *_):
        if not self._bloque:
            self.modifie.emit()

    def ajouter_ligne(self, valeurs=None, emettre=True):
        valeurs = valeurs or {}
        self._bloque = True
        try:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            for j, c in enumerate(self.colonnes):
                v = valeurs.get(c.nom)
                if c.type == "choix":
                    cb = QComboBox()
                    cb.setEditable(c.libre)
                    cb.addItems([str(x) for x in (c.choix() if c.choix else [])])
                    if v is not None:
                        i = cb.findText(str(v))
                        if i >= 0:
                            cb.setCurrentIndex(i)
                        elif c.libre:
                            cb.setCurrentText(str(v))
                        else:
                            cb.addItem(str(v))
                            cb.setCurrentText(str(v))
                    cb.currentTextChanged.connect(self._changement)
                    self.tbl.setCellWidget(r, j, cb)
                else:
                    it = QTableWidgetItem(_texte(v))
                    if not c.editable:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                        it.setBackground(self.palette().alternateBase())
                    self.tbl.setItem(r, j, it)
        finally:
            self._bloque = False
        if emettre:
            self.modifie.emit()

    def supprimer_selection(self):
        lignes = self.tbl.selectionModel().selectedRows()
        if lignes:
            self.tbl.removeRow(lignes[0].row())
            self.modifie.emit()

    def ligne_selectionnee(self):
        lignes = self.tbl.selectionModel().selectedRows()
        return lignes[0].row() if lignes else None

    def valeur(self, ligne, nom):
        j = next(i for i, c in enumerate(self.colonnes) if c.nom == nom)
        return self._lire_cellule(ligne, j)

    def definir_valeur(self, ligne, nom, valeur):
        j = next(i for i, c in enumerate(self.colonnes) if c.nom == nom)
        self._bloque = True
        try:
            w = self.tbl.cellWidget(ligne, j)
            if w is not None:
                w.setCurrentText(str(valeur))
            else:
                self.tbl.item(ligne, j).setText(_texte(valeur))
        finally:
            self._bloque = False

    def _lire_cellule(self, r, j):
        c = self.colonnes[j]
        w = self.tbl.cellWidget(r, j)
        if w is not None:
            return w.currentText().strip() or None
        texte = self.tbl.item(r, j).text() if self.tbl.item(r, j) else ""
        if c.type in ("float", "int"):
            return _nombre(texte, c.type)
        return texte.strip() or None

    def lignes(self):
        """Lignes non vides, sous forme de dicts (cellules vides -> None)."""
        out = []
        for r in range(self.tbl.rowCount()):
            ligne = {c.nom: self._lire_cellule(r, j) for j, c in enumerate(self.colonnes)}
            if any(v is not None for v in ligne.values()):
                out.append(ligne)
        return out

    def definir_lignes(self, lignes):
        self._bloque = True
        try:
            self.tbl.setRowCount(0)
        finally:
            self._bloque = False
        for l in lignes:
            self.ajouter_ligne(l, emettre=False)

    def rafraichir_choix(self):
        """Recharge les listes déroulantes en conservant les valeurs choisies."""
        self._bloque = True
        try:
            for r in range(self.tbl.rowCount()):
                for j, c in enumerate(self.colonnes):
                    w = self.tbl.cellWidget(r, j)
                    if w is not None and c.choix:
                        actuel = w.currentText()
                        w.clear()
                        w.addItems([str(x) for x in c.choix()])
                        i = w.findText(actuel)
                        if i >= 0:
                            w.setCurrentIndex(i)
                        else:
                            w.addItem(actuel)
                            w.setCurrentText(actuel)
        finally:
            self._bloque = False
