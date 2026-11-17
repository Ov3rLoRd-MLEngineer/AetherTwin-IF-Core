"""Bio-informatique : lecture et analyse de séquences FASTA. Code déterministe, sans dépendance.

Tous les résultats sont calculés ; le LLM ne fait qu'expliquer. Biopython n'est pas requis.
Positions : indices Python (début inclus, fin exclue), comptés sur le brin lu de 5' vers 3'.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

DNA = set("ACGTN")
RNA = set("ACGUN")
COMPLEMENT = str.maketrans("ACGTNacgtn", "TGCANtgcan")
STOPS = ("TAA", "TAG", "TGA")

# Code génétique standard (table 1 du NCBI), dans l'ordre T, C, A, G pour chaque position.
_BASES = "TCAG"
_AMINO = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
CODON_TABLE = {a + b + c: _AMINO[16 * i + 4 * j + k]
               for i, a in enumerate(_BASES) for j, b in enumerate(_BASES) for k, c in enumerate(_BASES)}


class SequenceError(ValueError):
    """Séquence ou fichier FASTA invalide."""


@dataclass(frozen=True)
class FastaRecord:
    name: str
    description: str
    sequence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Orf:
    strand: str  # « + » ou « - »
    frame: int  # 0, 1 ou 2
    start: int  # sur le brin lu
    end: int  # fin exclue, codon stop compris
    protein: str  # sans le « * » final

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_fasta(text: str) -> list[FastaRecord]:
    """Lit un texte FASTA (un ou plusieurs enregistrements). Lève `SequenceError` s'il est mal formé."""
    records: list[FastaRecord] = []
    header: str | None = None
    chunks: list[str] = []

    def flush() -> None:
        if header is None:
            return
        sequence = "".join(chunks).upper()
        if not sequence:
            raise SequenceError(f"enregistrement « {header.split()[0] if header.split() else '?'} » sans séquence")
        name, _, description = header.partition(" ")
        records.append(FastaRecord(name, description.strip(), sequence))

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith(">"):
            flush()
            header, chunks = line[1:].strip(), []
            if not header:
                raise SequenceError(f"ligne {number} : en-tête FASTA vide")
        elif header is None:
            raise SequenceError(f"ligne {number} : séquence avant le premier en-tête « > »")
        else:
            cleaned = line.replace(" ", "").rstrip("*")
            if not cleaned.isalpha():
                raise SequenceError(f"ligne {number} : caractères inattendus dans la séquence")
            chunks.append(cleaned)
    flush()
    if not records:
        raise SequenceError("aucun enregistrement FASTA trouvé")
    return records


def _dna(sequence: str) -> str:
    seq = sequence.upper().replace("U", "T")
    unknown = set(seq) - DNA
    if not seq or unknown:
        raise SequenceError("séquence nucléotidique vide ou invalide"
                            + (f" (caractères : {', '.join(sorted(unknown))})" if unknown else ""))
    return seq


def base_counts(sequence: str) -> dict[str, int]:
    seq = _dna(sequence)
    return {base: seq.count(base) for base in "ACGTN"}


def gc_percent(sequence: str) -> float:
    """Pourcentage de G et C parmi les bases déterminées (les N sont exclus du dénominateur)."""
    counts = base_counts(sequence)
    known = counts["A"] + counts["C"] + counts["G"] + counts["T"]
    if known == 0:
        raise SequenceError("aucune base déterminée (uniquement des N)")
    return 100.0 * (counts["G"] + counts["C"]) / known


def reverse_complement(sequence: str) -> str:
    return _dna(sequence).translate(COMPLEMENT)[::-1]


def transcribe(sequence: str) -> str:
    """ADN (brin codant) → ARN messager."""
    return _dna(sequence).replace("T", "U")


def translate(sequence: str, to_stop: bool = False) -> str:
    """Traduit en protéine depuis la première base. Codon contenant N : « X ». Bases en trop : ignorées."""
    seq = _dna(sequence)
    protein = []
    for index in range(0, len(seq) - len(seq) % 3, 3):
        amino = CODON_TABLE.get(seq[index:index + 3], "X")
        if amino == "*" and to_stop:
            break
        protein.append(amino)
    return "".join(protein)


