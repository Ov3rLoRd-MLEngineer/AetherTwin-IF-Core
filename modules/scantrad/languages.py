"""Langues sources prises en charge (vers le français) : japonais, chinois, coréen, anglais.

Chaque langue fixe :
- l'écriture attendue dans une lecture (une réponse sans aucun de ces caractères est un faux positif) ;
- si le texte peut être vertical (japonais, chinois) : on mesure alors le sens et on lit colonne par colonne ;
- le sens de lecture des bulles : de droite à gauche pour le manga japonais ; de gauche à droite pour les
  manhwa coréens, les manhua chinois modernes et les comics ;
- le nom de l'œuvre dans les consignes (manga, manhua, manhwa, comic).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    code: str
    name: str          # « japonais » : dans les consignes, « le texte japonais »
    script: re.Pattern[str]
    vertical: bool     # le texte peut être écrit en colonnes
    right_to_left: bool  # ordre de lecture des bulles
    work: str          # manga, manhua, manhwa, comic
    note: str = ""     # précision de lecture propre à la langue


LANGUAGES = {
    "ja": Language("ja", "japonais", re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]"), True, True, "manga",
                   "Ignore les furigana (petits caractères de lecture placés à côté des kanji)."),
    "zh": Language("zh", "chinois", re.compile(r"[㐀-鿿]"), True, False, "manhua"),
    "ko": Language("ko", "coréen", re.compile(r"[가-힯ᄀ-ᇿ㄰-㆏]"), False, False, "manhwa"),
    "en": Language("en", "anglais", re.compile(r"[A-Za-z]{2}"), False, False, "comic",
                   "Le lettrage est souvent en capitales : transcris-le tel quel."),
}
DEFAULT = "ja"


def language(code: str | None) -> Language:
    """Langue demandée ; le japonais par défaut. Refuse un code inconnu (au lieu de deviner)."""
    code = (code or DEFAULT).strip().lower()
    if code not in LANGUAGES:
        raise ValueError(f"langue inconnue : {code!r} (attendu : {', '.join(LANGUAGES)})")
    return LANGUAGES[code]


def ocr_prompt(lang: Language, mode: str = "auto") -> str:
    """Consigne d'OCR.

    - `auto` : la zone vient de la détection, elle peut ne contenir que du dessin → réponse « AUCUN » permise ;
    - `manual` : zone posée à la main, sens inconnu ;
    - `vertical` / `horizontal` : sens mesuré sur l'encre ;
    - `column` : une seule colonne, découpée par le code.
    """
    head = f"Transcris exactement le texte {lang.name} écrit dans cette image extraite d'un {lang.work}."
    tail = "Réponds uniquement par le texte transcrit, sur une ligne, sans traduction ni commentaire."
    note = f" {lang.note}" if lang.note else ""
    if mode == "column":
        return (f"Transcris exactement le texte {lang.name} de cette image : une seule colonne verticale, à lire "
                f"de haut en bas. {tail}")
    if mode == "vertical":
        return (f"{head} Le texte est VERTICAL, en plusieurs colonnes : lis chaque colonne de haut en bas, en "
                f"commençant par la colonne la plus à DROITE, puis celle à sa gauche, et ainsi de suite.{note} {tail}")
    if mode == "horizontal":
        return f"{head} Le texte est HORIZONTAL : lis les lignes de gauche à droite, de haut en bas.{note} {tail}"
    sense = (" Le texte peut être vertical : lis les colonnes de haut en bas, de la droite vers la gauche."
             if lang.vertical else "")
    if mode == "manual":
        return f"{head}{sense}{note} {tail}"
    return (f"{head}{sense}{note} {tail} S'il n'y a pas de texte {lang.name} lisible (dessin, décor), réponds "
            "exactement : AUCUN")
