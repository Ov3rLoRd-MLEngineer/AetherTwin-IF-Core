"""Calculs de genesis_lab : chaque fonction est comparée à une valeur de référence connue."""
from __future__ import annotations

import math

import pytest

from modules.genesis_lab import astro, bio, chem

FASTA = """>seq1 gène de démonstration
ATGGCCGCCGCC
TAA
; un commentaire
>seq2
GGGGCCCCAATT
"""


# --------------------------------------------------------------------------- bio-informatique
def test_parse_fasta() -> None:
    records = bio.parse_fasta(FASTA)
    assert [(r.name, r.description, r.sequence) for r in records] == [
        ("seq1", "gène de démonstration", "ATGGCCGCCGCCTAA"), ("seq2", "", "GGGGCCCCAATT")]


@pytest.mark.parametrize("text", ["ACGT", ">vide\n", ">\nACGT", "", ">a\nAC-GT"])
def test_parse_fasta_rejects_malformed_input(text: str) -> None:
    with pytest.raises(bio.SequenceError):
        bio.parse_fasta(text)


def test_composition_and_strands() -> None:
    assert bio.gc_percent("ATGC") == 50.0 and bio.gc_percent("GGCC") == 100.0 and bio.gc_percent("ATNN") == 0.0
    assert bio.base_counts("AACGTN") == {"A": 2, "C": 1, "G": 1, "T": 1, "N": 1}
    assert bio.reverse_complement("ATGC") == "GCAT" and bio.reverse_complement("AAACCC") == "GGGTTT"
    assert bio.transcribe("ATGC") == "AUGC"
    assert bio.melting_temperature_wallace("ATGCATGC") == 24.0
    with pytest.raises(bio.SequenceError):
        bio.gc_percent("ATXQ")
    with pytest.raises(bio.SequenceError):
        bio.gc_percent("NNNN")


def test_genetic_code() -> None:
    assert len(bio.CODON_TABLE) == 64 and sum(1 for a in bio.CODON_TABLE.values() if a == "*") == 3
    assert bio.CODON_TABLE["ATG"] == "M" and bio.CODON_TABLE["TGG"] == "W"  # les deux seuls codons uniques
    assert bio.translate("ATGGCCTAA") == "MA*" and bio.translate("ATGGCCTAA", to_stop=True) == "MA"
    assert bio.translate("ATGNNNGC") == "MX"  # codon indéterminé : X ; bases en trop ignorées
    assert bio.translate("AUGUUUUAA") == "MF*"  # l'ARN est accepté
    # les 20 acides aminés sont tous produits par la table
    assert set(bio.CODON_TABLE.values()) - {"*"} == set("ACDEFGHIKLMNPQRSTVWY")


def test_open_reading_frames_on_both_strands() -> None:
    forward = "CC" + "ATG" + "GCC" * 3 + "TAA" + "GG"
    orfs = bio.find_orfs(forward, min_aa=2)
    assert [(o.strand, o.frame, o.start, o.end, o.protein) for o in orfs] == [("+", 2, 2, 17, "MAAA")]
    assert forward[2:17] == "ATGGCCGCCGCCTAA"
    reverse = bio.find_orfs(bio.reverse_complement(forward), min_aa=2)
    assert [(o.strand, o.protein) for o in reverse] == [("-", "MAAA")]
    assert bio.find_orfs(forward, min_aa=5) == [] and bio.find_orfs("ATGGCCGCC", min_aa=1) == []  # pas de stop


def test_sequence_comparison() -> None:
    assert bio.hamming_distance("GAGCCTACTAACGGGAT", "CATCGTAATGACGGCCT") == 7  # exemple classique (Rosalind)
    with pytest.raises(bio.SequenceError):
        bio.hamming_distance("AC", "ACG")
    result = bio.global_alignment("GCATGCG", "GATTACA")  # exemple de l'article Needleman-Wunsch de Wikipédia
    assert result["score"] == 0 and len(result["aligned_a"]) == len(result["aligned_b"])
    assert result["aligned_a"].replace("-", "") == "GCATGCG" and result["aligned_b"].replace("-", "") == "GATTACA"
    same = bio.global_alignment("ACGT", "ACGT")
    assert same["score"] == 4 and same["identity_percent"] == 100.0


