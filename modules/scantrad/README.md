# scantrad — traduction locale de manga en VO

> **Usage personnel uniquement.** Ce module traduit, sur ta machine, des pages que tu possèdes ou que tu as
> le droit de lire. Il ne télécharge rien, ne publie rien, et le dépôt ne contient **aucune page de manga
> protégée** : la page de test (`tests/data/scantrad/page_test.png`) est dessinée par
> `modules/scantrad/testpage.py`, avec des répliques écrites pour le projet. Ne diffuse pas de traductions
> d'œuvres sous droits sans l'accord de leurs ayants droit.

## Chaîne

| Étape | Implémentation actuelle | Remplaçable par |
|---|---|---|
| Détection des bulles | heuristique OpenCV (`detect.py`) : zones claires fermées contenant du texte | un modèle de détection appris (même signature) |
| OCR japonais | modèle de vision local **via le Hub** (`qwen2.5vl:7b`, contexte 4 096) | manga-ocr (demande PyTorch) |
| Effacement du texte | inpainting OpenCV (Telea), limité à l'intérieur de la bulle | LaMa |
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

## Limites connues

- Détection : les bulles sans contour sur fond blanc, le texte hors bulle et les onomatopées dessinées ne sont
  pas détectés ; le texte vertical est lu par le modèle de vision mais la réincrustation est horizontale.
- Mesures faites sur **une** page synthétique, propre. Une vraie page scannée (trame, bruit, bulles collées)
  n'a pas été essayée.
