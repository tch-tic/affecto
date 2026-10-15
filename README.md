# Affectation trafic (plugin QGIS, prototype)

## Installation
QGIS 3.28+ : Extensions > Installer/Gérer les extensions > Installer depuis un ZIP > `affectation_trafic.zip`.
Aucune dépendance Python externe (téléchargement via l'API Overpass avec le réseau de QGIS, proxy inclus).
Le panneau s'ouvre via l'icône « Affectation trafic » (barre d'outils / menu Extensions).

## Onglet 1 « Réseau »
1. Choisir le GeoPackage du projet (nouveau ou existant) et le SCR projeté (Lambert-93 par défaut).
2. Périmètre : emprise de la carte, couche polygonale ou dessin à la main ; tampon en mètres.
3. Télécharger le réseau OSM (3 niveaux de détail) -> crée la variante nommée.
4. Variantes : afficher, dupliquer, supprimer ; style neutre ou sens de circulation.

## Onglet 1 « Réseau » : attributs OSM et modification

Attributs conservés au téléchargement : `vitesse` (utilisée), `vit_osm` (maxspeed, vide si absent),
`voies`, `rond_point` (pas de flèche), `ouvrage` (`pont` / `tunnel` / vide), `niveau` (tag layer).
Styles : ponts avec filet sombre au-dessus, tunnels en tirets dessous, tronçons désactivés en
tirets rouges, giratoires sans flèche (style « Sens de circulation »).

Outils de modification (variante affichée, validés tout de suite dans le GeoPackage) :
- **Inverser le sens** : tronçon à sens unique (champ `sens`, 1 <-> -1) ;
- **Double / unique** : double sens <-> sens unique dans le sens du tracé ;
- **Nouveau tronçon** : tracé à la souris + attributs ; extrémités accrochées aux nœuds, ou
  carrefour créé en coupant un tronçon proche (le trafic de référence est recopié sur les deux parties) ;
- **Supprimer / restaurer** : champ `actif` = 0, le tronçon reste dans la couche mais est ignoré
  par le calcul ; un second clic le restaure.
Chaque action est tracée dans la table `journal_reseau` (bouton « Historique des modifications »).
Commentaires : par variante (onglet 1) et par scénario (barre du haut).
Une variante créée avant cette version reçoit les nouveaux champs avec des valeurs par défaut ;
pour obtenir les attributs OSM, retélécharger sous un nouveau nom.

## Onglets 3 à 5 (Programme, Distribution, Affectation)
Un scénario = une variante de réseau + une programmation + des accès + des portes + une distribution.
- Programme : lots, typologies et quantités (ou flux saisis directement), ratios, accès des lots sur le réseau.
- Distribution : portes d'accès, parts émises/attirées par porte (par défaut, par lot, ou par lot|typologie).
- Affectation : plus court chemin en temps avec mouvements tournants, HPM et HPS, trafic de référence, bilan.
Un GeoPackage d'exemple prêt à l'emploi se génère avec `outils/preparer_exemple.py` (livré à part).

## Contenu du GeoPackage
`perimetre`, `variantes`, et par variante `troncons__<nom>` (champ `sens` : 0 double sens, 1 sens de numérisation, -1 inverse)
et `noeuds__<nom>`.

## Tests hors QGIS
`python tests/test_*.py` : analyse OSM, géométrie, règles d'édition, moteur d'affectation.
