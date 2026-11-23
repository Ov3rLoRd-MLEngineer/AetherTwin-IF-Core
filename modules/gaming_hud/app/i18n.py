"""
Langue de l'interface (français par défaut, anglais en option : Paramètres généraux > Langue).

L'appli est écrite en français ; la traduction se fait à l'affichage (ui.text / fit / wrap passent par `tr`) :
- texte exact trouvé dans le catalogue `i18n_en.json` (relevé par scripts/extract_ui_strings.py) ;
- sinon modèle de f-string (« {0} objets » → « {0} items »), les valeurs étant traduites à leur tour ;
- sinon morceaux connus (phrases du catalogue) remplacés dans un texte assemblé ;
- sinon le texte reste tel quel (données du jeu, noms propres...).

Les réponses des IA suivent la langue : `answer_note()` est ajouté aux questions envoyées.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LANGUAGES = {"fr": "Français", "en": "English"}
_CACHE_MAX = 6000

_lang = "fr"
_exact, _patterns, _fragments = {}, [], []
_cache = {}


def _compile(template):
    parts = re.split(r"(\{\d+\})", template)
    regex, order = "", []
    for p in parts:
        m = re.fullmatch(r"\{(\d+)\}", p)
        if m:
            regex += "(.+?)"
            order.append(int(m.group(1)))
        else:
            regex += re.escape(p.replace("{{", "{").replace("}}", "}"))
    literal = max((p for p in parts if not re.fullmatch(r"\{\d+\}", p)), key=len, default="")
    return re.compile("^" + regex + "$", re.S), order, literal.replace("{{", "{").replace("}}", "}")


def load(lang="fr", path=None):
    """Choisit la langue ; charge le catalogue anglais au besoin."""
    global _lang
    _lang = lang if lang in LANGUAGES else "fr"
    _cache.clear()
    _exact.clear()
    _patterns.clear()
    _fragments.clear()
    if _lang == "fr":
        return
    try:
        with open(path or os.path.join(HERE, f"i18n_{_lang}.json"), encoding="utf-8") as f:
            catalog = json.load(f)
    except (OSError, ValueError):
        catalog = {}
    for fr, en in catalog.items():
        if not isinstance(en, str) or not en or en == fr:
            continue
        if re.search(r"(?<!\{)\{\d+\}(?!\})", fr):
            regex, order, literal = _compile(fr)
            _patterns.append((regex, order, literal, en))
        else:
            _exact[fr] = en
            if " " in fr and len(fr) >= 10:
                _fragments.append((fr, en))
    _patterns.sort(key=lambda p: -len(p[2]))           # le modèle le plus précis d'abord
    _fragments.sort(key=lambda f: -len(f[0]))


def language():
    return _lang


def tr(text):
    """Texte traduit dans la langue choisie (tel quel en français ou si inconnu)."""
    if _lang == "fr" or not isinstance(text, str) or not text.strip():
        return text
    hit = _cache.get(text)
    if hit is not None:
        return hit
    out = _translate(text, 0)
    if len(_cache) > _CACHE_MAX:
        _cache.clear()
    _cache[text] = out
    return out


def _translate(text, depth):
    if text in _exact:
        return _exact[text]
    stripped = text.strip()
    if stripped != text and stripped in _exact:
        return text.replace(stripped, _exact[stripped])
    if depth < 2:
        for regex, order, literal, en in _patterns:
            if literal and literal not in text:
                continue
            m = regex.match(text)
            if m:
                values = {i: _translate(v, depth + 1) for i, v in zip(order, m.groups(), strict=False)}
                try:
                    return en.format(*[values.get(i, "") for i in range(max(order) + 1)])
                except (IndexError, KeyError, ValueError):
                    break
    out = text
    for fr, en in _fragments:
        if fr in out:
            out = out.replace(fr, en)
    return out


def answer_note():
    """Phrase ajoutée aux questions envoyées aux IA pour qu'elles répondent dans la langue de l'interface."""
    return "\n\n(Answer in English.)" if _lang == "en" else ""
