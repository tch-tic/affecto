"""Actions d'édition du réseau sur les couches QGIS (tronçons et nœuds), avec journal.

Les décisions (accrochage, découpe) viennent de regles_edition.py. Chaque action est validée
tout de suite dans le GeoPackage, sauf si la couche est déjà en édition manuelle : les
changements restent alors dans le tampon d'édition de l'utilisateur.
"""
from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
)

from . import regles_edition as regles
from .geom_utils import longueur


class ErreurEdition(Exception):
    """Message destiné à l'utilisateur."""


def _val(v, defaut=None):
    from qgis.core import NULL
    return defaut if (v is None or v == NULL) else v


def troncon_proche(layer, pt, tol):
    """Identifiant d'entité (fid QGIS) du tronçon le plus proche de ``pt`` à moins de ``tol``."""
    cible = QgsGeometry.fromPointXY(pt)
    rect = QgsRectangle(pt.x() - tol, pt.y() - tol, pt.x() + tol, pt.y() + tol)
    meilleur = None
    for f in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
        d = f.geometry().distance(cible)
        if d <= tol and (meilleur is None or d < meilleur[0]):
            meilleur = (d, f.id())
    return meilleur[1] if meilleur else None


def _en_edition(couches, action):
    """Exécute ``action()`` ; valide les couches qui n'étaient pas déjà en édition."""
    ouvertes = [c for c in couches if not c.isEditable()]
    for c in ouvertes:
        if not c.startEditing():
            raise ErreurEdition(f"La couche « {c.name()} » n'est pas modifiable.")
    try:
        action()
    except Exception:
        for c in ouvertes:
            c.rollBack()
        raise
    for c in ouvertes:
        if not c.commitChanges():
            erreurs = "; ".join(c.commitErrors())
            c.rollBack()
            raise ErreurEdition(f"Enregistrement impossible : {erreurs}")


