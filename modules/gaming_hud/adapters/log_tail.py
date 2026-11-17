"""Adaptateur générique : suit un fichier journal texte et en tire un état, avec des règles regex en YAML.

Convient à tout jeu (ou outil) qui écrit un journal lisible : il suffit d'un fichier de règles, sans
écrire de code. Exemple : `modules/gaming_hud/rules/log_tail.example.yaml`.

Format des règles :

    id: mon_jeu                    # identifiant de l'adaptateur
    game: "Mon jeu"
    path: "chemin/vers/le/journal.log"
    encoding: utf-8                # facultatif
    rules:
      - field: zone                # nom du champ dans l'état
        pattern: 'Entering zone: (?P<value>.+)'
        description: "Zone actuelle"
      - field: level
        pattern: 'Level up! Now level (?P<value>\\d+)'
        type: int                  # str (défaut) | int | float
      - field: deaths
        pattern: 'You died'
        mode: count                # set (défaut) | count | append
      - field: whispers
        pattern: 'Whisper from (?P<value>.+)'
        mode: append
        max: 20
        private: true              # masqué en mode Showcase

Le fichier n'est jamais modifié. Seules les lignes ajoutées depuis la dernière lecture sont analysées ;
une troncature ou une rotation du journal est détectée et la lecture reprend au début.
"""
from __future__ import annotations

import copy
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modules.gaming_hud.adapters.base import META_KEY, PRIVACY_OFF, check_mode
from modules.gaming_hud.adapters.privacy import MASK, PrivacyOptions, filter_state

_CASTS = {"str": str, "int": lambda v: int(float(v)), "float": float}
_MODES = ("set", "count", "append")
MAX_READ_BYTES = 4 * 1024 * 1024  # par lecture : un journal énorme est rattrapé en plusieurs fois


class RulesError(ValueError):
    """Fichier de règles invalide."""


@dataclass(frozen=True)
class Rule:
    field: str
    pattern: re.Pattern[str]
    type: str = "str"
    mode: str = "set"
    max: int = 50
    private: bool = False
    description: str = ""


def parse_rules(raw: Any) -> tuple[dict[str, Any], list[Rule]]:
    """Valide le contenu d'un fichier de règles. Retourne (en-tête, règles)."""
    if not isinstance(raw, dict):
        raise RulesError("le fichier de règles doit être un dictionnaire YAML")
    if not isinstance(raw.get("path"), str) or not raw["path"].strip():
        raise RulesError("`path` (chemin du journal) est obligatoire")
    items = raw.get("rules")
    if not isinstance(items, list) or not items:
        raise RulesError("`rules` doit être une liste non vide")
    rules = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("field") or not item.get("pattern"):
            raise RulesError(f"règle n° {index + 1} : `field` et `pattern` sont obligatoires")
        kind, mode = str(item.get("type", "str")), str(item.get("mode", "set"))
        if kind not in _CASTS:
            raise RulesError(f"règle « {item['field']} » : type inconnu {kind!r} (str, int, float)")
        if mode not in _MODES:
            raise RulesError(f"règle « {item['field']} » : mode inconnu {mode!r} (set, count, append)")
        try:
            pattern = re.compile(str(item["pattern"]))
        except re.error as exc:
            raise RulesError(f"règle « {item['field']} » : expression régulière invalide ({exc})") from exc
        rules.append(Rule(str(item["field"]), pattern, kind, mode, int(item.get("max", 50)),
                          bool(item.get("private", False)), str(item.get("description", ""))))
    header = {"id": str(raw.get("id", "log_tail")), "game": str(raw.get("game", "Jeu (journal texte)")),
              "path": raw["path"], "encoding": str(raw.get("encoding", "utf-8"))}
    return header, rules