def find_orfs(sequence: str, min_aa: int = 30, both_strands: bool = True) -> list[Orf]:
    """Cadres de lecture ouverts ATG…stop, sur les 3 cadres (et les 2 brins). Triés du plus long au plus court."""
    if min_aa < 1:
        raise ValueError("min_aa doit être au moins 1")
    orfs = []
    strands = [("+", _dna(sequence))] + ([("-", reverse_complement(sequence))] if both_strands else [])
    for strand, seq in strands:
        for frame in range(3):
            start = None
            for index in range(frame, len(seq) - 2, 3):
                codon = seq[index:index + 3]
                if start is None and codon == "ATG":
                    start = index
                elif start is not None and codon in STOPS:
                    protein = translate(seq[start:index])
                    if len(protein) >= min_aa:
                        orfs.append(Orf(strand, frame, start, index + 3, protein))
                    start = None
    return sorted(orfs, key=lambda o: (-len(o.protein), o.strand, o.start))


def melting_temperature_wallace(sequence: str) -> float:
    """Tm d'un oligonucléotide court (règle de Wallace, valable jusqu'à ~14 bases) : 2(A+T) + 4(G+C), en °C."""
    counts = base_counts(sequence)
    if counts["N"]:
        raise SequenceError("la règle de Wallace ne s'applique pas à une séquence contenant des N")
    return 2.0 * (counts["A"] + counts["T"]) + 4.0 * (counts["G"] + counts["C"])


def hamming_distance(a: str, b: str) -> int:
    """Nombre de positions différentes entre deux séquences de même longueur."""
    if len(a) != len(b):
        raise SequenceError("la distance de Hamming demande deux séquences de même longueur")
    return sum(x != y for x, y in zip(a.upper(), b.upper(), strict=True))


def global_alignment(a: str, b: str, match: int = 1, mismatch: int = -1, gap: int = -1) -> dict[str, Any]:
    """Alignement global (Needleman-Wunsch) de deux séquences courtes. Coût en O(len(a) × len(b))."""
    a, b = a.upper(), b.upper()
    if not a or not b:
        raise SequenceError("alignement impossible avec une séquence vide")
    if len(a) * len(b) > 4_000_000:
        raise SequenceError("séquences trop longues pour cet alignement simple (limite : 4 millions de cases)")
    rows, cols = len(a) + 1, len(b) + 1
    score = [[0] * cols for _ in range(rows)]
    for i in range(1, rows):
        score[i][0] = i * gap
    for j in range(1, cols):
        score[0][j] = j * gap
    for i in range(1, rows):
        for j in range(1, cols):
            diagonal = score[i - 1][j - 1] + (match if a[i - 1] == b[j - 1] else mismatch)
            score[i][j] = max(diagonal, score[i - 1][j] + gap, score[i][j - 1] + gap)
    top, bottom = [], []
    i, j = len(a), len(b)
    while i > 0 or j > 0:
        if i > 0 and j > 0 and score[i][j] == score[i - 1][j - 1] + (match if a[i - 1] == b[j - 1] else mismatch):
            top.append(a[i - 1])
            bottom.append(b[j - 1])
            i, j = i - 1, j - 1
        elif i > 0 and score[i][j] == score[i - 1][j] + gap:
            top.append(a[i - 1])
            bottom.append("-")
            i -= 1
        else:
            top.append("-")
            bottom.append(b[j - 1])
            j -= 1
    aligned_a, aligned_b = "".join(reversed(top)), "".join(reversed(bottom))
    identical = sum(x == y and x != "-" for x, y in zip(aligned_a, aligned_b, strict=True))
    return {"score": score[len(a)][len(b)], "aligned_a": aligned_a, "aligned_b": aligned_b, "identical": identical,
            "length": len(aligned_a), "identity_percent": 100.0 * identical / len(aligned_a)}


def analyze_fasta(text: str, min_orf_aa: int = 30) -> list[dict[str, Any]]:
    """Analyse complète de chaque enregistrement : longueur, composition, GC %, ORF, protéine du plus long ORF."""
    out = []
    for record in parse_fasta(text):
        orfs = find_orfs(record.sequence, min_orf_aa)
        out.append({
            "name": record.name, "description": record.description, "length": len(record.sequence),
            "base_counts": base_counts(record.sequence), "gc_percent": round(gc_percent(record.sequence), 3),
            "orf_count": len(orfs), "orfs": [orf.to_dict() for orf in orfs[:10]],
            "longest_protein": orfs[0].protein if orfs else "",
        })
    return out
