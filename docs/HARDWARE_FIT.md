# Adéquation matérielle — AetherTwin (I&F Core)

Ce document dit ce qui tourne aujourd'hui sur le poste de développement, ce qui a été mesuré, où la
VRAM bloque, et ce qu'une seule carte de 32 Go changerait. Tout chiffre vient d'une mesure datée
(sources : `config/hardware_profiles.yaml`, `PROJECT_STATUS.md`). Ce qui n'a pas été mesuré est dit.

## 1. Le poste réel

| Élément | Valeur | Comment c'est connu |
|---|---|---|
| Système | Windows 10 Professionnel 10.0.19045 | `Get-CimInstance Win32_OperatingSystem`, 16/11/2026 |
| Carte 0 | NVIDIA GeForce RTX 5080, 16 303 Mio | `nvidia-smi`, 16/11/2026 |
| Carte 1 | NVIDIA GeForce RTX 5060 Ti, 16 311 Mio | `nvidia-smi`, 16/11/2026 |
| VRAM vue par Ollama | 31,8 Gio au total | journal de démarrage d'Ollama 0.40.16 |
| Mémoire vive | 32 Go | relevé lors de l'essai de Strata, 23/11/2026 |
| Serveur de modèles | Ollama 0.40.16, cache KV `q8_0`, flash attention, `keep_alive` 5 min | journal d'Ollama |

La RTX 5060 Ti en service est une ASUS Dual. Une troisième carte, une seconde RTX 5060 Ti 16 Go (ASUS Prime),
est déjà achetée mais **pas encore montée** : elle est dans sa boîte (déclaré par Jérémy, 25/11). Le profil
`tri_gpu_48gb_nvidia` existe dans `config/hardware_profiles.yaml` mais il est marqué **déclaré** : il
n'a jamais été observé. Tout ce qui suit concerne les **deux** cartes réellement branchées.

Aucun modèle Q8_0 n'est installé. Les trois Qwen (27B, 30B, 35B) sont en Q4_K_M : c'est la décision de
Jérémy tant que la VRAM totale est de 32 Go.

## 2. Ce qui tourne aujourd'hui, et les mesures

| Charge | Réglage | Mesure | Date et source |
|---|---|---|---|
| `qwen3-27b` (Q4_K_M), modèle par défaut | `num_ctx` 32 768 | **16,77 Gio** de VRAM ; première réponse en 10,9 s (chargement à froid compris) | 17/11, `/api/ps` d'Ollama |
| `qwen3-coder:30b-a3b` (Q4_K_M) | `num_ctx` 32 768 | **19,69 Gio** ; première réponse en 14,0 s | 17/11, `/api/ps` |
| `qwen2.5vl:7b` (vision : bulles de manga, écran de jeu) | `num_ctx` 4 096 | 6 464 Mio sur la RTX 5060 Ti ; image lue en 16,7 s à froid | 17/11, `nvidia-smi` |
| Réponse mot à mot de l'assistant (`qwen3-27b`) | — | premier mot à 16 s chargement compris, environ 30 morceaux par seconde ensuite | essai réel, J8 |
| HandSegNet (masque de main, `mangastudio`) | ViT-B | 2,8 Go de VRAM ; 0,17 s par masque une fois chargé (21,8 s au premier appel) | essai réel sur la RTX 5080, J7 |
| Strata, moteur secondaire « mélange d'experts » : Qwen3.6-35B-A3B UD-Q4_K_XL | contexte 64 K, RTX 5060 Ti seule | 36 à 48 jetons par seconde ; **21 à 24 Go de RAM** pris | 23/11, essai réel |
| Budget d'Inoue (gardienne de la VRAM) | marge de 10 % | 6,39 Go réservés sur 28,66 Go utilisables | 22/11, Hub de Jérémy |

Débit en jetons par seconde d'Ollama sur les gros modèles : **non mesuré**. Contexte rempli à
32 768 jetons : **non mesuré** (les mesures ci-dessus sont prises après une question courte).

