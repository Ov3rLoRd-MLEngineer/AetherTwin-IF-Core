# mangastudio — studio de retouche anime

Intègre les modèles de Jérémy **HandSegNet** et **FootSegNet** (SAM ViT-B de Meta, décodeur de masque
affiné sur des images d'anime ; Apache 2.0). Chacun prend une boîte autour d'**une** main ou d'**un** pied et
rend un masque binaire, base d'une retouche locale (régénérer seulement la main ratée).

| Pièce | Fichier | État |
|---|---|---|
| Segmentation (module du Hub) | `segment.py`, `module.py` | modèle réel si `torch`, `segment-anything`, `safetensors` et les poids sont là ; sinon **simulation GrabCut** (OpenCV), toujours signalée |
| Nœuds ComfyUI | `comfyui_nodes/` | « Masque de main (HandSegNet) », « Masque de pied (FootSegNet) » ; dossier autonome à copier dans `ComfyUI/custom_nodes/` |
| Continuité inter-cases | `workflows/continuity.json` | format API de ComfyUI : IP-Adapter (identité du personnage) + ControlNet (trait de la nouvelle case), puis masque des mains pour contrôle. **À valider sur la machine GPU** |
| Interface | onglet **Studio** du tableau de bord | choisir l'image, tracer la boîte, obtenir le masque et un aperçu teinté |

## Licences (vérifiées le 17/11/2026)

- **Poids** (Hugging Face, `Ov3rLoRd-MLEngineer/*-anime-sdxl`) : Apache 2.0 (`LICENSE_WEIGHTS.txt`, métadonnées).
- **Code d'inférence** des dépôts GitHub d'origine : MIT (fichier `LICENSE`). Le README GitHub de FootSegNet
  annonce « Apache 2.0 » pour l'ensemble : à harmoniser par l'auteur. Le code de ce dossier est celui
  d'AetherTwin et suit la licence du projet.

## Poids

Non versionnés (375 Mo chacun). Par défaut : `models/mangastudio/handsegnet_vit_b_best.safetensors` et
`models/mangastudio/footsegnet_vit_b_best.safetensors` (dossier ignoré par Git), téléchargés depuis
`huggingface.co/Ov3rLoRd-MLEngineer/handsegnet-anime-sdxl` et `…/footsegnet-anime-sdxl`. Autre emplacement :
`config/local.yaml`, section `mangastudio`, clés `handsegnet_weights` et `footsegnet_weights`.

## Ce que le workflow de continuité demande

ComfyUI avec les nœuds `ComfyUI_IPAdapter_plus` (IP-Adapter), un modèle SDXL anime, un ControlNet SDXL
(trait ou pose) et nos nœuds. Les noms de modèles commençant par `A_CHOISIR_` sont à remplacer. Aucune
image n'a été générée avec ce workflow à ce jour : il est vérifié par sa structure seulement.

## Domaine d'entraînement

HandSegNet et FootSegNet ont été entraînés **uniquement sur des images générées par SDXL** (illustrations
anime en couleur). Sur une page de manga en noir et blanc, tramée ou photographiée, ils sortent de leur
domaine : les débordements constatés le 17/11/2026 (masques qui prennent un manteau ou une cape) viennent
probablement de là, et non d'un défaut du branchement. Pour juger leur qualité, les essayer sur des images
SDXL, leur domaine. (Précision de Jérémy, 17/11/2026.)

## Limites connues (d'après les fiches des modèles)

Une boîte par appel ; deux mains = deux boîtes (masques réunis). HandSegNet : IoU de validation 0,888 avec une
boîte exacte, 0,72 en moyenne avec une boîte trouvée automatiquement ; erreurs typiques : main en miroir,
doigts manquants. FootSegNet : IoU 0,928 avec une boîte exacte.
