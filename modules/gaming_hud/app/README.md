# WoW Assistant

Compagnon Python (Pygame) qui lit les données d'un addon WoW (HermesAssistant) via les SavedVariables.
Lecture seule : aucune automatisation du jeu.

## Onglets (touches 1 à 9 et 0)
Personnage · Talents et grimoire · Journal des quêtes · Sacs (+ banque de bataillon / de guilde) · Métiers ·
Hauts Faits · Collections du bataillon (Montures, Codex des mascottes, Jouets, Héritage, Transmoglyphe) ·
Historique d'activité (Évolution, Journal, Statistiques) · Réputations et monnaies · Semaine · Instances et Chambre ·
Hôtel des ventes · Bilans (combats) · Bestiaire · Hermes (coach)

## Commandes en jeu
- `/ha` : état                      - `/ha save` : écrit le fichier tout de suite (fait un /reload)
- `/ha scan [tout|achievements|statistiques|montures|mascottes|jouets|heritage|transmog|ensembles]` :
  analyses complètes, découpées pour ne pas gêner le jeu (automatiques ~45 s après la connexion si > 3 jours)
- `/ha auto <minutes>` / `/ha auto off` : /reload automatique prudent
- `/ha combatlog on|off` : journal de combat (pour le mode Focus)
- `/ha debug` : diagnostic

## Overlay et widgets (nouveau)
Bouton « Mode overlay » (onglet Personnage) ou raccourci global **F9** : fenêtre sans bordure, transparente, au premier plan.
Seuls les widgets sont visibles ; les zones vides laissent passer les clics vers WoW.
WoW doit être en mode « Fenêtré » ou « Fenêtré (plein écran) » (pas en plein écran exclusif).
- Widgets : Personnage, Équipement (infobulles), Quêtes, Assistant (conversation avec Hermes), Sacs, Métiers,
  Monnaies, Instances, Session. Glisser la barre de titre = déplacer ; coin bas-droit = redimensionner ;
  « − » = réduire ; « × » = fermer (réactivable dans Paramètres > Widgets). Disposition mémorisée dans `layout.json`.
- Raccourcis globaux par défaut : **F9** afficher/masquer l'overlay · **F10** verrouiller/déverrouiller · **F11** Mode Focus manuel
  (modifiables dans Paramètres > Overlay).
- Mode Focus : pendant un combat, chaque widget est gardé, réduit à sa barre de titre ou masqué (Paramètres > Widgets).
  Le combat est détecté avec le journal de combat officiel : activez-le une fois avec `/ha combatlog on`.

## Captures d'écran (vision) et voix
- **Capture** : bouton « Capture » (barre d'outils, widget Assistant, fenêtre d'envoi) ou **F7** : l'overlay se masque un instant,
  la fenêtre de WoW est capturée et jointe à la prochaine question (4 images maximum, réduites en JPEG).
- **Win + Maj + S** : toute image copiée dans le presse-papier vous est proposée (notification « Joindre / Ignorer »).
- **Micro** : bouton « Micro » (off → appuyer pour parler → activation vocale). Appuyer pour parler : maintenir **F8**
  (touche ou bouton de souris configurable). La phrase est transcrite puis envoyée à l'assistant avec les images jointes.
- **Reconnaissance (STT)** : serveur API compatible OpenAI (Open WebUI, faster-whisper-server...), programme local
  (whisper.cpp...) ou faster-whisper. **Voix (TTS)** : voix Windows, Piper, ou désactivée. Réglages : Paramètres > Voix / Vision.
- Dépendances : `pip install pillow sounddevice` (le micro est facultatif).

## Widgets web (Open WebUI, lecteur vidéo)
Widgets « Open WebUI » et « Lecteur vidéo » (Paramètres > Widgets > Actif, ou Paramètres > Web). Chaque page s'affiche dans un
**processus séparé** (`webhost.py`) dont la fenêtre suit la position du widget ; la zone du widget est transparente, la page web
est visible et cliquable à travers.
- Isolation : aucun code web dans l'appli, aucun pont JavaScript → Python, aucune commande système, aucun accès aux fichiers de
  l'appli (dossier de travail temporaire, environnement réduit, données web dans `cache/web/`), navigation limitée aux domaines
  autorisés (liste blanche). Ce n'est pas un bac à sable Windows complet : le processus garde les droits de votre session.