def test_full_fasta_analysis() -> None:
    first, second = bio.analyze_fasta(FASTA, min_orf_aa=2)
    assert first["length"] == 15 and first["longest_protein"] == "MAAA" and first["orf_count"] == 1
    assert first["gc_percent"] == pytest.approx(100 * 10 / 15, abs=0.001)  # ATG : 1 ; GCC × 3 : 9 ; TAA : 0
    assert second["gc_percent"] == pytest.approx(66.667, abs=0.001) and second["orf_count"] == 0


# --------------------------------------------------------------------------- astrophysique
def test_kepler_third_law() -> None:
    year_days = astro.seconds_to_days(astro.orbital_period_s(astro.AU_M))
    assert year_days == pytest.approx(365.2569, abs=0.01)  # année sidérale
    mars = astro.seconds_to_days(astro.orbital_period_s(astro.au_to_m(1.523679)))
    assert mars == pytest.approx(686.98, abs=0.1)
    geostationary = astro.semi_major_axis_m(86_164.1, astro.GM_EARTH)  # un jour sidéral
    assert geostationary / 1000 == pytest.approx(42_164, abs=2)
    assert astro.semi_major_axis_m(astro.orbital_period_s(3e11)) == pytest.approx(3e11, rel=1e-12)


def test_orbital_speeds() -> None:
    iss = astro.EARTH_RADIUS_M + 408e3
    assert astro.circular_speed_m_s(iss) == pytest.approx(7_665, abs=15)
    assert astro.orbital_period_s(iss, astro.GM_EARTH) / 60 == pytest.approx(92.6, abs=0.3)
    assert astro.escape_speed_m_s(astro.EARTH_RADIUS_M) == pytest.approx(11_186, abs=10)
    earth_speed = astro.vis_viva_speed_m_s(astro.AU_M, astro.AU_M)
    assert earth_speed == pytest.approx(29_785, abs=10)
    assert earth_speed == pytest.approx(astro.circular_speed_m_s(astro.AU_M, astro.GM_SUN))
    assert astro.schwarzschild_radius_m(astro.M_SUN_KG) == pytest.approx(2_953, abs=2)
    with pytest.raises(ValueError, match="orbite"):
        astro.vis_viva_speed_m_s(3.0, 1.0)


def test_magnitudes_and_distances() -> None:
    sun_distance_pc = astro.AU_M / astro.PARSEC_M
    assert astro.absolute_magnitude(-26.74, sun_distance_pc) == pytest.approx(4.83, abs=0.01)  # Soleil
    assert astro.absolute_magnitude(-1.46, 2.64) == pytest.approx(1.43, abs=0.01)  # Sirius
    assert astro.absolute_magnitude(7.0, 10.0) == 7.0
    assert astro.distance_pc_from_magnitudes(-1.46, 1.43) == pytest.approx(2.64, abs=0.01)
    proxima = astro.distance_pc_from_parallax(0.7685)
    assert proxima == pytest.approx(1.3012, abs=0.0005) and astro.pc_to_ly(proxima) == pytest.approx(4.244, abs=0.002)
    assert astro.flux_ratio(1.0, 6.0) == pytest.approx(100.0)
    assert astro.ly_to_pc(astro.pc_to_ly(3.0)) == pytest.approx(3.0)
    assert astro.pc_to_ly(1.0) == pytest.approx(3.2616, abs=0.0001)


@pytest.mark.parametrize("call", [lambda: astro.orbital_period_s(-1.0), lambda: astro.absolute_magnitude(1.0, 0.0),
                                  lambda: astro.escape_speed_m_s(float("nan")),
                                  lambda: astro.distance_pc_from_parallax(0.0)])
def test_astro_rejects_impossible_values(call) -> None:
    with pytest.raises(ValueError, match="strictement positif"):
        call()


# --------------------------------------------------------------------------- génie chimique
@pytest.mark.parametrize(("formula", "expected"), [("H2O", 18.015), ("CO2", 44.009), ("NaCl", 58.44),
                                                   ("C6H12O6", 180.156), ("Ca(OH)2", 74.092),
                                                   ("Al2(SO4)3", 342.13), ("Ca3(PO4)2", 310.17), ("O2", 31.998)])
