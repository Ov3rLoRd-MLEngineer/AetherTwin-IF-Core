"""
Client de l'API officielle Battle.net (Blizzard) — facultatif, désactivé tant qu'aucun identifiant n'est saisi.

Ce que l'appli en tire :
  - le rendu officiel du personnage (équipement et transmogrification réels) : remplace l'emplacement « Modèle 3D » ;
  - l'image des montures (affichage de la créature) ;
  - les prix de l'Hôtel des ventes : marchandises (toute la région) et objets du royaume connecté, mis à jour
    par Blizzard environ une fois par heure.

Identifiants : un « client » gratuit créé sur https://develop.battle.net (compte Battle.net) ; client ID et secret
saisis dans l'onglet Hôtel des ventes, gardés dans settings.json sur ce PC. Lecture seule, rien n'est envoyé au jeu.
Chaque réponse est mise en cache dans cache/bnet/ (prix : 1 h ; images : 7 jours).
"""
import base64
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

REGIONS = ("eu", "us", "kr", "tw")
LOCALES = {"eu": "fr_FR", "us": "en_US", "kr": "ko_KR", "tw": "zh_TW"}
TOKEN_URL = "https://oauth.battle.net/token"
API_URL = "https://{region}.api.blizzard.com"
HOUR, WEEK = 3600, 7 * 24 * 3600


class BnetError(Exception):
    pass


def realm_slug(name):
    """« Marécage de Zangar » → « marecage-de-zangar » (forme utilisée par l'API quand l'index n'est pas lu)."""
    plain = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode("ascii")
    plain = plain.replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def market_summary(listings):
    """[(prix unitaire en cuivre, quantité)] → {"min", "market", "quantity", "listings"}.
    Prix du marché : moyenne pondérée des 15 % les moins chers de la quantité en vente (les prix aberrants du
    haut ne comptent pas, un seul lot bradé non plus)."""
    rows = sorted((int(p), int(q)) for p, q in listings if p and q and int(p) > 0 and int(q) > 0)
    if not rows:
        return None
    total = sum(q for _p, q in rows)
    want, taken, value = max(1, int(total * 0.15)), 0, 0
    for price, quantity in rows:
        take = min(quantity, want - taken)
        value += price * take
        taken += take
        if taken >= want:
            break
    return {"min": rows[0][0], "market": int(value / taken), "quantity": total, "listings": len(rows)}