## 3. Le mur de la VRAM

Le calcul n'est pas ce qui limite le projet. La mémoire des cartes, si.

1. **Un gros modèle ne tient pas sur une carte.** En Q4_K_M, avec un contexte de 32 768 jetons,
   `qwen3-27b` occupe 16,77 Gio et `qwen3-coder:30b` 19,69 Gio. Les deux dépassent les 16 Go d'une seule
   carte. Ollama les découpe donc sur les deux GPU. Chaque jeton traverse alors le bus PCIe entre les
   deux cartes. L'effet de ce découpage sur la vitesse n'a pas été isolé ici : il n'y a pas de carte plus
   grande pour comparer.
2. **Le contexte est fixé, pas laissé au défaut.** Ces modèles annoncent un contexte maximal de
   262 144 jetons. Laissé tel quel, ce contexte fait échouer l'allocation au chargement (constat déclaré
   par Jérémy au laboratoire Ov3rLoRd, voir `research/overlord_notes.md`). Le routeur fixe donc
   `num_ctx` à 32 768 pour chaque requête.
3. **Un seul gros modèle à la fois.** Le routeur (`core/llm_router.py`) décharge le gros modèle précédent
   avant d'en charger un autre. Mesuré le 17/11 : après déchargement, 0 Mio sur la RTX 5060 Ti. Inoue
   (`core/guardians/inoue.py`) garde 10 % de la VRAM totale en réserve et refuse, ou met en attente, un
   module qui dépasse le budget. Elle compte aussi un modèle chargé par un autre programme sur le même
   Ollama (bogue trouvé à l'essai réel, corrigé).
4. **La vision et le langage se disputent la place.** Pour une page de manga, `scantrad` lit les bulles
   avec `qwen2.5vl:7b` (6,3 Gio) puis traduit avec `qwen3-27b` (16,77 Gio). Ensemble : environ 23 Gio.
   Ça passe dans les 28,66 Go du budget, mais seulement en répartissant sur deux cartes, et sans place
   pour un troisième modèle (segmentation, Strata).
5. **La qualité est sacrifiée à la place.** Le profil « qualité » prévu au départ était le Q8_0. Il n'est
   pas installé : avec 32 Go, il prendrait la place de tout le reste. Le projet tourne donc en Q4_K_M.
6. **La RAM devient le mur suivant pour les « mélanges d'experts ».** Strata garde les experts du modèle
   en mémoire vive. Avec 32 Go de RAM, l'essai du 23/11 a provoqué des manques de mémoire jusque dans le
   navigateur. Une carte graphique de plus accélère ce moteur sans baisser la RAM demandée : il faudrait
   64 Go de RAM pour l'utiliser pleinement.

## 4. Ce qu'une seule carte de 32 Go simplifierait

Ce qui suit est un raisonnement à partir des mesures du paragraphe 2. **Rien de cela n'a été mesuré**
sur une carte de 32 Go : le projet n'en a jamais eu.

- **Un gros modèle et son contexte sur une seule carte.** 16,77 Gio et 19,69 Gio tiennent dans 32 Go.
  Plus de découpage entre deux cartes, plus de trafic PCIe entre elles pour chaque jeton.
- **Langage et vision ensemble, sur la même carte.** `qwen3-27b` + `qwen2.5vl:7b` ≈ 23 Gio : la chaîne de
  `scantrad` n'aurait plus à répartir ses deux modèles.
- **La seconde carte libérée pour autre chose.** Aujourd'hui, la RTX 5080 sert aussi au jeu et à OBS.
  Avec le gros modèle sur une carte de 32 Go, l'autre carte resterait au jeu, à la segmentation
  (HandSegNet, 2,8 Go) ou au moteur Strata.
- **Une planification plus simple pour Inoue.** Un seul domaine de mémoire au lieu de deux : le budget se
  calcule sur une carte, sans dépendre de la façon dont Ollama découpe un modèle.
- **Le Q8_0 redevient envisageable** pour le modèle de 27B, si sa taille réelle le permet. Elle n'a pas été
  mesurée : il faudra l'installer et la relever (`ollama show`, `/api/ps`).
- **L'image et la vidéo par IA, là où plusieurs cartes n'aident pas.** Ollama sait couper un modèle de
  langage en couches et les poser sur plusieurs cartes. Un modèle de diffusion (image ou vidéo, par exemple
  dans ComfyUI) ne se découpe pas ainsi : le modèle, ses encodeurs et son décodeur doivent tenir ensemble sur
  **une** carte. Avec des cartes de 16 Go, empiler les cartes ne donne donc pas plus de place à ces modèles ;
  une carte de 32 Go, si. Jérémy s'est beaucoup servi de ComfyUI et compte y revenir (déclaré, 25/11). Le
  dépôt n'a pas encore de module de génération d'image ou de vidéo : c'est un besoin de l'auteur, pas une
  mesure du projet.

## 4 bis. Le reste de la plateforme

La carte graphique n'est pas le seul plafond. Le paragraphe 3 l'a montré : avec 32 Go de RAM, le moteur
Strata (mélange d'experts) manque déjà de mémoire vive, et une carte de plus n'y change rien. Une évolution
cohérente du poste toucherait donc aussi la carte mère, le processeur et la mémoire, pour passer à **64 voire
128 Go de RAM** et accueillir trois cartes dans de bonnes conditions.

Une telle plateforme permettrait aussi de **répartir le matériel existant** sur deux postes au lieu d'un :

- un poste d'IA, avec la carte de 32 Go (ou les deux RTX 5060 Ti) et beaucoup de RAM, pour les gros modèles,
  Strata et ComfyUI ;
- le poste actuel, gardé pour le jeu et la diffusion, avec la RTX 5080 ; AetherTwin y resterait le Hub de
  jeu (WoW Assistant, overlay OBS) et appellerait le poste d'IA sur le réseau local.

Ce partage n'est pas écrit dans le code aujourd'hui : le Hub et Ollama tournent sur la même machine. C'est une
piste, décrite pour montrer où le projet pourrait aller, pas un résultat.

## 5. Ce qui n'est pas prouvé

- Aucun essai sur une carte de 32 Go, de quelque fabricant que ce soit.
- **Rien n'a été testé sur une carte Radeon.** Le projet cible NVIDIA et CUDA sous Ollama
  (`core/hardware/gpu_monitor.py` lit les cartes par `pynvml`). Sur une autre machine, le moniteur passe
  sur `nvidia-smi`, puis sur un état « inconnu » qui n'empêche jamais le démarrage du Hub. Aucun
  backend AMD n'a été écrit.
- Le gain réel du « tout sur une carte » face au découpage sur deux cartes : non chiffré.
- Le débit en jetons par seconde des gros modèles, et la VRAM à contexte rempli : non mesurés.
- La topologie à trois cartes (48 Go) : jamais observée (la troisième carte est achetée, pas montée).
- La génération d'image ou de vidéo (ComfyUI) : hors du dépôt, rien mesuré ici.
- Le partage entre un poste d'IA et un poste de jeu : une piste, rien d'écrit dans le code.

## 6. Refaire les mesures

```powershell
nvidia-smi --query-gpu=name,memory.total --format=csv
ollama show qwen3-27b:latest
# deux gros modèles chargés l'un après l'autre par le routeur, VRAM relevée par /api/ps
$env:AETHERTWIN_REAL_OLLAMA = "1"
.\.venv\Scripts\python.exe -m pytest tests/core/test_llm_router.py -k real_ollama -s
```

Le Hub montre aussi la mesure en direct : onglet **Accueil** (charge et VRAM de chaque carte, budget
d'Inoue, modèles chargés, bouton pour décharger un modèle).
