# calc_cas — calculatrice à calcul formel

Calculatrice haut de gamme du Hub : **résultats exacts et approchés**, graphes, tableur et statistiques, et un
**outil de calcul exact pour les agents locaux** (un modèle Ollama délègue ses calculs au lieu de les inventer).
Tout tourne sur la machine : SymPy (BSD), NumPy (BSD), aucun service en ligne, aucune VRAM.

Inspiration fonctionnelle des calculatrices graphiques à calcul formel du commerce, **sans en reprendre le nom,
le logo, l'interface ni le logiciel** : l'identité visuelle (logo AetherTwin, graphite, sarcelle et ambre) est
celle du Hub ; aucune touche ni étiquette n'est copiée, seule l'organisation générale « écran + pavé de navigation
+ clavier à deux fonctions » est familière.

## Installation

Rien à faire de plus que le Hub : `sympy` est dans `requirements.txt` (déjà installé avec le venv).

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Puis tableau de bord → onglet **Outils** (le module démarre à la première utilisation), ou bouton
**Ouvrir la calculatrice** (aussi « Lancer » sur la carte du module) pour la fenêtre de bureau. Sans SymPy, le module
démarre quand même en mode dégradé et répond « moteur de calcul indisponible ».

Configuration facultative, section `calc_cas` de `config/local.yaml` :

```yaml
calc_cas:
  timeout_s: 10                       # délai maximal d'un calcul
  program_timeout_s: 10               # délai maximal d'un programme (bac à sable)
  program_memory_mb: 768              # mémoire maximale du processus des programmes
  hub_api: "http://127.0.0.1:5750"    # modèle local du Hub pour « Le modèle délègue » (vide = désactivé)
  model: ""                           # vide = modèle par défaut du Hub
```

## Fenêtre de la calculatrice

`python -m modules.calc_cas.app` (lancé par le Hub) ouvre `core/web/calc_app.html` dans **Edge en mode
application** (Chrome sinon, navigateur par défaut en dernier recours) : fenêtre sans barre d'adresse,
redimensionnable, qui retient sa taille (profil dédié `data/calc_cas/window-profile`). L'arrêt depuis le Hub ferme
la fenêtre (objet de tâche Windows qui lie Edge au lanceur).

- **Mise en page fluide** : en portrait, écran en haut et clavier en bas ; dès que la fenêtre est plus large que
  haute, écran à gauche et clavier à droite. Touches, polices et pavé suivent la largeur *et* la hauteur ; F2 ou
  « Clavier » masque le clavier pour un écran plein ; ◐ écran clair ou sombre.
- **Cinq applications** (onglets, `tab`, Ctrl+1…5) : Calculs, Graphes, Géométrie, Tableur, Programmes.
- **Clavier à deux fonctions** : `2nde` (ambre) donne la fonction secondaire de chaque touche (√, ln, sin⁻¹, ∫,
  lim, ≈, sto→…), `abc` bascule le clavier en lettres (2nde + abc : majuscules). `esc`, `menu` (fonctions selon
  l'application, recherche), `catalogue` (2nde + menu, Ctrl+K), `⌫` / effacer, `var`, `mode` (auto → exact →
  approché), `deg/rad`, `ans`, `rappel`, `x,t,θ` (variable selon le type de courbe).
- **Pavé de navigation** : dans Calculs, ▲▼ parcourent l'historique et OK recopie la saisie (2nde + OK : le
  résultat) ; dans Graphes, ◀▶▲▼ déplacent la fenêtre, ou la trace le long des courbes ; dans le Tableur, les cellules.
- **Calculs** : `2nde` + entrée (ou Maj+Entrée) = valeur approchée ; `expr → nom` stocke ; badge RAD/DEG.
- **Graphes** : 6 fonctions (y =, paramétrique, polaire), trace, zéros, extrema, intersection, tableau de valeurs
  (début, pas), fenêtre xmin…ymax, zooms standard, trigonométrique, repère orthonormé, glisser et molette.
