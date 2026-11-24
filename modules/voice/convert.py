"""Conversion de voix (kNN-VC, MIT) : donne à une voix le timbre d'une voix enregistrée avec consentement.

Principe (Baas, van Niekerk, Kamper, 2023) : WavLM-Large découpe la parole en vecteurs (couche 6, 50 par seconde) ;
chaque vecteur de la voix à convertir est remplacé par la moyenne de ses 4 plus proches voisins pris dans les
enregistrements de la voix cible ; un vocodeur HiFi-GAN refait le son. Rien à entraîner : plus la voix cible a
d'enregistrements (1 à 5 minutes), plus le résultat est fidèle.

Consentement, vérifié à chaque étape :
    - une voix de la banque appartient à quelqu'un qui l'a enregistrée lui-même dans le studio ;
    - sa première prise est une phrase de consentement dite à voix haute, avec son nom, que Whisper doit retrouver ;
    - les prises suivantes sont des textes affichés à lire : un fichier de quelqu'un d'autre (vidéo, message) ne
      passe pas, puisqu'il faudrait qu'il contienne exactement ces phrases ;
    - aucune importation de fichier ; la banque reste sur ce PC (`data/voice/bank/`, hors Git).

Poids (téléchargés à la demande depuis les publications de kNN-VC, taille et SHA-256 vérifiés, chargés avec
`weights_only=True`) : WavLM-Large (1,26 Go) et le vocodeur « prematched » (66 Mo).
"""
from __future__ import annotations

import difflib
import hashlib
import io
import json
import re
import shutil
import threading
import time
import unicodedata
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from modules.voice import effects

RATE = 16_000
LAYER = 6           # couche de WavLM qui porte le timbre (article kNN-VC)
TOPK = 4
RELEASE = "https://github.com/bshall/knn-vc/releases/download/v0.1/"
WEIGHTS = {  # nom → (taille en octets, SHA-256)
    "WavLM-Large.pt": (1_261_965_425, "6fb4b3c3e6aa567f0a997b30855859cb81528ee8078802af439f7b2da0bf100f"),
    "prematch_g_02500000.pt": (66_214_643, "f924c7632c6eaf99004386d62293e124419e33582573552a6ae976eb88ed2dd5"),
}
VOICE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
MAX_VOICES = 16
MAX_TAKES = 100    # consentement + 99 lectures (≈ 5 à 8 min)
TAKE_SECONDS = (2.0, 60.0)
MATCH_MIN = 0.6     # ressemblance minimale entre le texte affiché et ce que Whisper a entendu

