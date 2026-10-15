"""Tâche de fond : téléchargement Overpass + construction des tronçons."""
import json
import time
from urllib.parse import quote

from qgis.core import (
    QgsBlockingNetworkRequest,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsSettings,
    QgsTask,
)
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from . import osm_parse

# Instances publiques essayées dans l'ordre. Pour imposer un serveur (le vôtre, par exemple) :
# réglage QGIS « affectation_trafic/overpass_url » (Préférences > Avancé).
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
TOURS = 2        # nombre de passages sur la liste des serveurs
PAUSE_S = 10     # attente entre deux passages (serveurs saturés)
USER_AGENT = "QGIS-AffectationTrafic/0.1"


class TelechargementReseau(QgsTask):
    """Télécharge les voies OSM du périmètre et les découpe en tronçons.

    Tout le travail réseau et le calcul se font hors du thread principal ;
    ``callback(task, ok)`` est appelé dans le thread principal à la fin.
    Résultat : ``task.segments`` (dicts avec ``geom`` en QgsGeometry, ``longueur`` en m).
    """

    def __init__(self, anneau_lonlat, zone_wkt, crs_wkt, niveau, transform_context, callback):
        super().__init__("Téléchargement du réseau OSM", QgsTask.CanCancel)
        self.anneau = anneau_lonlat
        self.zone_wkt = zone_wkt
        self.crs_wkt = crs_wkt
        self.niveau = niveau
        self.ctx = transform_context
        self.callback = callback
        self.segments = []
        self.erreur = None
        perso = str(QgsSettings().value("affectation_trafic/overpass_url", "") or "").strip()
        self.urls = ([perso] if perso else []) + OVERPASS_URLS

    def _attendre(self, secondes):
        for _ in range(secondes):
            if self.isCanceled():
                return False
            time.sleep(1)
        return True

    def _appel_overpass(self, requete):
        """Interroge les serveurs Overpass l'un après l'autre, avec nouvelles tentatives.

        Un serveur saturé (504, 429, réponse tronquée) est simplement remplacé par le suivant ;
        une requête refusée (400) arrête tout, car un autre serveur la refuserait aussi.
        """
        corps = QByteArray(("data=" + quote(requete, safe="")).encode("utf-8"))
        echecs = []
        total = TOURS * len(self.urls)
        essai = 0
        for tour in range(TOURS):
            for url in self.urls:
                if self.isCanceled():
                    return None
                essai += 1
                self.setProgress(5 + 40.0 * essai / total)
                hote = QUrl(url).host()
                req = QNetworkRequest(QUrl(url))
                req.setHeader(QNetworkRequest.ContentTypeHeader,
                              "application/x-www-form-urlencoded")
                req.setHeader(QNetworkRequest.UserAgentHeader, USER_AGENT)
                if hasattr(req, "setTransferTimeout"):
                    req.setTransferTimeout(180000)
                br = QgsBlockingNetworkRequest()
                err = br.post(req, corps)
                statut = br.reply().attribute(QNetworkRequest.HttpStatusCodeAttribute)
                if err == QgsBlockingNetworkRequest.NoError:
                    try:
                        data = json.loads(bytes(br.reply().content()).decode("utf-8"))
                    except ValueError:
                        echecs.append(f"{hote} : réponse illisible")
                        continue
                    ok, message = osm_parse.verifier_reponse(data)
                    if ok:
                        return data
                    echecs.append(f"{hote} : {message}")
                else:
                    echecs.append(f"{hote} : {statut or ''} {br.errorMessage()}".strip())
                    if statut == 400:
                        self.erreur = ("Requête refusée par Overpass (400) : " + echecs[-1])
                        return None
            if tour < TOURS - 1 and not self._attendre(PAUSE_S):
                return None
        self.erreur = ("Aucun serveur Overpass n'a répondu (serveurs saturés ou injoignables). "
                       "Réessayer dans quelques minutes, ou réduire le périmètre / le niveau de "
                       "détail. Détail : " + " | ".join(echecs[-4:]))
        return None

    def run(self):
        try:
            self.setProgress(5)
            data = self._appel_overpass(osm_parse.requete_overpass(self.anneau, self.niveau))
            if data is None:
                return False
            self.setProgress(50)
            segments = osm_parse.decouper(data["elements"])
            if not segments:
                self.erreur = "Aucune voie trouvée dans le périmètre (vérifier le niveau de détail)."
                return False

            crs = QgsCoordinateReferenceSystem()
            crs.createFromWkt(self.crs_wkt)
            tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), crs, self.ctx)
            zone = QgsGeometry.fromWkt(self.zone_wkt)

            gardes = []
            for i, s in enumerate(segments):
                if self.isCanceled():
                    return False
                pts = [tr.transform(QgsPointXY(x, y)) for x, y in s.pop("coords")]
                geom = QgsGeometry.fromPolylineXY(pts)
                if not zone.intersects(geom):
                    continue
                s["geom"] = geom
                s["longueur"] = geom.length()
                gardes.append(s)
                if i % 500 == 0:
                    self.setProgress(50 + 45 * i / len(segments))
            for n, s in enumerate(gardes, 1):
                s["id"] = n  # renumérotation après filtrage
            self.segments = gardes
            if not gardes:
                self.erreur = "Aucun tronçon dans la zone après filtrage."
                return False
            self.setProgress(100)
            return True
        except Exception as exc:  # remonté à l'utilisateur dans finished()
            self.erreur = f"{type(exc).__name__} : {exc}"
            return False

    def finished(self, ok):
        self.callback(self, ok)