- **Géométrie** (construction dynamique) : points, segments, droites, cercles (centre et point, ou circonscrit),
  polygones, milieu, perpendiculaire, parallèle, médiatrice, intersections (droites, segments, cercles) ; mesures
  de longueur, d'angle (radians ou degrés selon le badge), d'aire et d'équation, recalculées en direct quand on
  glisse un point libre. **Mesures exactes** à la demande (`√5`, `π/2`, `y = 3 − 3x/4`, cercle `(x − 1)² + (y − 1)² = 2`)
  grâce à la grille magnétique (points sur des valeurs simples). Supprimer retire aussi ce qui dépend de l'objet ;
  Ctrl+Z annule ; le pavé déplace le point sélectionné d'un pas de grille. Figure gardée dans la fenêtre.
- **Tableur** : listes l1…l4 (60 lignes), statistiques 1 et 2 variables, 6 régressions, courbe envoyée dans
  Graphes, colonnes envoyées dans Calculs (`l1 := […]`).
- **Programmes** : éditeur Python (numéros de ligne, Tab = 4 espaces, indentation automatique), Ctrl+Entrée
  exécute, Ctrl+S enregistre ; console avec `input()` interactif ; dessin (`plot`, `scatter`, `fplot`, `text`) ;
  `cas("…")` et `cas_value("…")` appellent le moteur exact ; 4 exemples ; programmes gardés dans la session.

### Bac à sable des programmes

Les programmes tournent dans un **processus séparé** (délai `program_timeout_s`, mémoire `program_memory_mb`),
après vérification de l'arbre syntaxique : modules autorisés `math`, `cmath`, `random`, `statistics` (copies
filtrées) ; pas de fichiers, réseau, `os`/`sys`, `open`, `eval`, `exec`, classes, `with`, `global`, ni de nom ou
d'attribut commençant par `_` (ni `gi_frame`, `f_globals`, `format`, `mro`…). Sorties bornées (100 000
caractères, 50 000 points). `input()` fonctionne par **rejeu** : le programme s'arrête à la première question,
puis est relancé avec les réponses déjà données et la même graine aléatoire (résultat identique).

## Fonctions disponibles

Saisie naturelle : `2x`, `x y`, `2(x+1)`, `sin x`, `x^2`, `5!`, `√2`, `π`, `×`, `÷`, `x²`, `≤`. Constantes `pi`, `e`, `i`,
`oo` (infini). `=` écrit une équation ; `:=` définit une variable ou une fonction ; `expr → nom` (ou `->`) stocke
un résultat ; `ans` = dernier résultat. Unité d'angle : radians par défaut, degrés au choix (`sin(90)` = 1,
`asin(1)` = 90).
Alias français acceptés (entre parenthèses).

| Domaine | Fonctions |
|---|---|
| Algèbre | `simplify` (simplifier), `expand` (développer), `factor` (factoriser), `cancel`, `apart`, `together`, `trigsimp`, `collect`, `subs` |
| Analyse | `diff(f, x, n)` (dériver), `integrate(f, x)` / `integrate(f, x, a, b)` (intégrer), `limit(f, x, a, "+"|"-")` (limite), `taylor(f, x, a, n)`, `sum(terme, k, a, b)` (somme), `product` |
| Équations | `solve(éq, x)`, `solve([éq1, éq2], [x, y])` (résoudre), `nsolve(éq, x, départ)` |
| Matrices | `[[1, 2], [3, 4]]`, `det`, `inv`, `transpose`, `eigenvals` (valeurs_propres), `eigenvects`, `rank`, `rref`, `trace`, `eye(n)`, `dot`, `cross`, `M^-1`, `M*N` |
| Complexes | `re`, `im`, `abs`, `arg`, `conj`, `polar(z)`, `expand_complex` |
| Arithmétique | `gcd` (pgcd), `lcm` (ppcm), `isprime`, `factorint`, `divisors`, `mod`, `binomial`, `floor`, `ceil` |
| Listes | `mean` (moyenne), `median`, `variance`, `stdev` (écart_type), `min`, `max`, `sum([…])` |
| Valeur approchée | `approx(expr, chiffres)` (alias `N`) ; chaque résultat numérique est aussi donné en approché |

