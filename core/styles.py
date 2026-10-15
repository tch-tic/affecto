"""Styles des couches : réseau neutre, réseau avec sens de circulation, périmètre."""
from qgis.core import (
    Qgis,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerLineSymbolLayer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProperty,
    QgsRuleBasedRenderer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSymbolLayer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

STYLE_NEUTRE = "neutre"
STYLE_SENS = "sens"

GRIS = "#8a8a8a"
BLEU = "#1f5fa8"
# Orientation de la flèche (angle du marqueur « ArrowHead » sur la ligne).
# Valeur validée dans QGIS 3.40 : 0° suit le sens de numérisation, 180° l'inverse.
ANGLE_FLECHE = 0

_STRUCTURANT = ("'motorway','motorway_link','trunk','trunk_link',"
                "'primary','primary_link'")
_SECONDAIRE = "'secondary','secondary_link','tertiary','tertiary_link'"


def _ligne(couleur, largeur):
    return QgsLineSymbol.createSimple({
        "color": couleur, "width": str(largeur),
        "capstyle": "round", "joinstyle": "round",
    })


def _forme_fleche():
    try:
        from qgis.core import Qgis
        return Qgis.MarkerShape.ArrowHead
    except (ImportError, AttributeError):
        from qgis.core import QgsSimpleMarkerSymbolLayerBase
        return QgsSimpleMarkerSymbolLayerBase.ArrowHead


def _placement_centre():
    try:
        from qgis.core import QgsTemplatedLineSymbolLayerBase
        return QgsTemplatedLineSymbolLayerBase.CentralPoint
    except ImportError:
        return QgsMarkerLineSymbolLayer.CentralPoint


def _appliquer_regles(layer, regles, niveaux=False):
    """Rend des règles (symbole, filtre, libellé). ``niveaux`` : ordre par « passe » des
    couches de symbole (ponts au-dessus, tunnels en dessous), indépendant de l'ordre des tronçons."""
    racine = QgsRuleBasedRenderer.Rule(None)
    for symbole, filtre, libelle in regles:
        racine.appendChild(QgsRuleBasedRenderer.Rule(symbole, 0, 0, filtre, libelle))
    rendu = QgsRuleBasedRenderer(racine)
    if niveaux:
        rendu.setUsingSymbolLevels(True)
    layer.setRenderer(rendu)
    layer.triggerRepaint()


# Conditions des règles (champs récents absents d'une ancienne variante : valeurs par défaut)
_ACTIF = 'coalesce("actif", 1) = 1'
INACTIF = 'coalesce("actif", 1) = 0'
PONT = _ACTIF + " AND \"ouvrage\" = 'pont'"
TUNNEL = _ACTIF + " AND \"ouvrage\" = 'tunnel'"
SOL = _ACTIF + " AND coalesce(\"ouvrage\", '') NOT IN ('pont', 'tunnel')"
SANS_ROND_POINT = 'coalesce("rond_point", 0) = 0'

# Ordre de dessin (passes) : tunnels < voirie < fond des ponts < ponts < flèches
PASSE_TUNNEL, PASSE_SOL, PASSE_CAISSON, PASSE_PONT, PASSE_FLECHE = 0, 1, 2, 3, 4
COULEUR_INACTIF = "#c0392b"
COULEUR_CAISSON = "#3c3c3c"

_LARGEUR_CLASSE = (f'CASE WHEN "highway" IN ({_STRUCTURANT}) THEN 1.0 '
                   f'WHEN "highway" IN ({_SECONDAIRE}) THEN 0.7 ELSE 0.4 END')
_COULEUR_SENS = f"CASE WHEN coalesce(\"sens\", 0) <> 0 THEN '{BLEU}' ELSE '{GRIS}' END"


def _couche_ligne(couleur, largeur, passe, expr_largeur=None, expr_couleur=None, tirets=False,
                  capsule=Qt.RoundCap, delta_largeur=0.0):
    """Couche de symbole « ligne simple », largeur/couleur éventuellement pilotées par expression.

    Construite directement (sans symbole temporaire ni clone) : les objets sip qui dépendent
    d'un propriétaire déjà détruit font planter QGIS.
    """
    sl = QgsSimpleLineSymbolLayer(QColor(couleur), largeur + delta_largeur)
    sl.setPenCapStyle(capsule)
    sl.setPenJoinStyle(Qt.RoundJoin)
    if tirets:
        sl.setPenStyle(Qt.DashLine)
    if expr_largeur:
        expr = f"({expr_largeur}) + {delta_largeur}" if delta_largeur else expr_largeur
        sl.setDataDefinedProperty(_propriete("StrokeWidth"), QgsProperty.fromExpression(expr))
    if expr_couleur:
        sl.setDataDefinedProperty(_propriete("StrokeColor"), QgsProperty.fromExpression(expr_couleur))
    sl.setRenderingPass(passe)
    return sl


def _corps(couleur, largeur, passe, expr_largeur=None, expr_couleur=None, tirets=False):
    return QgsLineSymbol([_couche_ligne(couleur, largeur, passe, expr_largeur, expr_couleur,
                                        tirets)])


def _pont(couleur, largeur, expr_largeur=None, expr_couleur=None):
    """Pont : filet sombre sous la voie, dessiné au-dessus du reste du réseau."""
    caisson = _couche_ligne(COULEUR_CAISSON, largeur, PASSE_CAISSON, expr_largeur, None,
                            capsule=Qt.FlatCap, delta_largeur=0.5)
    corps = _couche_ligne(couleur, largeur, PASSE_PONT, expr_largeur, expr_couleur,
                          capsule=Qt.FlatCap)
    return QgsLineSymbol([caisson, corps])


def _fleche_seule(angle, condition_sens):
    """Symbole sans trait : uniquement une flèche au milieu du tronçon."""
    fleche = QgsSimpleMarkerSymbolLayer(_forme_fleche(), 3.6, angle)
    fleche.setColor(QColor(BLEU))
    fleche.setStrokeColor(QColor(BLEU))
    fleche.setStrokeWidth(0.6)
    marqueur = QgsMarkerSymbol.createSimple({"name": "circle", "size": "1"})
    marqueur.changeSymbolLayer(0, fleche)
    couche = QgsMarkerLineSymbolLayer(True)
    couche.setPlacement(_placement_centre())
    couche.setSubSymbol(marqueur)
    couche.setRenderingPass(PASSE_FLECHE)
    return QgsLineSymbol([couche]), (
        f'{_ACTIF} AND {SANS_ROND_POINT} AND "sens" = {condition_sens}')


def _regles_corps(largeur_fixe, couleur, expr_couleur=None, par_classe=False):
    """Règles du trait : tronçon désactivé, tunnel, pont, puis voirie au sol."""
    el = _LARGEUR_CLASSE if par_classe else None
    base = 0.6 if largeur_fixe is None else largeur_fixe
    regles = [
        (_corps(COULEUR_INACTIF, 0.4, PASSE_TUNNEL, tirets=True), INACTIF,
         "Tronçon désactivé"),
        (_corps("#9aa0a6", base, PASSE_TUNNEL, el, expr_couleur, tirets=True), TUNNEL, "Tunnel"),
        (_pont(couleur, base, el, expr_couleur), PONT, "Pont"),
    ]
    if par_classe:
        regles += [
            (_corps(couleur, 1.0, PASSE_SOL), f'{SOL} AND "highway" IN ({_STRUCTURANT})',
             "Voirie structurante"),
            (_corps(couleur, 0.7, PASSE_SOL), f'{SOL} AND "highway" IN ({_SECONDAIRE})',
             "Voirie secondaire"),
            (_corps(couleur, 0.4, PASSE_SOL), f'{SOL} AND NOT ("highway" IN ({_STRUCTURANT}) '
             f'OR "highway" IN ({_SECONDAIRE}))', "Voirie de desserte"),
        ]
    else:
        regles.append((_corps(couleur, base, PASSE_SOL, None, expr_couleur), SOL, "Voirie"))
    return regles


def style_neutre(layer):
    """Gris uniforme, épaisseur selon la hiérarchie ; ponts, tunnels et désactivés distincts."""
    _appliquer_regles(layer, _regles_corps(None, GRIS, par_classe=True), niveaux=True)


def style_sens(layer):
    """Double sens en gris ; sens unique en bleu avec flèche (sauf giratoires)."""
    regles = _regles_corps(0.6, GRIS, expr_couleur=_COULEUR_SENS)
    for angle, sens, libelle in ((ANGLE_FLECHE, 1, "Sens unique (sens de numérisation)"),
                                 (ANGLE_FLECHE + 180, -1, "Sens unique (sens inverse)")):
        symbole, filtre = _fleche_seule(angle, sens)
        regles.append((symbole, filtre, libelle))
    _appliquer_regles(layer, regles, niveaux=True)


def appliquer(layer, style):
    if style == STYLE_SENS:
        style_sens(layer)
    else:
        style_neutre(layer)


def style_perimetre(layer):
    perimetre = QgsFillSymbol.createSimple({
        "color": "0,0,0,0", "outline_color": "#c0392b", "outline_width": "0.9"})
    zone = QgsFillSymbol.createSimple({
        "color": "0,0,0,0", "outline_color": "#c0392b",
        "outline_width": "0.4", "outline_style": "dash"})
    _appliquer_regles(layer, [
        (perimetre, '"type" = \'perimetre\'', "Périmètre d'étude"),
        (zone, '"type" = \'zone_reseau\'', "Zone de téléchargement (tampon)"),
    ])


def style_noeuds(layer):
    layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({
        "name": "circle", "size": "1.6", "color": "#ffffff",
        "outline_color": "#555555", "outline_width": "0.2"}))
    layer.triggerRepaint()


