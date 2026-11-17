"""Génère la page de test de `tests/data/scantrad/` : dessin simple et répliques **écrites pour le projet**.

Aucune page de manga protégée dans le dépôt. La génération demande une police japonaise (MS Gothic ou Yu Gothic
sous Windows) ; l'image produite est versionnée, les tests n'ont donc pas besoin de la police.

    python -m modules.scantrad.testpage
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parents[2] / "tests" / "data" / "scantrad"
JP_FONTS = ["C:/Windows/Fonts/msgothic.ttc", "C:/Windows/Fonts/YuGothM.ttc", "NotoSansCJK-Regular.ttc"]

# (case, centre x, centre y, demi-largeur, demi-hauteur, lignes de texte)
BUBBLES = [
    ((40, 40, 860, 520), 640, 170, 170, 95, ["おはよう！", "今日はいい天気だね。"]),
    ((40, 40, 860, 520), 260, 330, 150, 80, ["うん、海に", "行こうか？"]),
    ((480, 560, 860, 1000), 670, 760, 140, 75, ["星がきれいだよ。"]),  # case de droite : lue en premier
    ((40, 560, 440, 1000), 240, 700, 160, 100, ["ちょっと待って、", "カメラを", "持ってくる！"]),
    ((40, 1040, 860, 1260), 600, 1150, 150, 70, ["また明日ね。"]),
]


def jp_font(size: int) -> ImageFont.FreeTypeFont:
    for path in JP_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise SystemExit("Aucune police japonaise trouvée (MS Gothic, Yu Gothic ou Noto Sans CJK).")


def generate(out_dir: Path = OUT_DIR) -> Path:
    page = Image.new("RGB", (900, 1300), "white")
    draw = ImageDraw.Draw(page)
    panels = sorted({b[0] for b in BUBBLES})
    for i, (x0, y0, x1, y1) in enumerate(panels):
        draw.rectangle((x0, y0, x1, y1), fill=(172, 172, 172), outline="black", width=4)  # trame grise
        for k in range(6):  # quelques formes, pour que la case ne soit pas vide
            cx, cy = x0 + 60 + (k * 113 + i * 37) % max(1, x1 - x0 - 120), y0 + 60 + (k * 71) % max(1, y1 - y0 - 120)
            draw.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), outline=(60, 60, 60), width=3)
            draw.line((cx - 30, cy + 35, cx + 30, cy + 35), fill=(80, 80, 80), width=2)
    font = jp_font(26)
    truth = []
    for index, (_panel, cx, cy, rx, ry, lines) in enumerate(BUBBLES, start=1):
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill="white", outline="black", width=3)
        line_h = 32
        top = cy - len(lines) * line_h / 2
        for k, line in enumerate(lines):
            width = draw.textlength(line, font=font)
            draw.text((cx - width / 2, top + k * line_h), line, font=font, fill="black")
        truth.append({"index": index, "box": [cx - rx, cy - ry, 2 * rx, 2 * ry], "text": "".join(lines)})
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / "page_test.png"
    page.save(image_path, optimize=True)
    (out_dir / "page_test.json").write_text(json.dumps({
        "licence": "page générée par modules/scantrad/testpage.py pour AetherTwin, répliques originales (Apache-2.0)",
        "bubbles": truth}, ensure_ascii=False, indent=2), encoding="utf-8")
    return image_path


if __name__ == "__main__":
    print(generate())
