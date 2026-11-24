# voice — voix locale d'AetherTwin

Parler au micro et entendre les réponses, partout dans le Hub et dans les outils branchés dessus, sans rien envoyer
hors du PC. Le module regroupe :

- **l'écoute** : Whisper local (faster-whisper, modèle « small » sur le processeur par défaut) ;
- **la synthèse** : Piper (voix françaises libres, environ 15 fois plus rapide que le temps réel) et, en secours, la
  voix de Windows ;
- **les profils de voix** : un moteur, une voix (et un locuteur pour les voix multiples), une vitesse et des effets ;
- **les effets** : hauteur, graves, aigus, robot, radio, écho, salle, trémolo, volume. Ce sont les mêmes réglages
  pour les voix de synthèse (sur le serveur, `effects.py`) et pour ta propre voix en direct (dans la page, Web
  Audio) ;
- **le studio audio** : un synthé et un séquenceur, le modulateur vocal en direct et la gestion des voix ;
- **la conversion de voix (IA)** : donner ton timbre à une voix de synthèse ou à un enregistrement, à partir de ta
  voix enregistrée dans le studio, avec consentement ;
- **la sortie vers VB-Cable** pour Discord, un jeu ou OBS ;
- **MCP** : le serveur `aethertwin_voice` pour Hermes Agent ou tout client MCP.

## Où s'en servir

| Endroit | Ce qu'on y fait |
|---|---|
| Hub → **Assistant** | bouton 🎙 « Parler » (clic pour commencer, clic pour envoyer, Échap pour annuler) ; case « lire les réponses à voix haute » ; choix de la voix ; volume ; bouton « Silence » (ou Échap). La réponse est lue phrase par phrase pendant que le modèle écrit ; les blocs de code ne sont pas lus. |
| Hub → **Outils → Studio audio** (ou sa fenêtre) | synthé et séquenceur, modulateur vocal, profils de voix, installation de Piper, conversion vers ta voix (onglet « Ma voix (IA) »), VB-Cable, branchement chez Hermes |
| **WoW Assistant** → Paramètres → Voix | « Voix (TTS) » : **Voix du Hub** (adresse du Hub et profil, vide = celui de l'assistant) ; « Reconnaissance » : Serveur API avec l'adresse `http://127.0.0.1:5750/v1` |
| **Tes autres outils IA** | API compatible OpenAI du Hub, voir plus bas |
| **Hermes Agent** | outils MCP `voice_speak`, `voice_stop`, `voice_profiles`, `voice_set_default`, `voice_save_profile` |

## Installer les voix

Studio audio → **Voix** → « Installer Piper et les voix françaises » (ou la commande `install` du module). Les
fichiers viennent uniquement des dépôts officiels, à des adresses fixes, et vont dans `data/voice/piper/` (hors du
dépôt Git, environ 300 Mo) :

| Fichier | Source | Licence |
|---|---|---|
| `piper.exe` 2023.11.14-2 | github.com/rhasspy/piper | MIT ; il contient espeak-ng (GPL-3), lancé comme programme séparé |
| `fr_FR-siwis-medium` | huggingface.co/rhasspy/piper-voices, révision v1.0.0 | données SIWIS : CC-BY 4.0 |
| `fr_FR-upmc-medium` (Jessica, Pierre) | idem | CC-BY-SA 4.0 |
| `fr_FR-gilles-low` | idem | CC0 |
| `fr_FR-mls-medium` (125 voix) | idem | Multilingual LibriSpeech : CC-BY 4.0 |

La voix « tom » est écartée à cause de sa licence (AGPL). La révision v1.0.0 des voix est imposée : la
configuration de la branche principale n'est pas lisible par ce binaire de Piper.

L'écoute demande faster-whisper : `scripts\setup.ps1 -Voice` (déjà utilisé par l'onglet Traduction).

## Profils

Gardés dans `data/voice/profiles.json`, partagés par le Hub, le studio, WoW Assistant et le serveur MCP.

- **Synthèse** (voix des réponses) : aether, narrateur, fuma, inoue, robot, radio, windows, plus les tiens.
- **Micro** (ta voix dans le modulateur) : ma_voix, ma_voix_grave, ma_voix_robot, ma_voix_radio, plus les tiens.
- Un profil intégré modifié devient un profil personnel ; le supprimer rend l'original.
- Si Piper ou la voix d'un profil manque, la voix de Windows prend le relais. L'en-tête `X-Voice-Fallback: 1`
  le signale et la page l'indique.