Affichage : MathML natif du navigateur (aucune bibliothèque externe), copie en texte ou en LaTeX.

**Graphes** : `y = f(x)`, paramétriques `x(t), y(t)`, polaires `r(θ)` (variable `theta`) ; jusqu'à 8 courbes ;
glisser pour déplacer, molette ou boutons pour zoomer ; zéros, extrema et intersections dans la fenêtre, avec la
forme exacte quand elle se vérifie (`x = √2`), sinon la valeur décimale.

**Tableur et statistiques** : colonnes X, Y, effectifs (cases acceptant `1/3`, `sqrt(2)`) ; une variable
(n, moyenne, Σx, Σx², sx, σx, quartiles, médiane, étendue) ; deux variables (moyennes, covariance, r) ;
régressions linéaire, quadratique, cubique, exponentielle (a·bˣ), puissance (a·xᵇ), logarithmique, avec r²,
nuage de points et courbe tracés dans « Graphes ».

**Agents** (`agent.py`) : outils `cas_compute`, `cas_analyze_function`, `cas_statistics` (schémas JSON au format
« function calling »), sorties structurées `{ok, exact, approx, latex, error}`, session séparée de celle de
l'utilisateur. Trois portes :

- bus du Hub : `POST /modules/calc_cas/command/tool` avec `{"name": "cas_compute", "arguments": {"expression": "…"}}` ;
- serveur MCP stdio pour Hermes Agent ou tout client MCP : `.venv\Scripts\python.exe -m modules.calc_cas.mcp_server` ;
- `POST /modules/calc_cas/command/ask` `{"question": "…"}` : le modèle du Hub écrit `CAS: <expression>`, le moteur
  calcule, le modèle répond à partir des résultats exacts (fonctionne avec tout modèle, même sans support des « tools »).

## Exemples de démonstration

Liste complète (vérifiée par les tests) dans `demos.py`, aussi proposée dans l'onglet (« Exemples »).

| Saisie | Résultat exact | Approché |
|---|---|---|
| `integrate(e^(-x^2), x, -oo, oo)` | √π | 1.77245385091 |
| `sum(1/k^2, k, 1, oo)` | π²/6 | 1.64493406685 |
| `solve([2x + y = 5, x - y = 1], [x, y])` | [x = 2, y = 1] | |
| `factor(x^3 - 6x^2 + 11x - 6)` | (x − 3)(x − 2)(x − 1) | |
| `eigenvals([[2, 1], [1, 2]])` | {1: 1, 3: 1} | |
| `e^(i pi) + 1` | 0 | |
| `f(x) := x^3 - 3x` puis Graphes → Extrema | maximum (−1 ; 2), minimum (1 ; −2) | |
| Graphes `cos(x)` et `x` → Intersections | x ≈ 0.739085133215 (pas de forme exacte) | |
| Tableur → Exemple → y = a·bˣ | a ≈ 2.02, b ≈ 1.497, r² ≈ 0.9996 | |
| Agent : « Quelle est l'aire exacte entre y = x^2 et y = 2x ? » | le modèle délègue `solve` puis `integrate` → 4/3 | |

Essai réel (23/11/2026) : `qwen3-27b` via le Hub, 2 calculs délégués, réponse 4/3 en 22 s.

## Sécurité et robustesse

