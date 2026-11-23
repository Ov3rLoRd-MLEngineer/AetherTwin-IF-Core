"""
Rentabilité des recettes : coût des composants achetés à l'Hôtel des ventes, comparé au prix de vente de l'objet
fabriqué (moins la commission de 5 % de l'Hôtel des ventes).

- Recettes : lues par l'addon quand la fenêtre d'un métier est ouverte (l'addon 1.11 ajoute l'objet fabriqué).
- Prix : ceux de l'onglet Hôtel des ventes (Battle.net, TradeSkillMaster, Auctionator), voir addon_data.Market.
- Composants de base seulement : les composants optionnels et la qualité (rangs) ne sont pas comptés ; pour un
  composant qui existe en plusieurs rangs, on prend le moins cher. C'est une estimation, pas un conseil d'achat.
"""

AH_CUT = 0.05


def _unit_price(market, ids):
    prices = [p for p in (market.estimate(int(i))[0] for i in ids or [] if i) if p]
    return min(prices) if prices else None


def recipe_profit(recipe, market):
    """{"name", "profession", "out", "cost", "value", "profit", "missing": [composants sans prix]} ou None si la
    recette ne dit pas quel objet elle fabrique (recettes lues avant l'addon 1.11)."""
    out_id = int(recipe.get("out") or 0)
    if not out_id:
        return None
    cost, missing = 0, []
    for m in recipe.get("materials") or recipe.get("mats") or []:
        ids = m.get("item_ids") or m.get("ids") or ([m["item_id"]] if m.get("item_id") else [])
        price = _unit_price(market, ids)
        if price is None:
            missing.append(m.get("name") or f"objet {ids[0] if ids else '?'}")
            continue
        cost += price * int(m.get("quantity") or 1)
    sale, source = market.estimate(out_id)
    quantity = float(recipe.get("outQty") or 1) or 1.0
    value = int(sale * quantity * (1 - AH_CUT)) if sale else None
    profit = value - cost if value is not None and not missing else None
    return {"name": recipe.get("name", ""), "profession": recipe.get("profession", ""), "out": out_id,
            "quantity": quantity, "cost": cost, "value": value, "profit": profit, "missing": missing,
            "source": source or ""}


def ranking(recipes, market, profession=""):
    """Recettes classées de la plus rentable à la moins rentable ; celles qu'on ne peut pas chiffrer à la fin."""
    rows = []
    for recipe in recipes or []:
        if profession and recipe.get("profession") != profession:
            continue
        row = recipe_profit(recipe, market)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: (r["profit"] is None, -(r["profit"] or 0), r["name"]))
    return rows


def describe(rows, money, limit=25):
    """Texte pour Hermes : une ligne par recette (prix déjà convertis par `money`)."""
    lines = []
    for r in rows[:limit]:
        if r["profit"] is None:
            why = ("composants sans prix : " + ", ".join(r["missing"][:3])) if r["missing"] else "objet sans prix"
            lines.append(f"- {r['name']} ({r['profession']}) : non chiffrable ({why})")
        else:
            lines.append(f"- {r['name']} ({r['profession']}) : coût {money(r['cost'])}, vente nette "
                         f"{money(r['value'])}, bénéfice {'-' if r['profit'] < 0 else ''}{money(abs(r['profit']))}")
    return "\n".join(lines)


ADVICE_PROMPT = ("Voici la rentabilité estimée de mes recettes (prix de l'Hôtel des ventes relevés par WoW Assistant, "
                 "commission de 5 % déduite, composants de base seulement). Dis-moi ce qui vaut la peine d'être "
                 "fabriqué et vendu, en tenant compte des quantités vendues (un objet rare se vend lentement), de la "
                 "qualité (rangs) et de mes spécialisations de métier. Vérifie en ligne si un prix te semble "
                 "aberrant.\n\n")
