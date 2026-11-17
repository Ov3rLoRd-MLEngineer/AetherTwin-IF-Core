# scantrad — traduction locale de manga en VO

> **Usage personnel uniquement.** Ce module traduit, sur ta machine, des pages que tu possèdes ou que tu as
> le droit de lire. Il ne télécharge rien, ne publie rien, et le dépôt ne contient **aucune page de manga
> protégée** : la page de test (`tests/data/scantrad/page_test.png`) est dessinée par
> `modules/scantrad/testpage.py`, avec des répliques écrites pour le projet. Ne diffuse pas de traductions
> d'œuvres sous droits sans l'accord de leurs ayants droit.

## Chaîne

| Étape | Implémentation actuelle | Remplaçable par |
|---|---|---|
| Mise à l'échelle | une page de moins de 1 100 px de haut est agrandie (une capture réduite rend les caractères flous) | — |
| Détection du texte | `detect_text_blocks` (OpenCV) : caractères d'encre sur papier clair, regroupés en colonnes ou lignes, colonnes d'une même bulle fusionnées ; la bulle = la plage claire autour | un modèle de détection appris (même signature) ; `detector: bubbles` = ancienne heuristique des bulles fermées |
| OCR japonais et tri | modèle de vision local **via le Hub** (`qwen2.5vl:7b`, contexte 4 096) ; « AUCUN » ou aucun caractère japonais = faux positif écarté ; seconde lecture plus large si la première échoue | manga-ocr (demande PyTorch) |
| Effacement du texte | inpainting OpenCV (Telea) de l'encre fine du bloc (caractères, ponctuation, furigana), jamais des contours ni du dessin ; seulement pour les blocs validés par l'OCR | LaMa |
| Traduction | modèle local par défaut du Hub, un appel par page, glossaire de la série | tout modèle d'Ollama |
| Réincrustation | Pillow : taille ajustée, retours à la ligne, centrage | — |

Chaque étape est un objet passé à `Scantrad` (`pipeline.py`) : on en change une sans toucher aux autres.
Rien ne part sur Internet : l'OCR et la traduction passent par le routeur du Hub sur `127.0.0.1`.

## Utilisation

Le Hub doit tourner (raccourci **AetherTwin** du bureau, ou `Lancer AetherTwin.bat`). Depuis le dossier du projet :

```bat
.venv\Scripts\python.exe -m modules.scantrad tests\data\scantrad\page_test.png --series demo
.venv\Scripts\python.exe -m modules.scantrad --screen 100,100,800,1200 --series demo
.venv\Scripts\python.exe -m modules.scantrad --glossary demo --add "ユキ=Yuki"
```

Le glossaire de chaque série est dans `data/scantrad/glossaires/<série>.json` (ignoré par Git) : noms des
personnages, termes, ton. Seules les entrées présentes dans la page sont données au modèle.

## Mesures (page de test, 17/11/2026, RTX 5080 + RTX 5060 Ti)

| Étape | Temps |
|---|---|
| Détection | 0,013 s |
| OCR (5 bulles, chargement du modèle de vision compris) | 10,4 s |
| Effacement | 0,04 s |
| Traduction (`qwen3-27b`, chargement compris) | 13,0 s |
| Réincrustation | 0,035 s |
| **Total** | **23,6 s** |

VRAM totale au plus haut : 26 153 MiB sur 32 614 (modèle de vision et modèle de traduction chargés ensemble).
OCR exact sur les 5 bulles. Résultat : `docs/captures/scantrad_page_test_fr.png`.

## Essai sur une vraie page (17/11/2026)

Page de magazine photographiée, 443 × 451 px (fournie par Jérémy, **non versionnée**) : 11 blocs détectés,
7 écartés par l'OCR (dessin, pétales), 4 bulles traduites dans la bulle, japonais effacé, dessin intact.
Environ 6 à 26 s selon que les modèles étaient déjà chargés. Ratés : « 私い!? » (écriture manuscrite) et
« 本当に » (rogné au bord de l'image) ; une lecture approximative (ちゃんと lu ちやと) qui fausse un peu la
traduction. Premier essai, avant ce travail : une seule bulle trouvée, texte non effacé.

## Limites connues

- Les onomatopées dessinées et le texte manuscrit ne sont pas traduits ; le texte posé sur le dessin (hors
  papier clair) n'est pas détecté.
- La réincrustation est horizontale, même quand le texte d'origine est vertical.
- La qualité de la traduction dépend de l'OCR : une lecture fausse donne une phrase fausse, sans alerte.