- Toutes les voix de synthèse sortent au même volume (−23 dB en moyenne, crêtes à 70 % au plus).

## Le modulateur vocal (ta voix en direct)

Studio audio → **Modulateur vocal** :

1. « Activer le micro ».
2. Choisis un profil « micro », ou règle les curseurs puis « Enregistrer sous… ».
3. Choisis la sortie.

La latence est d'environ 50 ms. La hauteur est changée par un AudioWorklet (`core/web/audio_worklet.js` : deux têtes
de lecture qui glissent, fenêtre de 40 ms), sans changer le débit. Les autres effets sont des nœuds Web Audio. La
voix modifiée peut être enregistrée en `.webm`.

Ta voix n'est jamais envoyée au serveur par le modulateur.

### VB-Cable (Discord, jeux, OBS)

VB-Cable (VB-Audio, donationware) n'est **pas** fourni. La page donne seulement :

- le lien vers son site officiel (`https://vb-audio.com/Cable/`) ;
- un bouton « Vérifier l'installation ». Le serveur cherche un périphérique « VB-Audio » et la page cherche la
  sortie « CABLE Input ».

Une fois VB-Cable installé :

1. Choisis la sortie « CABLE Input » ici.
2. Dans Discord ou le jeu, choisis le micro « CABLE Output ».

« m'écouter » garde une copie de ta voix sur ta sortie par défaut. Un casque est conseillé.

### NVIDIA Broadcast

Si NVIDIA Broadcast est installé, son micro « Microphone (NVIDIA Broadcast) » retire l'écho des enceintes et les voix
autour. Le modulateur, la dictée de l'Assistant et l'enregistrement de ta voix le choisissent d'eux-mêmes et coupent
alors les filtres du navigateur, qui feraient double emploi. Ne mets pas « Speakers (NVIDIA Broadcast) » en sortie du
modulateur : il effacerait les effets.

## Ma voix (conversion par IA)

Studio audio → **Ma voix (IA)**. La conversion garde tes paroles et ton intonation, et remplace le timbre par celui
d'une voix de ta banque. Elle sert à :

- donner ta voix à une voix de synthèse : onglet **Voix** → profil → **Timbre** → ta voix. L'Assistant, WoW
  Assistant, Hermes et l'API parlent alors avec ton timbre ;
- convertir une phrase dite au micro, puis la réécouter ou l'exporter en WAV.

Le moteur est kNN-VC (MIT). WavLM-Large découpe la parole en vecteurs ; chacun est remplacé par la moyenne de ses
quatre plus proches voisins pris dans tes enregistrements ; un vocodeur HiFi-GAN refait le son. Il n'y a rien à
entraîner : la voix s'améliore à mesure que tu ajoutes des prises.

### Installer

Bouton **Installer la conversion (1,3 Go)**. Les deux fichiers de poids viennent des publications officielles de
kNN-VC. Leur taille et leur empreinte SHA-256 sont vérifiées, ils sont chargés sans exécuter de code
(`weights_only`) et rangés dans `data/voice/knnvc/` (hors du dépôt). PyTorch doit être présent dans l'environnement.

### Enregistrer ta voix

1. **Nouvelle voix** : ton prénom, un nom, puis l'attestation à cocher.
2. **Phrase de consentement** : la page affiche « Je m'appelle …, c'est ma propre voix, et j'accepte qu'AetherTwin
   l'apprenne sur cet ordinateur. » Dis-la toi-même.
3. **Textes à lire** : une phrase à la fois, à voix normale. 30 s de lecture rendent la voix utilisable ; 3 à 5
   minutes la rendent nettement plus fidèle.

Whisper vérifie chaque prise : si le texte entendu ne correspond pas au texte affiché, la prise est refusée. Il n'y a
pas d'importation de fichier. Un enregistrement de quelqu'un d'autre (vidéo, message vocal) ne passe donc pas, puisqu'il
faudrait qu'il contienne exactement ces phrases. Seule ta voix, ou celle d'une personne présente qui a donné son accord
et lit elle-même la phrase de consentement, entre dans la banque. Tout reste dans `data/voice/bank/` sur ce PC. Une
prise ou une voix entière se supprime depuis la page.

### Vitesse