def test_molar_masses(formula: str, expected: float) -> None:
    assert chem.molar_mass_g_mol(formula) == pytest.approx(expected, abs=0.03)


def test_formula_parsing() -> None:
    assert chem.parse_formula("Al2(SO4)3") == {"Al": 2, "S": 3, "O": 12}
    assert chem.parse_formula("Mg(OH)2") == {"Mg": 1, "O": 2, "H": 2}
    assert chem.parse_formula("C2H5OH") == {"C": 2, "H": 6, "O": 1}
    assert chem.parse_formula("K4Fe(CN)6") == {"K": 4, "Fe": 1, "C": 6, "N": 6}
    fractions = chem.mass_fractions("H2O")
    assert fractions["H"] == pytest.approx(0.1119, abs=0.0002) and sum(fractions.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("formula", ["", "H2O)", "(H2O", "Xx2", "2H", "()", "H0", "h2o", "H2-O"])
def test_invalid_formulas_are_rejected(formula: str) -> None:
    with pytest.raises(chem.ChemistryError):
        chem.parse_formula(formula)


def test_moles_and_ideal_gas() -> None:
    assert chem.moles_from_mass(180.156, "C6H12O6") == pytest.approx(1.0, abs=1e-4)
    assert chem.mass_g_from_moles(2.0, "H2O") == pytest.approx(36.03, abs=0.01)
    molar_volume = chem.ideal_gas_volume_m3(1.0, 273.15, chem.ATM_PA)
    assert molar_volume * 1000 == pytest.approx(22.414, abs=0.001)  # litres par mole dans les conditions normales
    assert chem.ideal_gas_moles(chem.ATM_PA, molar_volume, 273.15) == pytest.approx(1.0)
    assert chem.celsius_to_kelvin(25.0) == 298.15
    with pytest.raises(chem.ChemistryError):
        chem.celsius_to_kelvin(-300.0)


def test_mass_balances() -> None:
    out = chem.mix_streams([{"flow_kg_h": 100.0, "fractions": {"sel": 0.10, "eau": 0.90}},
                            {"flow_kg_h": 300.0, "fractions": {"eau": 1.0}}])
    assert out["flow_kg_h"] == 400.0 and out["fractions"]["sel"] == pytest.approx(0.025)
    assert out["component_kg_h"] == {"sel": pytest.approx(10.0), "eau": pytest.approx(390.0)}  # chaque espèce conservée
    assert sum(out["fractions"].values()) == pytest.approx(1.0)
    assert chem.dilution_volume(12.0, 10.0, 1.0) == pytest.approx(120.0)
    closure = chem.balance_closure([100.0, 300.0], [398.0])
    assert closure["gap_kg_h"] == pytest.approx(2.0) and closure["gap_percent"] == pytest.approx(0.5)
    with pytest.raises(chem.ChemistryError, match="sommer à 1"):
        chem.mix_streams([{"flow_kg_h": 1.0, "fractions": {"a": 0.5, "b": 0.6}}])
    with pytest.raises(chem.ChemistryError, match="augmenter"):
        chem.dilution_volume(1.0, 10.0, 2.0)


def test_equilibria() -> None:
    assert chem.ph_strong_acid(0.01) == pytest.approx(2.0) and chem.ph_strong_base(0.01) == pytest.approx(12.0)
    assert chem.ph_weak_acid(0.1, 1.8e-5) == pytest.approx(2.875, abs=0.005)  # acide acétique 0,1 mol/L
    approximation = -math.log10(math.sqrt(1.8e-5 * 0.1))
    assert chem.ph_weak_acid(0.1, 1.8e-5) > approximation  # la résolution exacte corrige l'approximation usuelle
    assert chem.ph_buffer(4.76, 0.1, 0.1) == pytest.approx(4.76)
    assert chem.ph_buffer(4.76, 1.0, 0.1) == pytest.approx(5.76)
    assert chem.equilibrium_constant(-5708.0) == pytest.approx(10.0, abs=0.01)  # ΔG° = −RT ln 10 à 298,15 K
    assert chem.equilibrium_constant(0.0) == 1.0
