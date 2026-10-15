"""Stockage du projet dans un GeoPackage unique.

Contenu :
- ``perimetre``          : polygones (type = perimetre | zone_reseau)
- ``variantes``          : table (sans géométrie) qui décrit chaque variante de réseau
- ``troncons__<variante>`` : un tronçon par ligne, champ ``sens`` (0 / 1 / -1)
- ``noeuds__<variante>``   : nœuds (extrémités de tronçons) avec leur degré

Une variante = un jeu de couches. On peut donc modifier une copie du réseau
sans toucher à la variante de départ.
"""
import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

from qgis.core import (
    NULL,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsProviderRegistry,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from .defauts import SCHEMAS, TABLES_SCENARIO

PREFIX_TRONCONS = "troncons__"
PREFIX_NOEUDS = "noeuds__"
COUCHE_PERIMETRE = "perimetre"
TABLE_VARIANTES = "variantes"

CHAMPS_VARIANTES = ["nom", "libelle", "description", "parent", "source",
                    "cree_le", "nb_troncons", "longueur_km"]


# Champs ajoutés aux couches de tronçons : (nom, type, valeur donnée aux lignes existantes)
CHAMPS_TRONCONS_AJOUTES = [
    ("vit_osm", QVariant.Int, None),      # vitesse du tag maxspeed (NULL si absente)
    ("rond_point", QVariant.Int, 0),      # 1 = giratoire (pas de flèche)
    ("ouvrage", QVariant.String, ""),     # '' (sol), 'pont' ou 'tunnel'
    ("niveau", QVariant.Int, 0),          # tag OSM layer
    ("actif", QVariant.Int, 1),           # 0 = tronçon désactivé (conservé mais inutilisable)
    ("origine", QVariant.String, "osm"),  # osm | ajout | coupe
]

TYPES_CHAMPS = {"str": QVariant.String, "float": QVariant.Double, "int": QVariant.LongLong}


def slugify(texte):
    """Identifiant de couche sûr (ASCII, minuscules, underscores)."""
    s = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s or "reseau"


def _point_xy(ligne):
    if ligne.get("x") is None or ligne.get("y") is None:
        return None
    return QgsGeometry.fromPointXY(QgsPointXY(ligne["x"], ligne["y"]))


class ProjetGpkg:
    def __init__(self, chemin):
        self.chemin = chemin

    # -- accès bas niveau --------------------------------------------------
    def existe(self):
        return os.path.exists(self.chemin)

    def tables(self):
        """Noms des tables du GeoPackage, ou None si le fichier ne peut pas être lu ainsi.

        Lecture seule via sqlite3 : évite d'ouvrir une couche inexistante, ce que QGIS
        signale par un avertissement « Impossible de trouver la couche … ».
        """
        try:
            uri = Path(self.chemin).resolve().as_uri() + "?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=2)
            try:
                return {r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
            finally:
                con.close()
        except Exception:
            return None

    def couche(self, nom_couche):
        if not self.existe():
            return None
        presentes = self.tables()
        if presentes is not None and nom_couche not in presentes:
            return None
        lyr = QgsVectorLayer(f"{self.chemin}|layername={nom_couche}", nom_couche, "ogr")
        return lyr if lyr.isValid() else None

    def _ecrire(self, layer, nom_couche):
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = nom_couche
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteLayer if self.existe()
            else QgsVectorFileWriter.CreateOrOverwriteFile)
        res = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, self.chemin, QgsProject.instance().transformContext(), opts)
        if res[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Écriture de « {nom_couche} » impossible : {res[1]}")

    @staticmethod
    def _copie_memoire(layer):
        """Copie une couche en mémoire (évite de lire et écrire le même fichier)."""
        wkb = layer.wkbType()
        from qgis.core import QgsWkbTypes
        type_txt = QgsWkbTypes.displayString(wkb) if wkb else "None"
        mem = QgsVectorLayer(type_txt, "copie", "memory")
        mem.setCrs(layer.crs())
        mem.dataProvider().addAttributes(list(layer.fields()))
        mem.updateFields()
        mem.dataProvider().addFeatures(list(layer.getFeatures()))
        return mem

    # -- périmètre -----------------------------------------------------------
    def ecrire_perimetre(self, geom_perimetre, geom_zone, crs, buffer_m):
        lyr = QgsVectorLayer("MultiPolygon", "perimetre", "memory")
        lyr.setCrs(crs)
        pr = lyr.dataProvider()
        pr.addAttributes([QgsField("type", QVariant.String),
                          QgsField("buffer_m", QVariant.Double),
                          QgsField("cree_le", QVariant.String)])
        lyr.updateFields()
        maintenant = datetime.now().isoformat(timespec="seconds")
        feats = []
        for type_, geom in (("perimetre", geom_perimetre), ("zone_reseau", geom_zone)):
            f = QgsFeature(lyr.fields())
            g = QgsGeometry(geom)
            g.convertToMultiType()
            f.setGeometry(g)
            f.setAttributes([type_, float(buffer_m), maintenant])
            feats.append(f)
        pr.addFeatures(feats)
        self._ecrire(lyr, COUCHE_PERIMETRE)

    def lire_perimetre(self):
        """Retourne (geom_perimetre, geom_zone, crs, buffer_m) ou None."""
        lyr = self.couche(COUCHE_PERIMETRE)
        if lyr is None:
            return None
        geoms, buffer_m = {}, 0.0
        for f in lyr.getFeatures():
            geoms[f["type"]] = f.geometry()
            buffer_m = f["buffer_m"] or 0.0
        if "perimetre" not in geoms or "zone_reseau" not in geoms:
            return None
        return geoms["perimetre"], geoms["zone_reseau"], lyr.crs(), buffer_m

    # -- variantes -----------------------------------------------------------
    def lister_variantes(self):
        lyr = self.couche(TABLE_VARIANTES)
        if lyr is None:
            return []
        out = []
        for f in lyr.getFeatures():
            out.append({c: f[c] for c in CHAMPS_VARIANTES})
        return sorted(out, key=lambda r: r["cree_le"] or "")

    def variante_existe(self, slug):
        return any(v["nom"] == slug for v in self.lister_variantes())

    def _ecrire_variantes(self, enregistrements):
        lyr = QgsVectorLayer("None", TABLE_VARIANTES, "memory")
        pr = lyr.dataProvider()
        pr.addAttributes([
            QgsField("nom", QVariant.String), QgsField("libelle", QVariant.String),
            QgsField("description", QVariant.String), QgsField("parent", QVariant.String),
            QgsField("source", QVariant.String), QgsField("cree_le", QVariant.String),
            QgsField("nb_troncons", QVariant.Int), QgsField("longueur_km", QVariant.Double),
        ])
        lyr.updateFields()
        feats = []
        for r in enregistrements:
            f = QgsFeature(lyr.fields())
            f.setAttributes([r[c] for c in CHAMPS_VARIANTES])
            feats.append(f)
        pr.addFeatures(feats)
        self._ecrire(lyr, TABLE_VARIANTES)

    def _maj_variante(self, enreg):
        autres = [v for v in self.lister_variantes() if v["nom"] != enreg["nom"]]
        self._ecrire_variantes(autres + [enreg])

    def ecrire_variante(self, libelle, description, parent, source, segments, crs):
        """Écrit les couches troncons__/noeuds__ d'une variante (écrase si elle existe)."""
        slug = slugify(libelle)
        self._purger_dependances(slug)  # identifiants renumérotés : référence et journal périmés
        troncons = self._couche_troncons(segments, crs)
        noeuds = self._couche_noeuds(segments, crs)
        self._ecrire(troncons, PREFIX_TRONCONS + slug)
        self._ecrire(noeuds, PREFIX_NOEUDS + slug)
        longueur_km = sum(s["longueur"] for s in segments) / 1000.0
        self._maj_variante({
            "nom": slug, "libelle": libelle, "description": description or "",
            "parent": parent or "", "source": source,
            "cree_le": datetime.now().isoformat(timespec="seconds"),
            "nb_troncons": len(segments), "longueur_km": round(longueur_km, 2),
        })
        return slug

    def dupliquer(self, slug_source, nouveau_libelle, description=""):
        nouveau = slugify(nouveau_libelle)
        if self.variante_existe(nouveau):
            raise ValueError(f"La variante « {nouveau} » existe déjà")
        src = next(v for v in self.lister_variantes() if v["nom"] == slug_source)
        for prefix in (PREFIX_TRONCONS, PREFIX_NOEUDS):
            lyr = self.couche(prefix + slug_source)
            self._ecrire(self._copie_memoire(lyr), prefix + nouveau)
        ref = self.lire_lignes(f"trafic_ref__{slug_source}")
        if ref:
            self.ecrire_lignes(f"trafic_ref__{nouveau}", SCHEMAS["trafic_ref"], ref)
        historique = self.lire_journal(slug_source)
        if historique:  # l'historique de la variante d'origine reste lisible dans la copie
            self.ecrire_lignes("journal_reseau", SCHEMAS["journal_reseau"],
                               self.lire_lignes("journal_reseau")
                               + [{**h, "variante": nouveau} for h in historique])
        self._maj_variante({
            "nom": nouveau, "libelle": nouveau_libelle,
            "description": description or f"Copie de {src['libelle']}",
            "parent": slug_source, "source": "copie",
            "cree_le": datetime.now().isoformat(timespec="seconds"),
            "nb_troncons": src["nb_troncons"], "longueur_km": src["longueur_km"],
        })
        return nouveau

    def supprimer(self, slug):
        """Supprime les couches d'une variante (retirer d'abord les couches du projet QGIS)."""
        md = QgsProviderRegistry.instance().providerMetadata("ogr")
        conn = md.createConnection(self.chemin, {})
        for prefix in (PREFIX_TRONCONS, PREFIX_NOEUDS):
            if conn.tableExists("", prefix + slug):
                conn.dropVectorTable("", prefix + slug)
        restantes = [v for v in self.lister_variantes() if v["nom"] != slug]
        self._ecrire_variantes(restantes)
        self._purger_dependances(slug)

    def _purger_dependances(self, slug):
        """Supprime le trafic de référence et le journal d'une variante (identifiants périmés)."""
        table = f"trafic_ref__{slug}"
        if self.table_existe(table):
            try:
                md = QgsProviderRegistry.instance().providerMetadata("ogr")
                md.createConnection(self.chemin, {}).dropVectorTable("", table)
            except Exception:
                pass  # une table orpheline est sans gravité si la variante est recréée plus tard
        if self.table_existe("journal_reseau"):
            lignes = self.lire_lignes("journal_reseau")
            reste = [l for l in lignes if l.get("variante") != slug]
            if len(reste) != len(lignes):
                self.ecrire_lignes("journal_reseau", SCHEMAS["journal_reseau"], reste)

    def maj_description(self, slug, texte):
        """Enregistre le commentaire d'une variante."""
        v = next((v for v in self.lister_variantes() if v["nom"] == slug), None)
        if v is None:
            raise ValueError(f"Variante « {slug} » introuvable")
        v["description"] = texte
        self._maj_variante(v)

    # -- champs, journal et référence des tronçons ---------------------------------------
    def assurer_champs(self, slug):
        """Ajoute aux variantes anciennes les champs récents (valeurs par défaut).

        Retourne True si des champs ont été ajoutés. Les attributs OSM (giratoires, ponts,
        tunnels, vitesse autorisée) n'existent que pour les réseaux téléchargés ensuite.
        """
        lyr = self.couche(PREFIX_TRONCONS + slug)
        if lyr is None:
            return False
        manquants = [c for c in CHAMPS_TRONCONS_AJOUTES if lyr.fields().indexOf(c[0]) < 0]
        if not manquants:
            return False
        pr = lyr.dataProvider()
        if not pr.addAttributes([QgsField(n, t) for n, t, _ in manquants]):
            raise RuntimeError("Ajout des nouveaux champs impossible dans le GeoPackage")
        lyr.updateFields()
        defauts = {lyr.fields().indexOf(n): d for n, _t, d in manquants if d is not None}
        pr.changeAttributeValues({f.id(): dict(defauts) for f in lyr.getFeatures()})
        return True

    def lire_journal(self, slug):
        return [l for l in self.lire_lignes("journal_reseau") if l.get("variante") == slug]

    def ajouter_journal(self, slug, tid, action, detail=""):
        lignes = self.lire_lignes("journal_reseau")
        lignes.append({"variante": slug, "date": datetime.now().isoformat(timespec="seconds"),
                       "tid": tid, "action": action, "detail": detail})
        self.ecrire_lignes("journal_reseau", SCHEMAS["journal_reseau"], lignes)

    def copier_ref_troncon(self, slug, tid_source, tid_nouveau):
        """Un tronçon coupé en deux garde le trafic de référence de l'original."""
        table = f"trafic_ref__{slug}"
        lignes = self.lire_lignes(table)
        src = next((l for l in lignes if l.get("tid") == tid_source), None)
        if src is not None:
            self.ecrire_lignes(table, SCHEMAS["trafic_ref"], lignes + [{**src, "tid": tid_nouveau}])

    def mettre_a_jour_stats(self, slug):
        """À appeler après édition manuelle du réseau : recalcule le nombre et la longueur."""
        lyr = self.couche(PREFIX_TRONCONS + slug)
        if lyr is None:
            return
        n, total = 0, 0.0
        a_actif = lyr.fields().indexOf("actif") >= 0
        for f in lyr.getFeatures():
            if a_actif and f["actif"] == 0:
                continue  # tronçon désactivé
            n += 1
            total += f.geometry().length()
        v = next((v for v in self.lister_variantes() if v["nom"] == slug), None)
        if v:
            v.update(nb_troncons=n, longueur_km=round(total / 1000.0, 2))
            self._maj_variante(v)


    # -- tables génériques (scénarios, ratios, programme, distribution, résultats) ----
    def lire_lignes(self, table):
        """Lignes d'une table sous forme de dicts (NULL -> None). [] si la table n'existe pas."""
        lyr = self.couche(table)
        if lyr is None:
            return []
        noms = [f.name() for f in lyr.fields()]
        lignes = []
        for f in lyr.getFeatures():
            ligne = {}
            for n in noms:
                v = f[n]
                ligne[n] = None if (v is None or v == NULL) else v
            lignes.append(ligne)
        return lignes

    def table_existe(self, table):
        return self.couche(table) is not None

    def ecrire_lignes(self, table, schema, lignes, type_geom="None", crs=None, geometrie=None):
        """Écrit (en écrasant) une table. Pour une couche, ``geometrie(ligne)`` -> QgsGeometry."""
        lyr = QgsVectorLayer(type_geom, table, "memory")
        if crs is not None:
            lyr.setCrs(crs)
        pr = lyr.dataProvider()
        pr.addAttributes([QgsField(nom, TYPES_CHAMPS[t]) for nom, t in schema])
        lyr.updateFields()
        feats = []
        for l in lignes:
            f = QgsFeature(lyr.fields())
            if geometrie is not None:
                g = geometrie(l)
                if g is not None:
                    f.setGeometry(g)
            f.setAttributes([l.get(nom) for nom, _ in schema])
            feats.append(f)
        pr.addFeatures(feats)
        self._ecrire(lyr, table)

    def remplacer_lignes_scenario(self, table, scenario, nouvelles, crs=None):
        """Remplace les lignes d'un scénario dans une table partagée (autres scénarios intacts)."""
        schema = SCHEMAS[table]
        gardees = [l for l in self.lire_lignes(table) if l.get("scenario") != scenario]
        toutes = gardees + [{**l, "scenario": scenario} for l in nouvelles]
        spatial = any(n == "x" for n, _ in schema)
        self.ecrire_lignes(table, schema, toutes, "Point" if spatial else "None",
                           crs if spatial else None, _point_xy if spatial else None)

    # -- scénarios ---------------------------------------------------------------
    def lister_scenarios(self):
        return sorted(self.lire_lignes("scenarios"), key=lambda r: r["cree_le"] or "")

    def ecrire_scenario(self, rec):
        autres = [r for r in self.lister_scenarios() if r["nom"] != rec["nom"]]
        self.ecrire_lignes("scenarios", SCHEMAS["scenarios"], autres + [rec])

    def dupliquer_scenario(self, source, libelle, crs):
        nouveau = slugify(libelle)
        src = next(r for r in self.lister_scenarios() if r["nom"] == source)
        if any(r["nom"] == nouveau for r in self.lister_scenarios()):
            raise ValueError(f"Le scénario « {nouveau} » existe déjà")
        for table in TABLES_SCENARIO:
            lignes = [l for l in self.lire_lignes(table) if l.get("scenario") == source]
            if lignes:
                self.remplacer_lignes_scenario(table, nouveau, lignes, crs)
        self.ecrire_scenario({
            "nom": nouveau, "libelle": libelle, "variante": src["variante"],
            "description": f"Copie de {src['libelle']}",
            "cree_le": datetime.now().isoformat(timespec="seconds")})
        return nouveau

    def supprimer_scenario(self, nom, crs=None):
        for table in TABLES_SCENARIO:
            if self.table_existe(table):
                self.remplacer_lignes_scenario(table, nom, [], crs)
        self.ecrire_lignes("scenarios", SCHEMAS["scenarios"],
                           [r for r in self.lister_scenarios() if r["nom"] != nom])
        md = QgsProviderRegistry.instance().providerMetadata("ogr")
        conn = md.createConnection(self.chemin, {})
        for t in self.tables_resultats(nom):
            try:
                conn.dropVectorTable("", t)
            except Exception:
                pass  # une table de résultats orpheline est sans gravité

    @staticmethod
    def tables_resultats(nom):
        return [f"res_{k}__{nom}" for k in ("arcs", "virages", "generation", "synthese", "journal")]

    # -- construction des couches ----------------------------------------------
    @staticmethod
    def _couche_troncons(segments, crs):
        lyr = QgsVectorLayer("LineString", "troncons", "memory")
        lyr.setCrs(crs)
        pr = lyr.dataProvider()
        pr.addAttributes([
            QgsField("id", QVariant.Int), QgsField("osm_id", QVariant.LongLong),
            QgsField("nom", QVariant.String), QgsField("highway", QVariant.String),
            QgsField("sens", QVariant.Int), QgsField("vitesse", QVariant.Int),
            QgsField("voies", QVariant.Int), QgsField("longueur", QVariant.Double),
            QgsField("u", QVariant.LongLong), QgsField("v", QVariant.LongLong),
            QgsField("note", QVariant.String),
        ] + [QgsField(n, t) for n, t, _ in CHAMPS_TRONCONS_AJOUTES])
        lyr.updateFields()
        feats = []
        for s in segments:
            f = QgsFeature(lyr.fields())
            f.setGeometry(s["geom"])
            f.setAttributes([s["id"], s["osm_id"], s["nom"], s["highway"], s["sens"],
                             s["vitesse"], s["voies"], round(s["longueur"], 1),
                             s["u"], s["v"], "",
                             s.get("vit_osm"), s.get("rond_point", 0), s.get("ouvrage", ""),
                             s.get("niveau", 0), 1, "osm"])
            feats.append(f)
        pr.addFeatures(feats)
        return lyr

    @staticmethod
    def _couche_noeuds(segments, crs):
        noeuds = {}
        for s in segments:
            pts = s["geom"].asPolyline()
            for nid, pt in ((s["u"], pts[0]), (s["v"], pts[-1])):
                if nid not in noeuds:
                    noeuds[nid] = [pt, 0]
                noeuds[nid][1] += 1
        lyr = QgsVectorLayer("Point", "noeuds", "memory")
        lyr.setCrs(crs)
        pr = lyr.dataProvider()
        pr.addAttributes([QgsField("id", QVariant.LongLong), QgsField("degre", QVariant.Int)])
        lyr.updateFields()
        feats = []
        for nid, (pt, degre) in noeuds.items():
            f = QgsFeature(lyr.fields())
            f.setGeometry(QgsGeometry.fromPointXY(pt))
            f.setAttributes([nid, degre])
            feats.append(f)
        pr.addFeatures(feats)
        return lyr
