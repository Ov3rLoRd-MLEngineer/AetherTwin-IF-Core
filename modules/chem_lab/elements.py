"""Tableau périodique embarqué : 118 éléments (nom français, masse atomique, groupe, famille, électronégativité).

Masses : valeurs abrégées de l'UICPA ; entre crochets, nombre de masse de l'isotope le plus stable (élément sans
masse atomique standard). Électronégativité : échelle de Pauling, « - » quand elle n'est pas connue.
Groupe « f » : lanthanides et actinides, rangés sous le tableau.
"""
from __future__ import annotations

from typing import Any

CATEGORIES = {
    "am": "métal alcalin", "at": "métal alcalino-terreux", "mt": "métal de transition", "mp": "métal pauvre",
    "md": "métalloïde", "nm": "non-métal", "ha": "halogène", "gn": "gaz noble", "la": "lanthanide",
    "ac": "actinide", "in": "propriétés inconnues",
}
GASES = {"H", "He", "N", "O", "F", "Ne", "Cl", "Ar", "Kr", "Xe", "Rn"}
LIQUIDS = {"Br", "Hg"}

# Z symbole nom masse groupe famille électronégativité
_TABLE = """
1 H Hydrogène 1.008 1 nm 2.20
2 He Hélium 4.0026 18 gn -
3 Li Lithium 6.94 1 am 0.98
4 Be Béryllium 9.0122 2 at 1.57
5 B Bore 10.81 13 md 2.04
6 C Carbone 12.011 14 nm 2.55
7 N Azote 14.007 15 nm 3.04
8 O Oxygène 15.999 16 nm 3.44
9 F Fluor 18.998 17 ha 3.98
10 Ne Néon 20.180 18 gn -
11 Na Sodium 22.990 1 am 0.93
12 Mg Magnésium 24.305 2 at 1.31
13 Al Aluminium 26.982 13 mp 1.61
14 Si Silicium 28.085 14 md 1.90
15 P Phosphore 30.974 15 nm 2.19
16 S Soufre 32.06 16 nm 2.58
17 Cl Chlore 35.45 17 ha 3.16
18 Ar Argon 39.95 18 gn -
19 K Potassium 39.098 1 am 0.82
20 Ca Calcium 40.078 2 at 1.00
21 Sc Scandium 44.956 3 mt 1.36
22 Ti Titane 47.867 4 mt 1.54
23 V Vanadium 50.942 5 mt 1.63
24 Cr Chrome 51.996 6 mt 1.66
25 Mn Manganèse 54.938 7 mt 1.55
26 Fe Fer 55.845 8 mt 1.83
27 Co Cobalt 58.933 9 mt 1.88
28 Ni Nickel 58.693 10 mt 1.91
29 Cu Cuivre 63.546 11 mt 1.90
30 Zn Zinc 65.38 12 mt 1.65
31 Ga Gallium 69.723 13 mp 1.81
32 Ge Germanium 72.630 14 md 2.01
33 As Arsenic 74.922 15 md 2.18
34 Se Sélénium 78.971 16 nm 2.55
35 Br Brome 79.904 17 ha 2.96
36 Kr Krypton 83.798 18 gn 3.00
37 Rb Rubidium 85.468 1 am 0.82
38 Sr Strontium 87.62 2 at 0.95
39 Y Yttrium 88.906 3 mt 1.22
40 Zr Zirconium 91.224 4 mt 1.33
41 Nb Niobium 92.906 5 mt 1.6
42 Mo Molybdène 95.95 6 mt 2.16
43 Tc Technétium [98] 7 mt 1.9
44 Ru Ruthénium 101.07 8 mt 2.2
45 Rh Rhodium 102.91 9 mt 2.28
46 Pd Palladium 106.42 10 mt 2.20
47 Ag Argent 107.87 11 mt 1.93
48 Cd Cadmium 112.41 12 mt 1.69
49 In Indium 114.82 13 mp 1.78
50 Sn Étain 118.71 14 mp 1.96
51 Sb Antimoine 121.76 15 md 2.05
52 Te Tellure 127.60 16 md 2.1
53 I Iode 126.90 17 ha 2.66
54 Xe Xénon 131.29 18 gn 2.6
55 Cs Césium 132.91 1 am 0.79
56 Ba Baryum 137.33 2 at 0.89
57 La Lanthane 138.91 f la 1.10
58 Ce Cérium 140.12 f la 1.12
59 Pr Praséodyme 140.91 f la 1.13
60 Nd Néodyme 144.24 f la 1.14
61 Pm Prométhium [145] f la 1.13
62 Sm Samarium 150.36 f la 1.17
63 Eu Europium 151.96 f la 1.2
64 Gd Gadolinium 157.25 f la 1.2
65 Tb Terbium 158.93 f la 1.1
66 Dy Dysprosium 162.50 f la 1.22
67 Ho Holmium 164.93 f la 1.23
68 Er Erbium 167.26 f la 1.24
69 Tm Thulium 168.93 f la 1.25
70 Yb Ytterbium 173.05 f la 1.1
71 Lu Lutécium 174.97 f la 1.27
72 Hf Hafnium 178.49 4 mt 1.3
73 Ta Tantale 180.95 5 mt 1.5
74 W Tungstène 183.84 6 mt 2.36
75 Re Rhénium 186.21 7 mt 1.9
76 Os Osmium 190.23 8 mt 2.2
77 Ir Iridium 192.22 9 mt 2.20
78 Pt Platine 195.08 10 mt 2.28
79 Au Or 196.97 11 mt 2.54
80 Hg Mercure 200.59 12 mt 2.00
81 Tl Thallium 204.38 13 mp 1.62
82 Pb Plomb 207.2 14 mp 2.33
83 Bi Bismuth 208.98 15 mp 2.02
84 Po Polonium [209] 16 md 2.0
85 At Astate [210] 17 ha 2.2
86 Rn Radon [222] 18 gn 2.2
87 Fr Francium [223] 1 am 0.7
88 Ra Radium [226] 2 at 0.9
89 Ac Actinium [227] f ac 1.1
90 Th Thorium 232.04 f ac 1.3
91 Pa Protactinium 231.04 f ac 1.5
92 U Uranium 238.03 f ac 1.38
93 Np Neptunium [237] f ac 1.36
94 Pu Plutonium [244] f ac 1.28
95 Am Américium [243] f ac 1.13
96 Cm Curium [247] f ac 1.28
97 Bk Berkélium [247] f ac 1.3
98 Cf Californium [251] f ac 1.3
99 Es Einsteinium [252] f ac 1.3
100 Fm Fermium [257] f ac 1.3
101 Md Mendélévium [258] f ac 1.3
102 No Nobélium [259] f ac 1.3
103 Lr Lawrencium [266] f ac -
104 Rf Rutherfordium [267] 4 mt -
105 Db Dubnium [268] 5 mt -
106 Sg Seaborgium [269] 6 mt -
107 Bh Bohrium [270] 7 mt -
108 Hs Hassium [269] 8 mt -
109 Mt Meitnérium [278] 9 in -
110 Ds Darmstadtium [281] 10 in -
111 Rg Roentgenium [282] 11 in -
112 Cn Copernicium [285] 12 in -
113 Nh Nihonium [286] 13 in -
114 Fl Flérovium [289] 14 in -
115 Mc Moscovium [290] 15 in -
116 Lv Livermorium [293] 16 in -
117 Ts Tennesse [294] 17 in -
118 Og Oganesson [294] 18 in -
"""


