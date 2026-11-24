# data_lab — explorateur de données Æther

Onglet **Outils → Explorateur de données** du Hub, ou sa fenêtre séparée (« Ouvrir l'explorateur »). Un tableur
local : les formules sont calculées en Python par le module (le même moteur sert aux agents par MCP), la page
affiche la grille, les graphiques et les résultats. Rien ne sort du PC.

## Le tableur

- Saisie : clique une cellule et tape (ou double-clic, Entrée, F2) ; Entrée valide et descend, Tab va à droite,
  Échap annule. La barre **fx** montre et modifie le contenu brut. Pendant qu'on écrit une formule, un clic sur une
  cellule insère sa référence.
- Une formule commence par `=` ; arguments séparés par `;` (ou `,`), point décimal dans les formules ; dans une
  cellule de valeur, `3,5`, `1 234,5` et `50%` sont compris. Références `A1`, absolues `$A$1`, plages `A1:C10`.
- Plus de 80 fonctions, noms français et anglais : `SOMME`/`SUM`, `MOYENNE`, `SI`, `ET`, `NB.SI`, `SOMME.SI`,
  `ECARTYPE`, `MEDIANE`, `PENTE`, `ORDONNEE.ORIGINE`, `PREVISION`, `COEFFICIENT.CORRELATION`, `ARRONDI`, `LOG`,
  `ALEA`, `LOI.NORMALE`… (liste complète dans l'onglet **Formules**).
- **Équations** dans une cellule : `=RESOUDRE("x^3-2*x-5";2)` (racine près de 2), `=DERIVEE("x^2*SIN(x)";1)`,
  `=INTEGRALE("EXP(-x^2)";0;3)`. La variable est `x` ; l'expression peut lire des cellules (`"B1*x^2-3"`), donc la
  solution suit quand on change un paramètre.
- Erreurs lisibles (survol) : `#DIV/0!`, `#VALEUR!`, `#NOM?`, `#CYCLE!`, `#NUM!`, `#FORMULE!`, `#N/A`.
- Copier-coller avec Excel, LibreOffice ou un tableau web (Ctrl+C / Ctrl+V, texte tabulé). Entre deux cellules
  de l'explorateur, les formules suivent leurs références relatives. **Ctrl+D** / **Ctrl+R** recopient vers le
  bas / à droite, **Figer en valeurs** remplace des formules par leur résultat, **Ctrl+Z** annule.
- Classeurs enregistrés sur ce PC (`data/data_lab/workbooks`), brouillon gardé dans la fenêtre. **Importer** un
  CSV (séparateur deviné) ou un classeur Excel `.xlsx` (première feuille, formules comprises) ; **Exporter CSV**.

## Les outils (panneau de droite)

- **Graphique** : nuage de points, courbe ou barres ; « Depuis la sélection » prend la 1re colonne en X, les
  autres en Y et reconnaît une ligne de titres.
- **Ajustement** : linéaire, polynôme (degré 1 à 6), exponentiel, puissance, logarithme. Équation, coefficients,
  R², courbe superposée aux mesures, et **Insérer** écrit le modèle comme formule dans la feuille (à recopier).
- **Simulation** :
  - *balayage* : fait varier une cellule d'entrée et trace les sorties recalculées (copie possible en tableau) ;
  - *Monte-Carlo* : des entrées tirées au hasard (lois normale, uniforme, triangulaire, lognormale,
    exponentielle) ; moyenne, écart type, centiles, histogramme et probabilité de dépasser un seuil.
- **Valeur cible** : quelle valeur d'entrée donne le résultat voulu (résolution numérique de la formule).
- **Statistiques** d'une plage (quartiles, histogramme) ; **Trier** une plage de valeurs ; **Filtrer**
  l'affichage (`>10`, `<>0`, `=Paris`, `contient:lyon`).

Le menu **Exemples** ouvre des classeurs commentés : chute libre (ajustement d'une parabole, g retrouvé),
prêt immobilier (Monte-Carlo sur le taux, valeur cible sur la mensualité), équations, notes d'une classe.

## Pour les agents (MCP)

Serveur MCP `aethertwin_donnees` (`python -I modules/data_lab/mcp_server.py`) : `data_list_workbooks`,
`data_read_workbook`, `data_write_cells`, `data_write_table`, `data_evaluate`, `data_fit`, `data_sweep`,
`data_monte_carlo`, `data_goal_seek`. Un modèle local lit et remplit les classeurs, et laisse le moteur faire les
calculs. Commande Hub `hermes_register` pour Hermes Agent ; pour Claude Code :

    claude mcp add --scope user donnees -- <python du Hub> -I modules/data_lab/mcp_server.py

En cours : plusieurs feuilles par classeur, mise en forme des cellules, questions en français à un modèle local
depuis la fenêtre, solveur d'optimisation à plusieurs variables.