class EditeurReseau:
    def __init__(self, projet, slug, troncons, noeuds):
        self.projet, self.slug = projet, slug
        self.troncons, self.noeuds = troncons, noeuds

    # -- outils internes ---------------------------------------------------------------------
    def _i(self, nom):
        return self.troncons.fields().indexOf(nom)

    def _journal(self, tid, action, detail=""):
        self.projet.ajouter_journal(self.slug, tid, action, detail)

    @staticmethod
    def _ligne(coords):
        return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in coords])

    def _entite(self, fid):
        f = self.troncons.getFeature(fid)
        if not f.isValid():
            raise ErreurEdition("Tronçon introuvable.")
        return f, int(_val(f["id"], 0))

    # -- actions sur un tronçon existant ----------------------------------------------------
    def inverser(self, fid):
        f, tid = self._entite(fid)
        sens = int(_val(f["sens"], 0))
        if sens == 0:
            raise ErreurEdition(f"Tronçon {tid} à double sens : rien à inverser. "
                                "Le passer d'abord en sens unique.")
        nouveau = regles.sens_inverse(sens)
        _en_edition([self.troncons],
                    lambda: self.troncons.changeAttributeValue(fid, self._i("sens"), nouveau))
        self._journal(tid, "inversion du sens", f"sens {sens} -> {nouveau}")
        return f"Tronçon {tid} : sens inversé."

    def basculer_double(self, fid):
        f, tid = self._entite(fid)
        sens = int(_val(f["sens"], 0))
        nouveau = regles.sens_bascule(sens)
        _en_edition([self.troncons],
                    lambda: self.troncons.changeAttributeValue(fid, self._i("sens"), nouveau))
        if nouveau == 0:
            self._journal(tid, "mise à double sens", f"sens {sens} -> 0")
            return f"Tronçon {tid} : double sens."
        self._journal(tid, "mise en sens unique", "sens 0 -> 1 (sens du tracé)")
        return f"Tronçon {tid} : sens unique dans le sens du tracé (outil « Inverser » pour changer)."

    def basculer_actif(self, fid):
        """Désactive un tronçon (conservé mais ignoré par le calcul) ou le réactive."""
        f, tid = self._entite(fid)
        actif = int(_val(f["actif"], 1))
        nouveau = 0 if actif else 1
        _en_edition([self.troncons],
                    lambda: self.troncons.changeAttributeValue(fid, self._i("actif"), nouveau))
        if nouveau == 0:
            self._journal(tid, "désactivation", "tronçon conservé, inutilisable")
            return f"Tronçon {tid} désactivé (cliquer à nouveau pour le restaurer)."
        self._journal(tid, "réactivation", "")
        return f"Tronçon {tid} restauré."

    # -- création --------------------------------------------------------------------------
    def creer(self, points, attributs, tol):
        """Crée un tronçon tracé par ``points`` (QgsPointXY, SCR de la couche).

        Les extrémités s'accrochent aux nœuds proches ; sinon à un tronçon actif proche, qui est
        coupé en deux pour créer le carrefour ; sinon un nouveau nœud est créé.
        """
        noeuds = {}
        for f in self.noeuds.getFeatures():
            p = f.geometry().asPoint()
            noeuds[int(f["id"])] = (p.x(), p.y())
        actifs, ids = {}, [0]
        for f in self.troncons.getFeatures():
            ids.append(int(_val(f["id"], 0)))
            if int(_val(f["actif"], 1)) != 1:
                continue
            g = f.geometry()
            if g.isNull() or g.isMultipart():
                continue
            actifs[int(f["id"])] = {"fid": f.id(),
                                    "coords": [(p.x(), p.y()) for p in g.asPolyline()]}
        try:
            plan = regles.planifier_creation(
                [(p.x(), p.y()) for p in points], noeuds, actifs, tol)
        except ValueError as exc:
            raise ErreurEdition(str(exc))

        tid_nouveau = regles.prochain_id(ids)
        tid_coupe = tid_nouveau + 1
        etat = {"nid": regles.prochain_id(noeuds)}
        extremites, coupures = {}, []

        def prochain_noeud():
            nid = etat["nid"]
            etat["nid"] += 1
            return nid

        def appliquer():
            for cle in ("debut", "fin"):
                e = plan[cle]
                if e["type"] == "noeud":
                    extremites[cle] = e["id"]
                    self._ajuster_degre(e["id"], +1)
                elif e["type"] == "nouveau":
                    nid = prochain_noeud()
                    self._ajouter_noeud(nid, e["point"], 1)
                    extremites[cle] = nid
                else:
                    nid = prochain_noeud()
                    self._couper(actifs[e["tid"]]["fid"], e, nid, tid_coupe)
                    self._ajouter_noeud(nid, e["point"], 3)
                    extremites[cle] = nid
                    coupures.append((e["tid"], tid_coupe))
            self._ajouter_troncon(tid_nouveau, plan["coords"], extremites["debut"],
                                  extremites["fin"], attributs)

        _en_edition([self.troncons, self.noeuds], appliquer)

        for tid_orig, tid_new in coupures:
            self.projet.copier_ref_troncon(self.slug, tid_orig, tid_new)
            self._journal(tid_orig, "découpe", f"coupé en {tid_orig} et {tid_new} pour raccordement")
        decrit = " / ".join(
            "nœud existant" if plan[c]["type"] == "noeud" else
            "carrefour créé" if plan[c]["type"] == "coupe" else "nouveau nœud"
            for c in ("debut", "fin"))
        self._journal(tid_nouveau, "création",
                      f"{attributs.get('highway', '')} {attributs.get('nom', '')} ; {decrit}".strip())
        return (f"Tronçon {tid_nouveau} créé ({longueur(plan['coords']):.0f} m ; {decrit}).")

    def _couper(self, fid, e, nid, tid_apres):
        """Coupe un tronçon : la partie avant garde l'identifiant, la partie après en reçoit un."""
        from qgis.core import NULL
        f = self.troncons.getFeature(fid)
        attrs = list(f.attributes())
        self.troncons.changeGeometry(fid, self._ligne(e["avant"]))
        self.troncons.changeAttributeValue(fid, self._i("v"), nid)
        self.troncons.changeAttributeValue(fid, self._i("longueur"), round(longueur(e["avant"]), 1))
        apres = QgsFeature(self.troncons.fields())
        for nom, valeur in (("id", tid_apres), ("u", nid),
                            ("longueur", round(longueur(e["apres"]), 1)), ("origine", "coupe")):
            i = self._i(nom)
            if i >= 0:
                attrs[i] = valeur
        i_fid = self._i("fid")
        if i_fid >= 0:
            attrs[i_fid] = NULL  # clé primaire attribuée par le GeoPackage
        apres.setAttributes(attrs)
        apres.setGeometry(self._ligne(e["apres"]))
        self.troncons.addFeature(apres)

    def _ajouter_troncon(self, tid, coords, u, v, a):
        f = QgsFeature(self.troncons.fields())
        f.setGeometry(self._ligne(coords))
        valeurs = {
            "id": tid, "osm_id": None, "nom": a.get("nom", ""), "highway": a.get("highway", ""),
            "sens": int(a.get("sens", 0)), "vitesse": a.get("vitesse", 30), "vit_osm": None,
            "voies": a.get("voies"), "rond_point": 0, "ouvrage": a.get("ouvrage", ""),
            "niveau": 0, "longueur": round(longueur(coords), 1), "u": u, "v": v,
            "note": "", "actif": 1, "origine": "ajout",
        }
        for nom, valeur in valeurs.items():
            i = self._i(nom)
            if i >= 0:
                f.setAttribute(i, valeur)
        self.troncons.addFeature(f)

    def _ajouter_noeud(self, nid, pt, degre):
        f = QgsFeature(self.noeuds.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt[0], pt[1])))
        f.setAttribute(self.noeuds.fields().indexOf("id"), nid)
        f.setAttribute(self.noeuds.fields().indexOf("degre"), degre)
        self.noeuds.addFeature(f)

    def _ajuster_degre(self, nid, delta):
        req = QgsFeatureRequest().setFilterExpression(f'"id" = {int(nid)}')
        for f in self.noeuds.getFeatures(req):
            i = self.noeuds.fields().indexOf("degre")
            self.noeuds.changeAttributeValue(f.id(), i, int(_val(f["degre"], 0)) + delta)
            break