- La saisie n'est **jamais exécutée telle quelle** : SymPy la transforme en code Python, dont l'arbre syntaxique est
  vérifié (aucun accès d'attribut, aucun nom commençant par `_`, appels limités à des noms, pas de fonction anonyme)
  puis évalué sans `__builtins__`, avec une liste fermée de fonctions.
- Chaque calcul tourne dans un **processus séparé** (`worker.py`) : au-delà de `timeout_s`, il est tué et relancé,
  les définitions de l'utilisateur sont rejouées. `9^9^9` ou une intégrale sans fin ne bloquent ni le module ni le Hub.
- Toute erreur devient un message lisible (`Division par zéro`, `Matrice non inversible`, `La limite n'existe pas…`).

## Choix faits (options les plus simples)

- `i` est l'unité imaginaire et `e` la constante d'Euler : utiliser `k`, `n`… comme indices de somme.
- `limit` sans sens donné = limite des deux côtés ; si elles diffèrent, message « la limite n'existe pas ».
- Quartiles par la **méthode des demi-séries** (médiane exclue si l'effectif est impair) ; `sx` divise par n − 1,
  `σx` par n ; `variance()` de la saisie = variance de la population.
- r² des régressions non linéaires calculé sur les y d'origine (après ajustement par linéarisation).
- Les agents ont leur propre session (`agent`) : ils ne voient ni ne modifient les variables de l'utilisateur.
- Délégation par le modèle : protocole texte `CAS:` plutôt que les « tools » natifs, que le routeur du Hub ne
  transmet pas encore ; ainsi aucun changement au cœur du Hub.
- Fenêtre : Edge en mode application plutôt qu'un cadre graphique Python (pywebview n'est pas installé) : rien à
  ajouter aux dépendances, même page et même API que le tableau de bord.
- Programmes en Python restreint plutôt qu'un langage maison : connu des élèves, vérifiable par l'arbre syntaxique.
- `input()` par rejeu plutôt que par un dialogue en direct avec le processus : plus simple, et le délai maximal
  s'applique à chaque exécution.
- Réglages de l'écran (mode d'affichage, onglet, fonctions tracées, tableur, clavier masqué) gardés dans le
  stockage local de la fenêtre ; unité d'angle et programmes dans la session du module.
- Variables, fonctions, réglages, programmes et historique (200 derniers calculs) gardés dans `data/calc_cas/session.json` (ignoré par Git).

## Limites connues

- Les résultats exacts ne sont pas simplifiés de force : `(x^2 - 1)/(x - 1)` reste tel quel, écrire `simplify(…)`.
- Une primitive non élémentaire reste une intégrale (avec un avertissement) ; une intégrale définie de ce type reçoit
  une valeur approchée.
- La forme exacte des points remarquables d'un graphe est une **reconnaissance** (`nsimplify`) vérifiée à 50
  chiffres : sûre quand elle est donnée, mais absente pour des racines exactes plus compliquées.
- Graphes : 8 courbes (6 dans la fenêtre), échantillonnage à 600–700 points ; une asymptote très étroite peut être manquée.
- Pas de débogueur pas à pas pour les programmes.
- Géométrie : les mesures exactes partent des coordonnées affichées (converties en fractions) ; pour un point
  construit à coordonnées irrationnelles (intersection d'un cercle…), la « valeur exacte » est celle d'une fraction
  très proche. Pas de lieux géométriques, de transformations (symétrie, rotation) ni d'export de la figure.
- Programmes : `input()` rejoue le programme depuis le début (un programme très long avant sa question est donc
  refait) ; pas de classes ni de modules autres que math, cmath, random, statistics.
- L'interface a été vérifiée dans Edge (fenêtre d'application) et le navigateur intégré (Chromium) ; MathML demande
  un navigateur récent.

## Fichiers

| Fichier | Rôle |
|---|---|
| `engine.py` | analyse sûre, fonctions CAS, session, présentation (texte, LaTeX, MathML) |
| `worker.py` | processus de calcul avec délai maximal et rejeu des définitions |
| `graph.py` | échantillonnage des courbes, zéros, extrema, intersections |
| `stats.py` | statistiques et régressions |
| `agent.py` | outils pour agents, boucle de délégation |
| `mcp_server.py` | serveur MCP stdio |
| `sandbox.py` | bac à sable des programmes Python |
| `geometry.py` | mesures exactes de géométrie (distance, angle, aire, droites, cercles) |
| `app.py` | lanceur de la fenêtre (Edge ou Chrome en mode application) |
| `module.py` | module du Hub (commandes du bus, persistance) |
| `demos.py` | exemples de démonstration |
| `core/web/calc_cas.js`, `calc_cas.css` | onglet « Outils » du tableau de bord |
| `core/web/calc_app.html`, `.js`, `.css` | fenêtre de la calculatrice |
| `core/web/calc_geo.js` | application Géométrie de la fenêtre |

Tests : `.venv\Scripts\python.exe -m pytest tests/calc_cas`