def period_of(z: int) -> int:
    for period, last in enumerate((2, 10, 18, 36, 54, 86, 118), start=1):
        if z <= last:
            return period
    raise ValueError(z)


def _load() -> list[dict[str, Any]]:
    out = []
    for line in _TABLE.strip().splitlines():
        z, sym, name, mass, group, cat, en = line.split()
        stable = mass.startswith("[")
        out.append({
            "z": int(z), "symbol": sym, "name": name, "mass": float(mass.strip("[]")), "radioactive_only": stable,
            "group": None if group == "f" else int(group), "period": period_of(int(z)), "category": cat,
            "category_name": CATEGORIES[cat], "electronegativity": None if en == "-" else float(en),
            "state": "?" if int(z) >= 104 else "gaz" if sym in GASES else "liquide" if sym in LIQUIDS else "solide",
        })
    return out


ELEMENTS: list[dict[str, Any]] = _load()
BY_SYMBOL: dict[str, dict[str, Any]] = {e["symbol"]: e for e in ELEMENTS}
MASS: dict[str, float] = {e["symbol"]: e["mass"] for e in ELEMENTS}


def element(key: Any) -> dict[str, Any]:
    """Un élément par symbole (« Fe »), numéro atomique (26) ou nom français (« fer »)."""
    text = str(key).strip()
    if text.isdigit() and 1 <= int(text) <= 118:
        return ELEMENTS[int(text) - 1]
    if text in BY_SYMBOL:
        return BY_SYMBOL[text]
    low = text.lower()
    for e in ELEMENTS:
        if e["name"].lower() == low or e["symbol"].lower() == low:
            return e
    raise ValueError(f"élément inconnu : {text!r}")