CONSENT_TEXT = ("Je m'appelle {name}, c'est ma propre voix, et j'accepte qu'AetherTwin l'apprenne sur cet ordinateur.")
PROMPTS = [
    "Le petit chat gris saute sur la table et regarde la pluie tomber derrière la fenêtre.",
    "Ce matin, j'ai pris un café bien chaud avant de partir travailler à vélo.",
    "Les montagnes enneigées brillent sous le soleil d'hiver, et le vent souffle fort.",
    "Pourriez-vous m'indiquer le chemin le plus court pour rejoindre la gare centrale ?",
    "Nous avons marché longtemps au bord de la plage en ramassant des coquillages.",
    "Il faut parfois s'arrêter, respirer profondément, puis reprendre la route avec le sourire.",
    "Le vaisseau quitta l'orbite lunaire et fila vers les étoiles lointaines de la galaxie.",
    "Mon grand-père racontait des histoires de pirates, de trésors et d'îles mystérieuses.",
    "Attention : le niveau d'eau monte vite, fermez les vannes et prévenez l'équipe !",
    "Une douce mélodie s'échappait du piano, emplissant la pièce d'une chaleur inattendue.",
    "Les oiseaux migrateurs traversent chaque année des milliers de kilomètres sans se perdre.",
    "Bonjour à tous, bienvenue dans cette nouvelle aventure, installez-vous confortablement.",
    "Le boulanger sort du four une fournée de croissants dorés qui sentent bon le beurre.",
    "Sous la lune, le loup gris traverse la forêt sans faire le moindre bruit.",
    "Je voudrais réserver une table pour deux personnes ce soir, près de la fenêtre si possible.",
    "La rivière serpente entre les collines vertes avant de rejoindre la mer agitée.",
    "Quelle surprise de te voir ici ! Tu aurais dû me prévenir, j'aurais préparé un gâteau.",
    "Le chevalier rangea son épée, salua la reine puis disparut dans la brume du matin.",
    "Chaque soir, elle notait dans un carnet les petites joies et les grandes idées de la journée.",
    "Un éclair zébra le ciel, suivi d'un grondement sourd qui fit trembler les vitres.",
    # phrases courtes et variées : questions, exclamations, sons du français (on, an, in, u, ou, ch, j, gn, ill)
    "Tu viens avec nous au marché demain matin ?",
    "Oh non, j'ai encore oublié mes clés dans la voiture !",
    "Il fait beau aujourd'hui, allons pique-niquer dans le parc.",
    "Peux-tu baisser un peu la musique, s'il te plaît ?",
    "Le train part dans cinq minutes, dépêche-toi !",
    "J'aime beaucoup l'odeur de la terre mouillée après l'orage.",
    "La bibliothèque ferme tôt le dimanche, pense à rendre tes livres.",
    "Une araignée tisse patiemment sa toile entre deux branches de vigne.",
    "Je ne comprends pas pourquoi l'imprimante refuse encore de fonctionner.",
    "Les enfants chantaient une chanson douce en rentrant de l'école.",
    "As-tu déjà vu une aurore boréale danser au-dessus de la neige ?",
    "Mon voisin jardine tous les samedis, même quand il pleut.",
    "C'est incroyable, nous avons enfin gagné la partie !",
    "Le chat ronronne sur le canapé, roulé en boule près du radiateur.",
    "Pense à arroser les plantes pendant que je suis en vacances.",
    "La soupe à l'oignon de ma grand-mère était la meilleure du village.",
    "Un brouillard épais couvrait la vallée jusqu'à midi.",
    "Est-ce que quelqu'un a vu mon écharpe bleue ?",
    "Le magicien sortit un lapin blanc de son chapeau noir.",
    "Nous partirons à l'aube pour éviter la chaleur de l'après-midi.",
    "Ferme la porte doucement, le bébé vient de s'endormir.",
    "Les vagues se brisent sur les rochers dans un fracas d'écume.",
    "Je préfère le thé au café, surtout avec un nuage de lait.",
    "Le musée présente une exposition sur les volcans et les tremblements de terre.",
    "Quelle drôle d'idée de repeindre la cuisine en jaune citron !",
    "Il a couru sous la pluie pour attraper le dernier bus.",
    "Les feuilles d'automne craquent sous nos pas dans l'allée du jardin.",
    "Voulez-vous du sucre ou du miel dans votre tisane ?",
    "La fusée décolle dans un nuage de fumée et de flammes orange.",
    "Prends ton temps, nous ne sommes pas pressés.",
    "Le hibou hulule doucement dans le grand chêne au fond du pré.",
    "On entend au loin les cloches de l'église sonner midi.",
    "Ce livre raconte l'histoire d'un enfant qui parlait aux arbres.",
    "Il faudra réparer la gouttière avant les grandes pluies.",
    "Bravo, ton dessin est magnifique, tu devrais l'accrocher au mur.",
    "Le pêcheur attend sur la jetée, immobile, que le poisson morde.",
    "Je me souviens très bien du jour où nous avons déménagé.",
    "Les abeilles butinent les fleurs de lavande tout l'été.",
    "Tu as raison, mieux vaut prévenir que guérir.",
    "La nuit tombe, et les lampadaires s'allument un à un dans la rue.",
    # textes longs, lus en plusieurs parties (une prise par partie) : voir LONG_TEXTS
    "Au bout de la presqu'île se dresse un vieux phare blanc et rouge. Depuis plus d'un siècle, il guide les "
    "bateaux qui rentrent au port par les nuits de tempête.",
    "Le gardien vivait seul là-haut avec son chien. Chaque soir, il montait les marches de l'escalier en "
    "colimaçon pour allumer la grande lampe.",
    "Un hiver, la tempête dura trois jours entiers. Les vagues frappaient la tour si fort que les vitres "
    "tremblaient, mais la lumière ne s'éteignit jamais.",
    "Aujourd'hui, le phare fonctionne tout seul. Pourtant, les marins du village continuent de saluer la petite "
    "fenêtre où brillait autrefois la lampe du gardien.",
    "Pour faire une bonne pâte à crêpes, il faut de la farine, des œufs, du lait et une pincée de sel. On mélange "
    "d'abord la farine et les œufs, puis on ajoute le lait petit à petit.",
    "Il faut fouetter doucement pour éviter les grumeaux. Ensuite, on laisse reposer la pâte au frais pendant une "
    "heure, le temps qu'elle devienne bien lisse.",
    "Dans une poêle chaude et légèrement beurrée, on verse une petite louche de pâte. On incline la poêle pour "
    "l'étaler, puis on retourne la crêpe quand le bord devient doré.",
    "On peut la garnir de sucre, de confiture ou de chocolat fondu. Et si l'on est très adroit, on peut même la "
    "faire sauter en l'air pour la retourner.",
    "La Terre tourne autour du Soleil en un peu plus d'une année. En même temps, elle tourne sur elle-même, ce "
    "qui donne le jour et la nuit.",
    "Son axe est penché par rapport à son orbite. C'est pour cette raison que nous avons des saisons : l'été, "
    "notre hémisphère reçoit les rayons du Soleil plus directement.",
    "La Lune, elle, tourne autour de la Terre en un mois environ. Elle ne brille pas par elle-même : elle renvoie "
    "simplement la lumière du Soleil, d'où ses phases.",
    "Bonjour, et merci de m'écouter. Aujourd'hui, je voudrais vous présenter un projet qui me tient à cœur depuis "
    "longtemps.",
    "L'idée est simple : réunir sur un seul ordinateur des outils pour apprendre, créer et jouer, sans dépendre "
    "d'internet ni d'un abonnement.",
    "Tout fonctionne en local, sur la machine. Les modèles d'intelligence artificielle tournent sur les cartes "
    "graphiques, et vos données restent chez vous.",
    "Je vais maintenant vous montrer quelques exemples. N'hésitez pas à poser des questions à la fin, je serai "
    "ravi d'y répondre.",
]
LONG_TEXTS = [("Le vieux phare", 4), ("La pâte à crêpes", 4), ("La Terre et la Lune", 3), ("La présentation", 4)]