def configurer_champs(layer):
    """Liste déroulante pour le champ « sens » : pratique pour éditer le réseau."""
    from qgis.core import QgsDefaultValue, QgsEditorWidgetSetup
    i_id = layer.fields().indexOf("id")
    if i_id >= 0:  # tronçons dessinés à la main : identifiant suivant automatique
        layer.setDefaultValueDefinition(
            i_id, QgsDefaultValue('coalesce(maximum("id"), 0) + 1'))
    for nom, valeurs in (
            ("sens", [{"Double sens": 0}, {"Sens de numérisation": 1}, {"Sens inverse": -1}]),
            ("actif", [{"Actif": 1}, {"Désactivé": 0}]),
            ("rond_point", [{"Non": 0}, {"Giratoire": 1}])):
        idx = layer.fields().indexOf(nom)
        if idx >= 0:
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ValueMap", {"map": valeurs}))


# ---------------------------------------------------------------- résultats
VALEURS_RESULTATS = {
    # clé : (suffixe du champ, libellé, seuils, couleurs, valeur pour la largeur max)
    "tot": ("tot", "Trafic total (référence + projet)", (800, 1200),
            ("#4fbdca", "#0a4c7f", "#4d2c68"), 2000),
    "proj": ("proj", "Trafic généré par le projet", (25, 50),
             ("#f6c85f", "#f28e2b", "#c0392b"), 60),
    "pct": ("pct", "Hausse par rapport à la référence (%)", (5, 10),
            ("#4fbdca", "#f28e2b", "#c0392b"), 20),
}