Sur le processeur (par défaut, la VRAM reste aux modèles de langue) : environ 15 s au premier usage (chargement),
puis environ 1,6 s pour 5 s de parole. Sur la carte graphique (`vc_device: "cuda"`, environ 1,5 Go de VRAM) : environ
0,05 s pour 5 s de parole, avec un chargement un peu plus long.

## Le synthé et le séquenceur

- **Pistes** : jusqu'à 12, synthé ou batterie, avec coupure (M) et écoute seule (S).
- **Saisie** : rouleau de piano sur 2 octaves (clic pour poser une note, glisser pour l'allonger, clic droit pour
  l'effacer) ; batterie pas à pas (grosse caisse, caisse claire, charleston fermé et ouvert, clap, tom).
- **Réglages du morceau** : 16 ou 32 pas, tempo, swing.
- **Synthé** :
  - 2 oscillateurs (forme d'onde, mélange, écart en cents) ;
  - enveloppe ADSR ;
  - filtre (passe-bas, passe-haut ou passe-bande) avec résonance et enveloppe ;
  - 7 préréglages.
- **Effets** : écho et salle en envois par piste, panoramique, limiteur général.
- **Jouer en direct** : clavier à l'écran ou clavier de l'ordinateur (rangée A S D F…, positions physiques) ;
  Espace lance ou arrête la lecture.
- **Fichiers** :
  - export WAV de 4 boucles rendu hors temps réel (OfflineAudioContext) ;
  - morceau enregistré automatiquement dans le navigateur ;
  - morceau exportable et importable en `.aether-audio.json`.

## API (compatible OpenAI)

Base : `http://127.0.0.1:5750/v1`. Le module est lancé à la demande au premier appel.

| Route | Entrée | Sortie |
|---|---|---|
| `POST /v1/audio/speech` | JSON `{input, voice?, speed?, effects?}` ; `voice` = profil d'AetherTwin (inconnu, ex. « alloy » → profil par défaut) | `audio/wav` (en-têtes `X-Voice-Profile`, `X-Voice-Engine`, `X-Voice-Fallback`) |
| `POST /v1/audio/transcriptions` | multipart (`file`, `language`, `response_format`) comme OpenAI, ou audio brut (`?language=fr`) ; WAV, WebM, OGG, MP3, M4A, FLAC ; 5 Mo au plus | `{"text", "language", "duration"}` (ou texte brut) |
| `GET/POST /voice/settings` | `{default?, mic?, speak_replies?}` | profils et réglages (sans lancer le module) |
| `POST /voice/profiles`, `DELETE /voice/profiles/{id}` | profil | profil validé |

Exemple :

```powershell
curl.exe -X POST http://127.0.0.1:5750/v1/audio/speech -H "Content-Type: application/json" -d '{\"input\":\"Bonjour\",\"voice\":\"narrateur\"}' -o bonjour.wav
```

## Commandes du module

`status`, `voices`, `profiles`, `profile_save`, `profile_delete`, `settings`, `speak`, `silence`, `transcribe`,
`effects`, `install`, `vbcable`, `hermes`, `hermes_register`, `tools`, `tool`, et pour la conversion `vc_status`,
`vc_install`, `vc_create`, `vc_prompt`, `vc_voice`, `vc_take`, `vc_take_delete`, `vc_delete`, `vc_convert`,
`vc_unload`. Le détail est dans `module.py`.
« stop » est réservé par le Hub à l'arrêt du module : la voix se coupe avec `silence`.

## Configuration (facultative)

Section `voice` de `config/local.yaml` :

```yaml
voice:
  data_dir: "data/voice"
  whisper_model: "small"      # tiny, base, small, medium, large-v3, large-v3-turbo
  whisper_device: "cpu"       # "cuda" prend de la VRAM aux modèles de langue
  vc_device: "cpu"            # conversion de voix ; "cuda" bien plus rapide (≈ 1,5 Go de VRAM)
```

## Limites connues

- La synthèse et l'écoute passent par le même processus du module, l'une après l'autre.
- Le décalage de hauteur en direct (lignes à retard) ajoute un léger grain sur les sons très purs ; il est discret
  sur la voix.
- La conversion n'est pas en direct. Elle s'applique à une phrase entière (2 minutes au plus) ; le modulateur en
  direct garde ses effets.
- Avec peu de lecture (moins d'une minute), quelques mots sont moins nets ; la voix s'améliore avec les prises.
- La conversion ne change pas la langue ni l'accent : elle remplace le timbre et garde la diction de la source.