def prompt_label(index: int) -> str:
    """« Texte long « … », partie 2 sur 4 » pour les morceaux des textes longs, sinon vide."""
    start = len(PROMPTS) - sum(n for _title, n in LONG_TEXTS)
    if index < start:
        return ""
    for title, n in LONG_TEXTS:
        if index < start + n:
            return f"Texte long « {title} », partie {index - start + 1} sur {n}"
        start += n
    return ""


READY_SECONDS = 30.0  # lecture minimale (hors consentement) pour un timbre reconnaissable ; 3 à 5 min conseillées


def words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFD", text.lower())
    plain = "".join(c for c in plain if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", plain)


def similarity(expected: str, heard: str) -> float:
    return difflib.SequenceMatcher(None, words(expected), words(heard)).ratio()


def trim_silence(x: np.ndarray, rate: int = RATE, floor_db: float = -45.0) -> np.ndarray:
    """Retire le silence du début et de la fin (trames de 20 ms sous `floor_db` par rapport à la crête)."""
    if x.size == 0:
        return x
    hop = rate // 50
    frames = x[: x.size // hop * hop].reshape(-1, hop) if x.size >= hop else x.reshape(1, -1)
    level = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    loud = np.flatnonzero(level > max(level.max() + floor_db, -70.0))  # -70 dB : silence numérique
    if loud.size == 0:
        return x[:0]
    start, end = max(0, loud[0] - 2) * hop, min(frames.shape[0], loud[-1] + 3) * hop
    return x[start:end]


def decode(audio: bytes) -> np.ndarray:
    """Tout format (WAV, WebM/Opus du navigateur…) → float32 mono à 16 kHz."""
    if audio[:4] == b"RIFF":
        try:
            x, rate = effects.read_wav(audio)
            return effects.resample(x, rate / RATE).astype(np.float32) if rate != RATE else x  # facteur = vitesse
        except (ValueError, EOFError):
            pass
    try:
        from faster_whisper import decode_audio
    except ImportError:
        raise RuntimeError("WAV 16 bits attendu (faster-whisper absent pour lire les autres formats)") from None
    return np.asarray(decode_audio(io.BytesIO(audio), sampling_rate=RATE), dtype=np.float32)


# ---------------------------------------------------------------------------- poids
def fetch_to(url: str, target: Path, size: int, sha256: str, timeout: float = 120) -> None:
    """Télécharge `url` (publications de kNN-VC seulement) vers `target`, taille et empreinte vérifiées."""
    if not url.startswith(RELEASE):
        raise ValueError("source refusée")
    part = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    got = 0
    with urllib.request.urlopen(url, timeout=timeout) as response, part.open("wb") as out:  # noqa: S310
        while chunk := response.read(1 << 20):
            got += len(chunk)
            if got > size:
                raise ValueError(f"{target.name} : plus gros que prévu")
            digest.update(chunk)
            out.write(chunk)
    if got != size or (sha256 and digest.hexdigest() != sha256):
        part.unlink(missing_ok=True)
        raise ValueError(f"{target.name} : fichier différent de celui publié (taille ou empreinte)")
    part.replace(target)


def weights_status(folder: Path) -> dict[str, bool]:
    return {name: (folder / name).is_file() and (folder / name).stat().st_size == size
            for name, (size, _sha) in WEIGHTS.items()}


def install(folder: Path, fetcher: Callable[[str, Path, int, str], None] = fetch_to) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    fetched = []
    for name, (size, sha) in WEIGHTS.items():
        if not weights_status(folder)[name]:
            fetcher(RELEASE + name, folder / name, size, sha)
            fetched.append(name)
    return {"fetched": fetched, "weights": weights_status(folder)}


# ---------------------------------------------------------------------------- banque de voix
def reading_seconds(voice: dict[str, Any]) -> float:
    """Durée des textes lus, sans la phrase de consentement."""
    return float(sum(t["seconds"] for t in voice.get("takes", []) if t.get("prompt", -1) >= 0))


class VoiceBank:
    """Voix enregistrées avec consentement : `bank/<id>/voice.json`, `takes/*.wav` (16 kHz), `features.pt`."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self._lock = threading.Lock()

    def _dir(self, vid: str) -> Path:
        if not VOICE_ID.fullmatch(str(vid)):
            raise ValueError("identifiant de voix invalide")
        return self.folder / vid

    def _read(self, vid: str) -> dict[str, Any]:
        path = self._dir(vid) / "voice.json"
        if not path.is_file():
            raise ValueError(f"voix inconnue : {vid}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, voice: dict[str, Any]) -> None:
        path = self._dir(voice["id"]) / "voice.json"
        path.write_text(json.dumps(voice, ensure_ascii=False, indent=1), encoding="utf-8")

    def get(self, vid: str) -> dict[str, Any]:
        return self._read(vid)

    def all(self) -> list[dict[str, Any]]:
        if not self.folder.is_dir():
            return []
        out = []
        for path in sorted(self.folder.glob("*/voice.json")):
            try:
                v = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            reading = reading_seconds(v)
            out.append({k: v.get(k) for k in ("id", "label", "consented", "created")}
                       | {"takes": len(v.get("takes", [])), "seconds": round(reading, 1),
                          "ready": bool(v.get("consented")) and reading >= READY_SECONDS})
        return out

    def create(self, vid: str, label: str, name: str, attest: bool) -> dict[str, Any]:
        """Nouvelle voix, encore inutilisable : la phrase de consentement doit d'abord être dite (`add_take`)."""
        if attest is not True:
            raise ValueError("coche l'attestation : seule ta voix (ou celle d'une personne présente qui lit "
                             "elle-même la phrase de consentement) peut entrer dans la banque")
        name = " ".join(str(name or "").split())[:40]
        if len(words(name)) < 1:
            raise ValueError("indique le prénom de la personne dont c'est la voix")
        with self._lock:
            if len(self.all()) >= MAX_VOICES:
                raise ValueError(f"{MAX_VOICES} voix au plus")
            folder = self._dir(vid)
            if folder.exists():
                raise ValueError(f"la voix « {vid} » existe déjà")
            (folder / "takes").mkdir(parents=True)
            voice = {"id": vid, "label": str(label or vid)[:60], "name": name,
                     "created": time.strftime("%Y-%m-%d %H:%M"),
                     "consent_text": CONSENT_TEXT.format(name=name), "consented": False, "takes": []}
            self._write(voice)
        return voice

    def next_prompt(self, vid: str, after: int | None = None) -> dict[str, Any]:
        """Prochain texte pas encore lu ; `after` (« Autre texte ») cherche à partir du texte suivant celui-là."""
        voice = self._read(vid)
        if not voice["consented"]:
            return {"index": -1, "text": voice["consent_text"], "consent": True, "label": ""}
        done = {t["prompt"] for t in voice["takes"]}
        first = 0 if after is None else (int(after) + 1) % len(PROMPTS)
        order = [(first + i) % len(PROMPTS) for i in range(len(PROMPTS))]
        fallback = first if after is not None else len(voice["takes"]) % len(PROMPTS)
        index = next((i for i in order if i not in done), fallback)
        return {"index": index, "text": PROMPTS[index], "consent": False, "label": prompt_label(index),
                "left": sum(1 for i in range(len(PROMPTS)) if i not in done), "total": len(PROMPTS)}

    def add_take(self, vid: str, audio: bytes, prompt: int, transcribe: Callable[[bytes], str]) -> dict[str, Any]:
        """Ajoute une prise lue en direct ; refusée si Whisper n'entend pas le texte affiché."""
        voice = self._read(vid)
        if len(voice["takes"]) >= MAX_TAKES:
            raise ValueError(f"{MAX_TAKES} prises au plus par voix")
        expected = voice["consent_text"] if not voice["consented"] else PROMPTS[int(prompt) % len(PROMPTS)]
        if voice["consented"] and not 0 <= int(prompt) < len(PROMPTS):
            raise ValueError("texte à lire inconnu")
        x = trim_silence(decode(audio))
        seconds = x.size / RATE
        if not TAKE_SECONDS[0] <= seconds <= TAKE_SECONDS[1]:
            raise ValueError(f"prise de {seconds:.1f} s : entre {TAKE_SECONDS[0]:.0f} et {TAKE_SECONDS[1]:.0f} s")
        wav = effects.write_wav(effects.normalize(x), RATE)
        heard = transcribe(wav)
        score = similarity(expected, heard)
        if score < MATCH_MIN:
            raise ValueError(f"le texte lu ne correspond pas ({score:.0%}) ; entendu : « {heard[:160]} »")
        with self._lock:
            voice = self._read(vid)
            n = max([int(t["file"][:3]) for t in voice["takes"]] or [-1]) + 1
            (self._dir(vid) / "takes" / f"{n:03d}.wav").write_bytes(wav)
            voice["takes"].append({"file": f"{n:03d}.wav", "prompt": -1 if not voice["consented"] else int(prompt),
                                   "seconds": round(seconds, 2), "match": round(score, 2)})
            voice["consented"] = True
            self._write(voice)
            (self._dir(vid) / "features.pt").unlink(missing_ok=True)
        return {"take": n, "seconds": round(seconds, 2), "match": round(score, 2), "heard": heard,
                "next": self.next_prompt(vid)}

    def delete_take(self, vid: str, take: int) -> bool:
        with self._lock:
            voice = self._read(vid)
            name = f"{int(take):03d}.wav"
            kept = [t for t in voice["takes"] if t["file"] != name]
            if len(kept) == len(voice["takes"]):
                return False
            if voice["takes"] and voice["takes"][0]["file"] == name:
                raise ValueError("la phrase de consentement reste : supprime la voix entière à la place")
            voice["takes"] = kept
            (self._dir(vid) / "takes" / name).unlink(missing_ok=True)
            (self._dir(vid) / "features.pt").unlink(missing_ok=True)
            self._write(voice)
        return True

    def delete(self, vid: str) -> bool:
        folder = self._dir(vid)
        if not folder.is_dir():
            return False
        with self._lock:
            shutil.rmtree(folder)
        return True

    def takes(self, vid: str) -> list[np.ndarray]:
        voice = self._read(vid)
        if not voice["consented"] or reading_seconds(voice) < READY_SECONDS:
            raise ValueError(f"la voix « {vid} » n'est pas prête : phrase de consentement puis "
                             f"{READY_SECONDS:.0f} s de lecture au moins ({reading_seconds(voice):.0f} s)")
        return [effects.read_wav((self._dir(vid) / "takes" / t["file"]).read_bytes())[0] for t in voice["takes"]]


# ---------------------------------------------------------------------------- conversion
class Converter:
    """WavLM + HiFi-GAN chargés à la première conversion (≈ 1,4 Go de mémoire ; processeur par défaut)."""

    def __init__(self, weights: Path, bank: VoiceBank, device: str = "cpu") -> None:
        self.weights, self.bank, self.device = Path(weights), bank, device
        self._models: tuple[Any, Any] | None = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        try:
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def status(self) -> dict[str, Any]:
        weights = weights_status(self.weights)
        return {"torch": self.available(), "weights": weights, "installed": all(weights.values()),
                "loaded": self._models is not None, "device": self.device}

    def unload(self) -> bool:
        with self._lock:
            was = self._models is not None
            self._models = None
        return was

    def _load(self) -> tuple[Any, Any]:
        if self._models is not None:
            return self._models
        if not self.available():
            raise RuntimeError("PyTorch absent : la conversion de voix en a besoin")
        if not all(weights_status(self.weights).values()):
            raise RuntimeError("poids de conversion absents : Studio audio → Ma voix → Installer")
        import torch

        from modules.voice.vc.hifigan import AttrDict, Generator
        from modules.voice.vc.wavlm import WavLM, WavLMConfig

        device = torch.device(self.device if self.device == "cpu" or torch.cuda.is_available() else "cpu")
        checkpoint = torch.load(self.weights / "WavLM-Large.pt", map_location="cpu", weights_only=True)
        wavlm = WavLM(WavLMConfig(checkpoint["cfg"]))
        wavlm.load_state_dict(checkpoint["model"])
        wavlm = wavlm.to(device).eval()
        config = json.loads((Path(__file__).parent / "vc" / "hifigan_config.json").read_text(encoding="utf-8"))
        vocoder = Generator(AttrDict(config))
        state = torch.load(self.weights / "prematch_g_02500000.pt", map_location="cpu", weights_only=True)
        vocoder.load_state_dict(state["generator"])
        vocoder.remove_weight_norm()
        vocoder = vocoder.to(device).eval()
        self._models = (wavlm, vocoder)
        return self._models

    def _features(self, wavlm: Any, x: np.ndarray) -> Any:
        import torch

        device = next(wavlm.parameters()).device
        source = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))[None].to(device)
        return wavlm.extract_features(source, output_layer=LAYER, ret_layer_results=False)[0].squeeze(0)

    def _matching_set(self, wavlm: Any, vid: str) -> Any:
        import torch

        cache = self.bank._dir(vid) / "features.pt"
        if cache.is_file():
            return torch.load(cache, map_location="cpu", weights_only=True)
        feats = torch.cat([self._features(wavlm, trim_silence(x)).cpu() for x in self.bank.takes(vid)], dim=0)
        torch.save(feats, cache)
        return feats

    def convert(self, x: np.ndarray, vid: str) -> np.ndarray:
        """Échantillons à 16 kHz → mêmes paroles avec le timbre de la voix `vid` (16 kHz)."""
        import torch

        if x.size < RATE // 10:
            raise ValueError("enregistrement trop court")
        if x.size > RATE * 120:
            raise ValueError("2 minutes au plus par conversion")
        with self._lock, torch.inference_mode():
            wavlm, vocoder = self._load()
            device = next(wavlm.parameters()).device
            pool = self._matching_set(wavlm, vid).to(device)
            query = self._features(wavlm, x)
            # distance cosinus, puis moyenne des k plus proches voisins (kNN-VC)
            q = torch.nn.functional.normalize(query, dim=-1)
            p = torch.nn.functional.normalize(pool, dim=-1)
            best = (q @ p.T).topk(k=min(TOPK, pool.shape[0]), dim=-1).indices
            out = vocoder(pool[best].mean(dim=1)[None]).squeeze().float().cpu().numpy()
        return effects.normalize(out.astype(np.float32))

    def convert_wav(self, wav: bytes, vid: str) -> bytes:
        return effects.write_wav(self.convert(decode(wav), vid), RATE)
