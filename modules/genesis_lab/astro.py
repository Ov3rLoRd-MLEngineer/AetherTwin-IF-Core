"""Astrophysique : mécanique orbitale, magnitudes, conversions. Code déterministe, unités du SI.

Chaque fonction porte ses unités dans son nom ou dans sa documentation. Les constantes viennent des
valeurs recommandées (CODATA 2018, résolutions B2 et B3 de l'UAI 2015).
"""
from __future__ import annotations

import math

G = 6.67430e-11  # m³ kg⁻¹ s⁻², constante gravitationnelle
C = 299_792_458.0  # m/s, vitesse de la lumière (exacte)
GM_SUN = 1.3271244e20  # m³/s², paramètre gravitationnel du Soleil (UAI 2015)
GM_EARTH = 3.986004e14  # m³/s²
M_SUN_KG = GM_SUN / G
M_EARTH_KG = GM_EARTH / G
AU_M = 1.495978707e11  # m, unité astronomique (exacte)
PARSEC_M = AU_M * 648_000.0 / math.pi  # m (définition UAI 2015)
LIGHT_YEAR_M = C * 365.25 * 86_400.0  # m, année julienne
DAY_S = 86_400.0
JULIAN_YEAR_S = 365.25 * DAY_S
EARTH_RADIUS_M = 6.371e6  # m, rayon moyen


def _positive(**values: float) -> None:
    for name, value in values.items():
        if not (isinstance(value, int | float) and math.isfinite(value) and value > 0):
            raise ValueError(f"{name} doit être un nombre strictement positif (reçu : {value!r})")


# -- mécanique orbitale
def orbital_period_s(semi_major_axis_m: float, gm_m3_s2: float = GM_SUN) -> float:
    """Troisième loi de Kepler : T = 2π √(a³ / GM). `gm` = G × (masse centrale + masse du satellite)."""
    _positive(semi_major_axis_m=semi_major_axis_m, gm_m3_s2=gm_m3_s2)
    return 2.0 * math.pi * math.sqrt(semi_major_axis_m ** 3 / gm_m3_s2)


def semi_major_axis_m(period_s: float, gm_m3_s2: float = GM_SUN) -> float:
    """Inverse de la troisième loi de Kepler : a = (GM T² / 4π²)^(1/3)."""
    _positive(period_s=period_s, gm_m3_s2=gm_m3_s2)
    return (gm_m3_s2 * period_s ** 2 / (4.0 * math.pi ** 2)) ** (1.0 / 3.0)


def circular_speed_m_s(radius_m: float, gm_m3_s2: float = GM_EARTH) -> float:
    """Vitesse sur une orbite circulaire : v = √(GM / r)."""
    _positive(radius_m=radius_m, gm_m3_s2=gm_m3_s2)
    return math.sqrt(gm_m3_s2 / radius_m)


def vis_viva_speed_m_s(radius_m: float, semi_major_axis_m: float, gm_m3_s2: float = GM_SUN) -> float:
    """Équation de la vis-viva : v = √(GM (2/r − 1/a)), à la distance r sur une orbite de demi-grand axe a."""
    _positive(radius_m=radius_m, semi_major_axis_m=semi_major_axis_m, gm_m3_s2=gm_m3_s2)
    term = 2.0 / radius_m - 1.0 / semi_major_axis_m
    if term < 0:
        raise ValueError("r dépasse 2a : ce point n'est pas sur l'orbite")
    return math.sqrt(gm_m3_s2 * term)


def escape_speed_m_s(radius_m: float, gm_m3_s2: float = GM_EARTH) -> float:
    """Vitesse de libération : v = √(2 GM / r)."""
    _positive(radius_m=radius_m, gm_m3_s2=gm_m3_s2)
    return math.sqrt(2.0 * gm_m3_s2 / radius_m)


def schwarzschild_radius_m(mass_kg: float) -> float:
    """Rayon de Schwarzschild : r = 2 G M / c²."""
    _positive(mass_kg=mass_kg)
    return 2.0 * G * mass_kg / C ** 2


# -- magnitudes et distances
def absolute_magnitude(apparent_magnitude: float, distance_pc: float) -> float:
    """M = m − 5 log10(d / 10 pc)."""
    _positive(distance_pc=distance_pc)
    return apparent_magnitude - 5.0 * math.log10(distance_pc / 10.0)


def distance_pc_from_magnitudes(apparent_magnitude: float, absolute_magnitude_value: float) -> float:
    """d = 10^((m − M + 5) / 5), en parsecs (module de distance, sans extinction)."""
    return 10.0 ** ((apparent_magnitude - absolute_magnitude_value + 5.0) / 5.0)


def distance_pc_from_parallax(parallax_arcsec: float) -> float:
    """d (pc) = 1 / parallaxe (secondes d'arc)."""
    _positive(parallax_arcsec=parallax_arcsec)
    return 1.0 / parallax_arcsec


def flux_ratio(magnitude_1: float, magnitude_2: float) -> float:
    """Rapport des flux F1/F2 = 10^(−0,4 (m1 − m2)) : 5 magnitudes d'écart = un facteur 100."""
    return 10.0 ** (-0.4 * (magnitude_1 - magnitude_2))


# -- conversions
def au_to_m(value_au: float) -> float:
    return value_au * AU_M


def m_to_au(value_m: float) -> float:
    return value_m / AU_M


def pc_to_ly(value_pc: float) -> float:
    return value_pc * PARSEC_M / LIGHT_YEAR_M


def ly_to_pc(value_ly: float) -> float:
    return value_ly * LIGHT_YEAR_M / PARSEC_M


def seconds_to_days(value_s: float) -> float:
    return value_s / DAY_S
