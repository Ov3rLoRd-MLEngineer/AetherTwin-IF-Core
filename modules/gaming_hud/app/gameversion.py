"""
Version du jeu installé, lue dans le fichier `.build.info` du dossier de World of Warcraft (lecture seule).

Sert à dater les faits de la base de connaissances du coach : un fait vérifié en 12.1.5 est à revérifier quand le
jeu passe en 12.2.0. Donne aussi la variante du jeu (Retail, Forever, Classic) d'après le dossier utilisé.
"""
import os

# dossier du jeu -> produit Battle.net dans .build.info ; Forever : produit pas encore connu, on le devine
FOLDER_PRODUCTS = {"_retail_": "wow", "_ptr_": "wowt", "_xptr_": "wowxptr", "_beta_": "wow_beta",
                   "_classic_": "wow_classic", "_classic_era_": "wow_classic_era", "_classic_ptr_": "wow_classic_ptr"}
FLAVORS = {"_retail_": "retail", "_ptr_": "retail", "_xptr_": "retail", "_beta_": "retail", "_forever_": "forever",
           "_classic_": "classic", "_classic_era_": "classic", "_classic_ptr_": "classic"}

_cache = {}


def flavor(game_path):
    """« retail », « forever », « classic » d'après le dossier (_retail_, _forever_...) ; « retail » par défaut."""
    folder = os.path.basename(os.path.normpath(game_path or "")).lower()
    return FLAVORS.get(folder, "retail")


def _rows(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [line.rstrip("\r\n") for line in f if line.strip()]
    if not lines:
        return []
    header = [h.split("!")[0] for h in lines[0].split("|")]
    return [dict(zip(header, line.split("|"))) for line in lines[1:]]


def build_info(game_path):
    """{"product", "version" (12.1.5.70961), "patch" (12.1.5), "flavor"} ou {} si introuvable."""
    if not game_path:
        return {}
    folder = os.path.basename(os.path.normpath(game_path)).lower()
    path = os.path.join(os.path.dirname(os.path.normpath(game_path)), ".build.info")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    key = (path, folder)
    if key in _cache and _cache[key][0] == mtime:
        return _cache[key][1]
    try:
        rows = _rows(path)
    except OSError:
        return {}
    product = FOLDER_PRODUCTS.get(folder) or folder.strip("_")
    row = (next((r for r in rows if r.get("Product") == product), None)
           or next((r for r in rows if product and product in (r.get("Product") or "")), None)
           or next((r for r in rows if r.get("Active") == "1"), None) or (rows[0] if rows else None))
    info = {}
    if row and row.get("Version"):
        version = row["Version"].strip()
        info = {"product": row.get("Product", ""), "version": version, "patch": patch_of(version),
                "flavor": FLAVORS.get(folder, "retail")}
    _cache[key] = (mtime, info)
    return info


def patch_of(version):
    """12.1.5.70961 -> 12.1.5 (les correctifs du même patch ne comptent pas)."""
    parts = [p for p in str(version or "").split(".") if p.isdigit()]
    return ".".join(parts[:3])


def patch_for(game_path):
    return build_info(game_path).get("patch", "")