class LogTailAdapter:
    """Construit un état à partir des lignes d'un journal texte."""

    def __init__(self, config: dict[str, Any], options: PrivacyOptions | None = None,
                 base_dir: Path | None = None) -> None:
        header, self.rules = parse_rules(config)
        self.id = header["id"]
        self.game = header["game"]
        self.encoding = header["encoding"]
        path = Path(os.path.expandvars(os.path.expanduser(header["path"])))
        self.path = path if path.is_absolute() or base_dir is None else base_dir / path
        self.options = options or PrivacyOptions()
        self._offset = 0
        self._inode: tuple[int, int] | None = None
        self._partial = ""
        self._fields: dict[str, Any] = {}
        self._lines_seen = 0
        self._last_match = 0.0
        self._error = ""

    @classmethod
    def from_file(cls, rules_path: Path, options: PrivacyOptions | None = None) -> LogTailAdapter:
        import yaml

        try:
            raw = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise RulesError(f"fichier de règles illisible ({rules_path}) : {exc}") from exc
        return cls(raw, options, base_dir=rules_path.parent)

    # -- lecture
    def detect(self) -> bool:
        return self.path.is_file()

    def _read_new_text(self) -> str:
        stat = self.path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if self._inode != identity or stat.st_size < self._offset:  # rotation ou troncature : on repart du début
            self._offset, self._partial, self._inode = 0, "", identity
        if stat.st_size == self._offset:
            return ""
        with open(self.path, "rb") as handle:
            handle.seek(self._offset)
            data = handle.read(MAX_READ_BYTES)
        self._offset += len(data)
        return data.decode(self.encoding, errors="replace")

    def _apply(self, line: str) -> None:
        for rule in self.rules:
            match = rule.pattern.search(line)
            if not match:
                continue
            self._last_match = time.time()
            if rule.mode == "count":
                self._fields[rule.field] = int(self._fields.get(rule.field, 0)) + 1
                continue
            groups = match.groupdict()
            raw = groups["value"] if "value" in groups else (match.group(1) if match.groups() else match.group(0))
            try:
                value = _CASTS[rule.type](raw.strip() if isinstance(raw, str) else raw)
            except (TypeError, ValueError):
                continue  # la ligne correspond mais la valeur n'a pas le type attendu : ignorée
            if rule.mode == "append":
                items = self._fields.setdefault(rule.field, [])
                items.append(value)
                del items[:-max(1, rule.max)]
            else:
                self._fields[rule.field] = value

    def read_state(self) -> dict[str, Any]:
        self._error = ""
        try:
            text = self._partial + self._read_new_text()
            lines = text.split("\n")
            self._partial = lines.pop()  # dernière ligne peut-être incomplète : gardée pour la prochaine lecture
            for line in lines:
                self._lines_seen += 1
                self._apply(line.rstrip("\r"))
        except FileNotFoundError:
            self._error = "journal introuvable"
        except OSError as exc:
            self._error = f"lecture impossible : {exc}"
        state: dict[str, Any] = {"fields": copy.deepcopy(self._fields)}
        state[META_KEY] = {
            "adapter": self.id, "game": self.game, "read_only": True, "detected": self.detect(),
            "has_data": bool(self._fields), "source_file": str(self.path), "lines_seen": self._lines_seen,
            "last_match": self._last_match or None, "error": self._error,
        }
        return state

    # -- description
    def schema(self) -> dict[str, Any]:
        return {"adapter": self.id, "sections": {"fields": "Champs extraits du journal par les règles"},
                "fields": {r.field: {"type": "int" if r.mode == "count" else r.type, "mode": r.mode,
                                     "private": r.private, "description": r.description} for r in self.rules}}

    def widgets(self) -> list[dict[str, Any]]:
        return [{"id": f"{self.id}_fields", "title": self.game, "section": "fields",
                 "note": "Champs extraits du journal"}]

    def privacy_filter(self, state: dict[str, Any], mode: str) -> dict[str, Any]:
        if check_mode(mode) == PRIVACY_OFF:
            return copy.deepcopy(state)
        private = {r.field for r in self.rules if r.private}
        fields = {k: (MASK if k in private else v) for k, v in (state.get("fields") or {}).items()}
        return filter_state({**state, "fields": fields}, self.options)

    def context_for_llm(self, state: dict[str, Any]) -> str:
        fields = state.get("fields") or {}
        if not fields:
            return f"Contexte {self.game} : aucune donnée lue dans le journal pour l'instant."
        parts = []
        for name, value in fields.items():
            shown = ", ".join(str(v) for v in value[-5:]) if isinstance(value, list) else value
            parts.append(f"{name} = {shown}")
        return f"Contexte {self.game} : " + " ; ".join(parts) + "."