def _propriete(nom):
    try:
        return getattr(QgsSymbolLayer.Property, nom)
    except AttributeError:
        return getattr(QgsSymbolLayer, "Property" + nom)


def _ligne_flux(couleur, largeur_expr):
    sym = QgsLineSymbol.createSimple({"color": couleur, "capstyle": "flat",
                                      "joinstyle": "round", "width": "0.5"})
    sym.symbolLayer(0).setDataDefinedProperty(
        _propriete("StrokeWidth"), QgsProperty.fromExpression(largeur_expr))
    return sym


def _placement_ligne():
    try:
        return Qgis.LabelPlacement.Line
    except AttributeError:
        return QgsPalLayerSettings.Line


def etiquettes(layer, expression, taille=7):
    s = QgsPalLayerSettings()
    s.fieldName = expression
    s.isExpression = True
    s.placement = _placement_ligne()
    fmt = QgsTextFormat()
    fmt.setSize(taille)
    fmt.setColor(QColor("#222222"))
    tampon = QgsTextBufferSettings()
    tampon.setEnabled(True)
    tampon.setSize(0.8)
    tampon.setColor(QColor("white"))
    fmt.setBuffer(tampon)
    s.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer.setLabelsEnabled(True)


def style_resultats(layer, periode, valeur, avec_etiquettes=True):
    """Bandes proportionnelles au trafic, couleur par classes (comme les cartes de charges).

    ``periode`` : "hpm" | "hps" ; ``valeur`` : "tot" | "proj" | "pct".
    """
    suffixe, _lib, (s1, s2), (c1, c2, c3), vmax = VALEURS_RESULTATS[valeur]
    champ = f"{periode}_{suffixe}"
    largeur = f'scale_linear(coalesce("{champ}", 0), 0, {vmax}, 0.4, 5)'
    nul = f'coalesce("{champ}", 0) <= 0'
    _appliquer_regles(layer, [
        (_ligne_flux("#d4d4d4", "0.3"), nul, "Aucun trafic"),
        (_ligne_flux(c1, largeur), f'coalesce("{champ}", 0) > 0 AND "{champ}" < {s1}', f"< {s1}"),
        (_ligne_flux(c2, largeur), f'"{champ}" >= {s1} AND "{champ}" < {s2}', f"{s1} – {s2}"),
        (_ligne_flux(c3, largeur), f'"{champ}" >= {s2}', f"≥ {s2}"),
    ])
    if avec_etiquettes:
        if valeur == "tot":
            etiquettes(layer, f'CASE WHEN "{champ}" > 0 THEN round("{champ}", -1) END')
        elif valeur == "proj":
            etiquettes(layer, f'CASE WHEN "{champ}" >= 1 THEN round("{champ}", 0) END')
        else:
            etiquettes(layer, f'CASE WHEN "{champ}" > 0 THEN round("{champ}", 1) || \' %\' END')
    else:
        layer.setLabelsEnabled(False)
    layer.triggerRepaint()


def style_acces(layer):
    layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({
        "name": "square", "size": "3.6", "color": "#1f5fa8",
        "outline_color": "#ffffff", "outline_width": "0.4"}))
    _etiquette_ponctuelle(layer, "\"lot_id\" || '/' || \"acces_id\"", "#1f5fa8")


def style_portes(layer):
    layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({
        "name": "circle", "size": "3.4", "color": "#c0392b",
        "outline_color": "#ffffff", "outline_width": "0.4"}))
    _etiquette_ponctuelle(layer, '"porte_id"', "#c0392b")


def _etiquette_ponctuelle(layer, expression, couleur):
    s = QgsPalLayerSettings()
    s.fieldName = expression
    s.isExpression = True
    try:
        s.placement = Qgis.LabelPlacement.AroundPoint
    except AttributeError:
        s.placement = QgsPalLayerSettings.AroundPoint
    fmt = QgsTextFormat()
    fmt.setSize(9)
    fmt.setColor(QColor(couleur))
    tampon = QgsTextBufferSettings()
    tampon.setEnabled(True)
    tampon.setSize(1.0)
    tampon.setColor(QColor("white"))
    fmt.setBuffer(tampon)
    s.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()
