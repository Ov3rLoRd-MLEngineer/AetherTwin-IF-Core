# chem_lab — labo de chimie Æther

Onglet **Outils → Labo de chimie** du Hub, ou sa fenêtre séparée (« Ouvrir le labo »). Tout tourne sur ce PC ;
les calculs sont exacts et faits en Python par le module, la page se contente d'afficher et d'animer.

## Tableau périodique

Les 118 éléments avec leur nom français, leur masse atomique (UICPA ; entre crochets, isotope le plus stable),
leur famille, leur électronégativité (Pauling) et leur état à 20 °C. Coloration au choix : famille,
électronégativité, état, masse. La recherche accepte un symbole, un numéro ou un nom (« Fe », « 26 », « fer »).
« Utiliser dans une formule » ajoute le symbole à la calculatrice de masse molaire.

## Équations et stœchiométrie

- **Masse molaire** et composition massique : parenthèses, crochets, hydrates (`CuSO4·5H2O`, `K4[Fe(CN)6]`).
- **Équilibrage exact** (algèbre linéaire en nombres entiers, SymPy) : coefficients les plus petits, charges
  comprises (`MnO4^- + Fe^2+ + H^+ -> Mn^2+ + Fe^3+ + H2O`). Flèches `->`, `→`, `=` ; états `(aq)`, `(s)`… acceptés.
  Si l'équation mélange plusieurs réactions indépendantes, le labo le dit au lieu d'inventer des coefficients.
- **Stœchiométrie** : quantités initiales (g ou mol) → réactif limitant, avancement, masses consommées, formées et
  restantes ; rendement réel en option.

## Solutions et pH

- pH **exact** d'un acide ou d'une base, fort ou faible : on résout l'électroneutralité, autoprotolyse de l'eau
  comprise (ainsi HCl à 10⁻⁸ mol/L donne bien pH 6,98 et non 8). Couples courants proposés.
- Tampon HA/A⁻ comparé à Henderson-Hasselbalch ; dilution C1·V1 = C2·V2 (la case vide est calculée) ;
  masse à peser pour préparer une solution.

## Titrage simulé

Acide fort ou faible titré par la soude, base forte ou faible par l'acide chlorhydrique : la courbe pH = f(V) est
calculée point par point, l'équivalence et la demi-équivalence (pH = pKa) sont marquées, et les indicateurs colorés
dont la zone de virage tombe dans le saut de pH sont proposés. « Verser » anime la burette (plus lentement près de
l'équivalence, comme au labo) et le bécher prend la couleur de l'indicateur choisi.

## Pour les agents (MCP)

Serveur MCP `aethertwin_chimie` (`python -I modules/chem_lab/mcp_server.py`) : `chem_element`, `chem_molar_mass`,
`chem_balance`, `chem_stoichiometry`, `chem_ph`, `chem_buffer`, `chem_titration`, `chem_dilution`,
`chem_preparation`. Un modèle local délègue ces calculs au lieu de les estimer. Commande Hub `hermes_register`
pour le brancher sur Hermes Agent ; pour Claude Code :

    claude mcp add --scope user chimie -- <python du Hub> -I modules/chem_lab/mcp_server.py

En cours : acides polyprotiques (H3PO4…), cinétique et équilibres en phase gaz, titrages d'oxydoréduction.