- Il n'existe volontairement pas d'extensions Python tierces : tout widget externe doit être une page web, donc isolée de la même façon.
- Nécessite `pip install pywebview` (WebView2 sur Windows 10/11). Si la fenêtre est décalée : Paramètres > Web > Échelle Windows.

## Données mémorisées
`cache/last_snapshot.json` garde le dernier état connu du personnage : l'appli l'affiche dès le lancement.
Une section vide (déconnexion, fichier en cours d'écriture) ne remplace jamais une section déjà connue.
Le bouton « Actualiser » (onglet Personnage) relit le fichier du jeu.

## Assistant IA (Hermes)
Paramètres généraux (onglet Personnage) : **Hermes Agent** (recommandé), serveur API compatible OpenAI (Ollama,
LM Studio, Open WebUI, Omniroute...). Réglages dans `settings.json` (l'ancien « Programme local » devient Hermes).
Boutons « Envoyer à Hermes » : quêtes, montures, mascottes, jouets, apparences, ensembles.

### Hermes Agent comme coach (onglet Hermes)
- **État** : Hermes trouvé, passerelle, modèle, API, skill, outils de jeu ; connexion Auto / API / CLI.
- **Mise en place** (un clic chacun, copie de sauvegarde du fichier de Hermes modifié) :
  1. « Installer le skill wow-coach » : consignes de coach dans `%LOCALAPPDATA%\hermes\skills\gaming\wow-coach` ;
  2. « Ajouter les outils de jeu (MCP) » : `hermes mcp add wow_assistant` → `hermes_mcp.py` (10 outils, lecture
     seule) ; à refaire si le dossier de l'appli change (le chemin y est enregistré) ;
  3. « Activer l'API de Hermes » (facultatif) : clé aléatoire dans le `.env` de Hermes (jamais affichée), puis
     « Relancer la passerelle (API) » (service en arrière-plan : fermer l'application Hermes ne la relance pas).
- **Sans l'API** : `hermes -z` (≈ 20 s par question, outils sans danger seulement, captures non transmises).
  **Avec l'API** : réponse au fil de l'eau, outils affichés, captures analysées, session visible dans Hermes ; une
  commande sensible demandée par Hermes attend « Autoriser » / « Refuser » dans l'appli.
- **Fichiers et liens** : « Joindre un fichier » ou glisser un fichier sur la fenêtre (texte : txt, md, lua, json,
  csv, log... lu par l'appli et envoyé comme données ; images) ; un lien dans la question est lu par Hermes.
- **Réflexion** : Rapide / Équilibrée (défaut) / Poussée, envoyée à chaque question ; « Hermes » garde son
  réglage (« high » est refusé par Qwen 3.5 : erreur 500).
- **Modèle** : Hermes exige au moins 64 000 jetons de contexte (Hermes > Paramètres > Fournisseurs > Points de
  terminaison > Contexte) ; sinon l'onglet explique l'erreur.
- **Overlay** : widgets « Assistant (Hermes) » (conversation) et « Coach Hermes » (questions en un clic,
  « Capture + avis », dernière réponse) ; même fil que l'onglet.
- **Base de connaissances** (vue « Connaissances » de l'onglet) : « Corriger la réponse » enregistre ce qui est
  juste ; vos corrections font foi et sont rappelées à Hermes à chaque question. Hermes cherche d'abord dans la base,
  vérifie en ligne (Wowhead...) et enregistre le fait avec son lien et la version du jeu ; à revérifier après 45 jours
  ou dès que le jeu change de patch (version lue dans `.build.info`, lecture seule). « C'est juste »,
  « Rejeter », « Supprimer », ou une règle ajoutée à la main. Fichier `%APPDATA%\WoWAssistant\coach_knowledge.json`
  (commun à toutes les copies de l'appli).

## Fichiers
HermesAssistant.toc/.lua (addon) · main.py · config.py · settings.py · llm.py · snapcache.py ·
lua_parser.py · game_connection.py · gamedata.py · character.py · quests.py · inventory.py · craft.py · history.py ·
wowhead.py · theme.py · icons_draw.py · ui.py · tabs.py · tabs_data.py · tabs_collections.py · tabutil.py ·
overlay.py · hotkeys.py · focus.py · widgets.py · widgets_builtin.py · vision.py · voice.py · webhost.py · webwidget.py ·
chatview.py · tabs_hermes.py · hermes_bridge.py · hermes_mcp.py (outils de jeu pour Hermes) · coach_knowledge.py · gameversion.py · routine.py · tabs_routine.py · combat_report.py · tabs_reports.py · simc.py · waypoints.py · hermes_skill/ ·
layout.json · chat_history.json · wowhead_links.json · recipes.json


## Nouveautés v9
- **Paramètres > Jeu** : choix du dossier `_retail_` (champ, « Parcourir… », « Détecter automatiquement » sur tous les disques), vérifications
  (WTF/Account, addon, fichier de données, journal de combat), appliqué à chaud et enregistré (`game.path` dans settings.json).
  Au démarrage, si le chemin n'est plus valide, l'appli cherche seule le jeu ; sinon elle ouvre cette page.
- **Overlay = 2e fenêtre** : la fenêtre principale reste sur son écran (sa position est mémorisée) ; la barre de widgets se place
  librement sur la zone du jeu. Écran de la fenêtre principale et de l'overlay au choix (Paramètres > Overlay).
  Boutons de la barre : « Fenêtre principale » (la ramène devant), « Fermer l'overlay ».
- **Voix** : choix du micro (Paramètres > Voix), test du micro avec état en direct, niveau et messages d'erreur précis
  (le message indique la commande pip pour CE Python si `sounddevice` manque).

## Nouveautés du 22/11/2026
- **Onglet « Hôtel des ventes »** : valeur estimée des sacs et des banques, recherche du prix d'un objet (avec
  l'historique Auctionator en courbe), « Conseil de vente (Hermes) ». Trois sources de prix, lues sans jamais rien
  écrire : **API Battle.net** (HdV officiel, mis à jour chaque heure), **TradeSkillMaster** (données téléchargées
  par l'application TSM : `TradeSkillMaster_AppHelper/AppData.lua`), **Auctionator** (vos scans).
- **Données des addons** (même onglet) : tous les addons installés et ce qu'ils enregistrent (SavedVariables),
  consultables en arbre ; « Expliquer (Hermes) ». Marche avec n'importe quel addon, sans code dédié.
- **Rendu officiel du personnage** à la place de la silhouette « Modèle 3D », et **image des montures** dans les
  Collections, par l'API Battle.net. Ce sont des images (pas un modèle qui tourne), mais ce sont les vraies :
  équipement et transmogrification actuels.
- **API Battle.net** : facultative ; un client gratuit créé sur https://develop.battle.net (client ID + secret, à
  saisir dans l'onglet Hôtel des ventes ; gardés dans `settings.json` sur ce PC). Cache dans `cache/bnet/`.
- **Mythique+** (onglet Instances et Chambre) : cote, clé en poche, meilleur niveau par donjon (vert : dans les
  temps), clés de la semaine, « Conseils M+ (Hermes) ». Demande l'**addon 1.7** (copiez le dossier
  `HermesAssistant` dans `Interface/AddOns`, puis /reload) ; l'addon exporte aussi la région du compte, qui
  règle l'API Battle.net seule.
- Plusieurs serveurs IA enregistrés (actif / inactif, fournisseur), modèles de tous les serveurs actifs.

## Nouveautés du 23/11/2026
- **Banque du personnage** (onglet Sacs) : addon **1.8** ; ouvrez une fois votre banque chez un banquier, puis
  /ha save. Comptée aussi dans « Valeur des banques » (Hôtel des ventes).
- **Collections** : aperçu plus grand. Mascottes en image (API Battle.net, comme les montures) ; jouets, héritage et
  apparences en grande icône (Battle.net ne propose pas de rendu des objets) ; ensembles : icônes de leurs pièces.
- **Personnage** : le rendu officiel est recadré pour remplir le cadre.

## Semaine : routine avant la remise à zéro (23/11/2026)
- Onglet **Semaine** : temps avant les remises à zéro (hebdomadaire et quotidienne), et ce qu'il reste à faire,
  détecté tout seul : Grande Chambre forte (emplacements et prochain palier), monnaies plafonnées à la semaine,
  quêtes hebdomadaires et journalières du journal, verrouillages, clés Mythique+.
- **Mes tâches** : ce que l'addon ne voit pas (Proie, commandes d'artisanat, logis...), hebdo ou quotidiennes,
  décochées toutes seules à la remise à zéro.
- **Autres personnages** : chacun est gardé dès que vous le connectez une fois (le fichier de l'addon ne garde que le
  dernier joué) ; une semaine d'avance est signalée « nouvelle semaine ».
- **Plan avec Hermes** : « J'ai 30 min / 1 h / 2 h » ; Hermes a aussi l'outil `wow_routine`. Widget d'overlay
  « Semaine ».
- Heures exactes de remise à zéro : **addon 1.10** (sinon calculées d'après la région). Fichier
  `%APPDATA%\WoWAssistant
outine.json` (hors du dépôt et du dossier du jeu).

## Points de route et montée de niveau (23/11/2026)
- Addon **1.10** : `/ha way x y` (zone actuelle) ou `/ha way <carte> x y` pose la flèche du jeu, sans TomTom.
- Journal des quêtes : « Copier le point de route » (coordonnées exportées par l'addon).
- Hermes : question « Niveau » (parcours de montée de niveau vérifié en ligne) ; les `/ha way` et `/way` de ses
  réponses deviennent des boutons sous la conversation : un clic copie, il reste à coller dans la discussion du jeu.

## WoW Forever et Questie (23/11/2026)
- Choisissez le dossier `_forever_` du jeu (Paramètres > Jeu) : l'appli affiche « WoW Forever » et cache ce qui
  n'existe pas sur Forever (Mythique+, Grande Chambre forte, décors du logis, Raidbots). L'assistant et Hermes
  sont prévenus (niveau 60, pas de vol...) pour ne pas conseiller ce qui n'existe pas.
- Addon **1.12** : se charge aussi sur Forever (Interface 16001, à confirmer en jeu) et lit le journal de quêtes
  avec l'ancienne API si la nouvelle manque.
- **Questie** (l'addon de base de quêtes, avec sa version Forever ; rien à voir avec le service payant « Questie
  AI ») : s'il est installé et chargé, l'addon lui demande, pour chaque quête du journal, à qui la rendre, où, et
  le niveau requis. Le détail de la quête et Hermes s'en servent ; une quête terminée a son point de route vers le
  PNJ. Lecture seule : Questie n'est jamais modifié.

## Décors du logis et rentabilité des recettes (23/11/2026)
- Addon **1.11** : `/ha scan logis` lit les décors du logis (compteurs du jeu, et la liste rangés / placés),
  affichés dans Collections → « Décors du logis ». La liste passe par une partie de l'API encore peu documentée :
  si elle reste vide, les compteurs restent justes.
- Hôtel des ventes → **« Rentabilité des recettes »** : coût des composants de base aux prix de l'Hôtel des ventes,
  vente nette (commission de 5 % déduite), bénéfice ; « Conseil (Hermes) » pour savoir quoi fabriquer. Il faut
  ouvrir une fois la fenêtre de chaque métier en jeu avec l'addon 1.11 (objet fabriqué par chaque recette).
  Estimation : rangs de qualité et composants optionnels non comptés.

## Raidbots (23/11/2026)
- Onglet Personnage (cadre d'équipement), **« Profil Raidbots »** : copie votre profil SimulationCraft (équipement porté avec ses bonus,
  enchantements, gemmes ; talents ; métiers) et ouvre le Droptimizer de raidbots.com : collez-le, lancez.
- **« Résultat Raidbots »** : sur la page du rapport, Ctrl+A puis Ctrl+C, puis ce bouton : le résultat est gardé
  dans les connaissances du coach (il fait foi) et Hermes résume les meilleures améliorations.
- Les objets des sacs ne sont pas dans le profil (l'addon n'exporte pas leur emplacement) : Top Gear ne les verra pas.

## Bilans de combat (23/11/2026)
- Onglet **Bilans** : après chaque boss et chaque clé Mythique+, un bilan tiré du journal de combat du jeu
  (/ha combatlog on) : durée, réussite, DPS / HPS / dégâts subis / interruptions / dissipations / morts de chaque
  membre du groupe, derniers coups reçus avant chaque mort, ce qui vous a fait le plus mal.
- « Analyser avec Hermes » (3 conseils concrets), « Copier le bilan » ; Hermes a aussi l'outil `wow_combat_reports`.
- Analyse après coup, hors du jeu (comme Warcraft Logs) ; rien n'est envoyé. Fichier
  `%APPDATA%\WoWAssistant\combat_reports.json`.

## Bestiaire (23/11/2026)
Onglet **Bestiaire** : créatures croisées et tuées, nombre de fois tuées, aptitudes, PV et ressource, niveau, rang,
lieu, butin (avec le pourcentage de corps qui l'ont donné), or moyen, image Battle.net, note personnelle, Wowhead,
Hermes. Il faut :
- le **journal de combat** du jeu : `/ha combatlog on` (une fois) ; pour les PV / niveau / carte, cochez aussi la
  journalisation avancée du jeu (Options > Système > Réseau) ;
- l'**addon 1.9** : il relève les créatures ciblées ou survolées et le butin des corps fouillés (puis /ha save).
Tout est gardé dans `bestiary.json`, à côté de l'appli.
Identifiants Battle.net : maintenant dans **Paramètres généraux > Jeu** (et gardés d'un lancement à l'autre).

## Vue 3D, Essayage, confirmation de fermeture (23/11/2026)
- **Vue 3D (facultative, désactivée par défaut)** : Paramètres généraux > Jeu > « Vue 3D (Wowhead) ». Le modèle
  s'affiche **dans** le cadre de l'aperçu (Personnage, Essayage, Montures, Mascottes, Bestiaire) : glisser pour
  tourner, molette pour zoomer, Ctrl+glisser pour déplacer ; bouton « Image » pour revenir au rendu Battle.net.
  Il faut pywebview (WebView2, déjà présent sous Windows 10/11) et les identifiants Battle.net. La visionneuse et
  les modèles viennent de Wowhead (usage personnel), relayés par un petit serveur local (127.0.0.1) avec un cache
  dans `cache/zam/`. Sans pywebview : bouton « Vue 3D » qui ouvre la page dans le navigateur.
- **Essayage** (Collections > Transmoglyphe) : votre personnage ; un clic sur une apparence la pose à sa place, un
  ensemble se pose en entier ; un clic sur une pièce dorée la retire ; « Tout retirer ».
- **Quitter** : la croix, Alt+F4 ou Échap demandent « Quitter WoW Assistant ? » (Entrée = oui, Échap = non).
- **Identifiants Battle.net** : gardés dans `settings.json` ET dans le profil Windows
  (`%APPDATA%\WoWAssistant\shared.json`) : une copie de l'appli dans un autre dossier les retrouve.
- **Assistant IA** (mode, serveurs enregistrés, modèle, réglages Hermes) : aussi dans ce fichier du profil ; le
  dernier enregistré, depuis n'importe quelle copie, l'emporte (recopier le dossier ne les efface plus).
- Bestiaire : sans la **journalisation avancée** du jeu, le journal de combat ne donne ni PV, ni niveau, ni carte
  (l'addon complète le niveau et la zone).

## Correctifs du 17/11/2026
- **Fermeture** : la croix de la fenêtre principale ferme bien l'appli, même après avoir ouvert (puis fermé) l'overlay.
- **Champs de saisie** : rester appuyé sur une touche la répète ; curseur déplaçable (flèches, Début, Fin, clic), touche Suppr ;
  **Ctrl+A / Ctrl+C / Ctrl+X / Ctrl+V** (et Maj+Inser) ; **clic droit** = menu Couper / Copier / Coller / Tout sélectionner.
  Un texte plus long que le champ défile pour garder le curseur visible. Un champ masqué (clé API) n'est jamais copié.
  La sélection est « tout ou rien » (pas de sélection partielle à la souris).
- **Widgets web** : on peut taper au clavier dans Open WebUI et le lecteur vidéo (la fenêtre n'était pas activable).
  En contrepartie, un widget web prend la saisie quand il s'ouvre : cliquez dans le jeu pour la lui rendre.
  Les sessions sont conservées dans `cache/web/<widget>/`.
- **Mise en page** : textes d'aide des Paramètres replacés sous leurs boutons ; barre d'outils de l'overlay élargie
  automatiquement pour que tous les boutons tiennent (libellés raccourcis : « Fenêtre », « Fermer », « Focus : auto »).
- Nouveau fichier : `clipboard.py` (presse-papier Windows, sans dépendance).
- **Clés API** : bouton « × » à droite du champ (Paramètres > Assistant IA, et Paramètres > Voix) : efface la clé du champ
  et de `settings.json` immédiatement.
- **Voix > faster-whisper** : le modèle se choisit par boutons (tiny, base, small, medium, large-v3) ; « whisper-1 », qui est
  un nom de l'API, n'est plus transmis à faster-whisper. Le message d'état en bas de la fenêtre est abrégé au lieu de
  chevaucher la mention de droite.
- **Lancement** : double-cliquer sur `Lancer WoW Assistant.bat` (Python 3.11). Les widgets web demandent `pywebview`
  dans CE Python : `py -3.11 -m pip install pywebview`.