class BattleNet:
    """Requêtes à l'API avec jeton OAuth (identifiants client) et cache disque."""

    TIMEOUT = 30

    def __init__(self, settings, cache_dir, opener=None):
        self.settings = settings
        self.cache_dir = cache_dir
        self.opener = opener or urllib.request.urlopen
        self._token, self._token_until = "", 0.0
        self._lock = threading.Lock()
        self.last_error = ""

    # ------------------------------------------------------------------ réglages
    def _cfg(self, key, default=""):
        return self.settings.get(f"bnet.{key}", default)

    def configured(self):
        return bool(self._cfg("client_id")) and bool(self._cfg("client_secret"))

    @property
    def region(self):
        region = str(self._cfg("region", "eu") or "eu").lower()
        return region if region in REGIONS else "eu"

    # ------------------------------------------------------------------ HTTP
    def _open(self, request):
        with self.opener(request, timeout=self.TIMEOUT) as response:
            return response.read()

    def token(self):
        with self._lock:
            if self._token and time.time() < self._token_until - 60:
                return self._token
            if not self.configured():
                raise BnetError("identifiants Battle.net non renseignés")
            auth = base64.b64encode(f"{self._cfg('client_id')}:{self._cfg('client_secret')}".encode()).decode()
            request = urllib.request.Request(TOKEN_URL, data=b"grant_type=client_credentials", method="POST",
                                             headers={"Authorization": "Basic " + auth,
                                                      "Content-Type": "application/x-www-form-urlencoded"})
            try:
                data = json.loads(self._open(request).decode("utf-8"))
            except urllib.error.HTTPError as e:
                raise BnetError("identifiants refusés par Battle.net" if e.code in (400, 401)
                                else f"Battle.net : erreur {e.code}") from e
            except (urllib.error.URLError, OSError, ValueError) as e:
                raise BnetError(f"Battle.net injoignable : {e}") from e
            self._token = str(data.get("access_token", ""))
            self._token_until = time.time() + float(data.get("expires_in", 3600))
            if not self._token:
                raise BnetError("réponse de jeton inattendue")
            return self._token

    def _cache_path(self, key, ext):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)[:150]
        return os.path.join(self.cache_dir, f"{safe}.{ext}")

    def _fresh(self, path, max_age):
        return os.path.isfile(path) and time.time() - os.path.getmtime(path) < max_age

    def get(self, path, namespace, max_age=HOUR, params=None):
        """JSON d'un point de l'API (`namespace` : static, dynamic ou profile), mis en cache `max_age` secondes."""
        query = {"namespace": f"{namespace}-{self.region}", "locale": LOCALES[self.region], **(params or {})}
        url = API_URL.format(region=self.region) + path + "?" + urllib.parse.urlencode(query)
        cache = self._cache_path(f"{self.region}{path}{namespace}", "json")
        if self._fresh(cache, max_age):
            with open(cache, encoding="utf-8") as f:
                return json.load(f)
        request = urllib.request.Request(url, headers={"Authorization": "Bearer " + self.token(),
                                                       "User-Agent": "WoWAssistant/1.8"})
        try:
            data = json.loads(self._open(request).decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                hint = " (personnage jamais vu par l'API, ou royaume mal reconnu)" if "/profile/" in path else ""
                raise BnetError("introuvable sur Battle.net" + hint) from e
            raise BnetError(f"Battle.net : erreur {e.code}") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise BnetError(f"Battle.net injoignable : {e}") from e
        os.makedirs(self.cache_dir, exist_ok=True)
        tmp = cache + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, cache)
        return data

    def download(self, url, key, max_age=WEEK):
        """Fichier (image) téléchargé dans le cache ; rend son chemin. Seuls les médias de Blizzard sont acceptés."""
        host = urllib.parse.urlsplit(url).hostname or ""
        if not host.endswith((".blizzard.com", ".battle.net", ".blizzard.cn", ".worldofwarcraft.com")):
            raise BnetError(f"adresse de média inattendue : {host}")
        ext = os.path.splitext(urllib.parse.urlsplit(url).path)[1].lstrip(".").lower() or "png"
        path = self._cache_path(key, ext if ext in ("png", "jpg", "jpeg", "webp") else "png")
        if self._fresh(path, max_age):
            return path
        request = urllib.request.Request(url, headers={"User-Agent": "WoWAssistant/1.8"})
        try:
            body = self._open(request)
        except (urllib.error.URLError, OSError) as e:
            raise BnetError(f"image injoignable : {e}") from e
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
        return path

    # ------------------------------------------------------------------ royaumes
    def realm(self, realm_name):
        """Royaume (slug, id du royaume connecté) d'après son nom tel que le jeu l'affiche."""
        index = self.get("/data/wow/realm/index", "dynamic", max_age=WEEK)
        wanted = realm_slug(realm_name)
        slug = next((r.get("slug") for r in index.get("realms", [])
                     if r.get("slug") == wanted or str(r.get("name", "")).lower() == realm_name.lower()), wanted)
        detail = self.get(f"/data/wow/realm/{slug}", "dynamic", max_age=WEEK)
        href = str((detail.get("connected_realm") or {}).get("href", ""))
        match = re.search(r"/connected-realm/(\d+)", href)
        return {"slug": slug, "connected_realm": int(match.group(1)) if match else None}

    # ------------------------------------------------------------------ médias
    def character_render(self, realm_name, character_name):
        """Chemin de l'image du personnage en pied (« main-raw », fond transparent), à défaut « main » ou « inset »."""
        slug = self.realm(realm_name)["slug"]
        name = urllib.parse.quote(character_name.lower())
        media = self.get(f"/profile/wow/character/{slug}/{name}/character-media", "profile", max_age=HOUR * 6)
        assets = {a.get("key"): a.get("value") for a in media.get("assets", []) if isinstance(a, dict)}
        for key in ("main-raw", "main", "inset", "avatar"):
            if assets.get(key):
                return self.download(assets[key], f"char_{self.region}_{slug}_{character_name.lower()}_{key}", HOUR * 6)
        raise BnetError("aucun rendu proposé pour ce personnage")

    def _display_image(self, displays, key, what):
        """Image « zoom » du premier affichage de créature de la liste (montures, mascottes)."""
        if not displays:
            raise BnetError(f"pas d'affichage pour cette {what}")
        display = self.get(f"/data/wow/media/creature-display/{int(displays[0]['id'])}", "static", max_age=WEEK * 4)
        assets = {a.get("key"): a.get("value") for a in display.get("assets", []) if isinstance(a, dict)}
        url = assets.get("zoom") or next(iter(assets.values()), None)
        if not url:
            raise BnetError(f"pas d'image pour cette {what}")
        return self.download(url, key, WEEK * 4)

    def mount_image(self, mount_id):
        """Image de la monture (« zoom » de son affichage de créature)."""
        mount = self.get(f"/data/wow/mount/{int(mount_id)}", "static", max_age=WEEK * 4)
        return self._display_image(mount.get("creature_displays") or [], f"mount_{int(mount_id)}", "monture")

    def pet_image(self, species_id, creature_id=0):
        """Image de la mascotte : sa créature (exportée par l'addon, sinon lue dans la fiche de l'espèce),
        puis le « zoom » de son affichage."""
        if not creature_id:
            pet = self.get(f"/data/wow/pet/{int(species_id)}", "static", max_age=WEEK * 4)
            creature_id = (pet.get("creature") or {}).get("id")
            if not creature_id:
                raise BnetError("pas de créature pour cette mascotte")
        creature = self.get(f"/data/wow/creature/{int(creature_id)}", "static", max_age=WEEK * 4)
        return self._display_image(creature.get("creature_displays") or [], f"pet_{int(species_id)}", "mascotte")

    def creature_image(self, creature_id):
        """Image d'une créature du bestiaire (même source que les montures et les mascottes)."""
        creature = self.get(f"/data/wow/creature/{int(creature_id)}", "static", max_age=WEEK * 4)
        return self._display_image(creature.get("creature_displays") or [], f"npc_{int(creature_id)}", "créature")

    def set_pieces(self, set_id):
        """Pièces d'un ensemble de transmogrification : [{"item": id d'un objet qui la donne, "slot": nom}].
        Battle.net ne propose pas de rendu des objets : l'appli affiche leurs icônes."""
        data = self.get(f"/data/wow/item-appearance/set/{int(set_id)}", "static", max_age=WEEK * 4)
        pieces = []
        for ref in (data.get("appearances") or [])[:16]:
            if not isinstance(ref, dict) or not ref.get("id"):
                continue
            appearance = self.get(f"/data/wow/item-appearance/{int(ref['id'])}", "static", max_age=WEEK * 4)
            items = [i for i in appearance.get("items") or [] if isinstance(i, dict) and i.get("id")]
            if items:
                pieces.append({"item": int(items[0]["id"]), "name": items[0].get("name", ""),
                               "slot": (appearance.get("slot") or {}).get("name", "")})
        if not pieces:
            raise BnetError("aucune pièce connue pour cet ensemble")
        return pieces

    # ------------------------------------------------------------------ Hôtel des ventes
    def commodities(self):
        """{item_id: résumé} des marchandises (minerais, herbes, composants…), communes à toute la région."""
        data = self.get("/data/wow/auctions/commodities", "dynamic", max_age=HOUR)
        return self._summaries(data, lambda a: a.get("unit_price"))

    def realm_auctions(self, realm_name):
        """{item_id: résumé} des objets non empilables (équipement, montures…) du royaume connecté."""
        connected = self.realm(realm_name)["connected_realm"]
        if not connected:
            raise BnetError("royaume connecté introuvable")
        data = self.get(f"/data/wow/connected-realm/{connected}/auctions", "dynamic", max_age=HOUR)
        # « buyout » est le prix du lot entier : ramené à l'unité
        return self._summaries(data, lambda a: (a["buyout"] // max(1, int(a.get("quantity", 1))) if a.get("buyout")
                                                else a.get("unit_price")))

    @staticmethod
    def _summaries(data, price_of):
        listings = {}
        for auction in data.get("auctions", []) or []:
            item = auction.get("item") or {}
            if "id" not in item:
                continue
            price = price_of(auction)
            if price:
                listings.setdefault(int(item["id"]), []).append((price, auction.get("quantity", 1)))
        out = {}
        for item_id, rows in listings.items():
            summary = market_summary(rows)
            if summary:
                out[item_id] = summary
        return out
