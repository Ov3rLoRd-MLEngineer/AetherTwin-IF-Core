"""scantrad : détection et effacement sur la page de test réelle, chaîne complète avec OCR et LLM factices."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from modules.scantrad.cli import main, read_image, series_slug, write_image
from modules.scantrad.detect import clean_bubbles, clean_text, detect_bubbles, detect_text_blocks, upscale_small_page
from modules.scantrad.hub_stages import (
    Glossary,
    accept_ocr,
    make_translator,
    make_vision_ocr,
    parse_translations,
    translation_prompt,
)
from modules.scantrad.pipeline import Scantrad
from modules.scantrad.typeset import fit, font_loader, make_typesetter

DATA = Path(__file__).resolve().parents[1] / "data" / "scantrad"
TRUTH = json.loads((DATA / "page_test.json").read_text(encoding="utf-8"))["bubbles"]


@pytest.fixture(scope="module")
def page() -> np.ndarray:
    return read_image(DATA / "page_test.png")


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix, iy = max(0, min(ax + aw, bx + bw) - max(ax, bx)), max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / (aw * ah + bw * bh - inter)


def test_detects_every_bubble_in_reading_order(page) -> None:
    bubbles = detect_bubbles(page)
    assert len(bubbles) == len(TRUTH) == 5
    for found, expected in zip(bubbles, TRUTH, strict=True):
        assert iou(found.box, expected["box"]) > 0.9, (found.box, expected)  # ordre manga : droite puis gauche


def test_text_first_detector_on_the_test_page(page) -> None:
    blocks = detect_text_blocks(page)
    assert len(blocks) == 5
    for found, expected in zip(blocks, TRUTH, strict=True):
        x, y, w, h = found.box
        ex, ey, ew, eh = expected["box"]
        assert ex <= x + w / 2 <= ex + ew and ey <= y + h / 2 <= ey + eh  # centre du texte dans sa bulle
        assert found.area is not None and _contains(expected["box"], found.area, slack=6)
    cleaned = clean_text(page, blocks)
    for block in blocks:
        tx, ty, tw, th = block.text_box
        assert (cleaned[ty:ty + th, tx:tx + tw][block.text_mask > 0].min(axis=1) > 180).mean() > 0.95


def test_spaced_line_end_is_kept_but_art_does_not_grow() -> None:
    from modules.scantrad.detect import _line_like

    blocks = detect_text_blocks(read_image(DATA / "page_test.png"))
    x, _y, w, _h = blocks[2].box  # « 星がきれいだよ。» : « だよ » est séparé par un trou plus large
    assert x + w >= 745, blocks[2].box
    assert _line_like((0, 0, 130, 37), (140, 2, 20, 22))       # ligne + caractère de même hauteur
    assert not _line_like((0, 0, 110, 120), (115, 10, 20, 22))  # tache carrée du dessin
    assert not _line_like((0, 0, 130, 37), (140, 0, 20, 80))    # voisin bien plus grand


def test_ocr_crop_hides_neighbouring_text() -> None:
    from modules.scantrad.hub_stages import bubble_png
    from modules.scantrad.pipeline import Bubble

    page = np.full((300, 300, 3), 255, np.uint8)
    page[140:160, 140:160] = 0      # le bloc lu
    page[140:160, 60:80] = 0        # texte d'une bulle voisine, dans la marge de découpe
    block = Bubble(1, (140, 140, 20, 20), np.full((20, 20), 255, np.uint8), np.zeros((20, 20), np.uint8))
    crop = cv2.imdecode(np.frombuffer(bubble_png(page, block, pad=90), np.uint8), cv2.IMREAD_GRAYSCALE)
    dark = np.argwhere(crop < 128)
    assert len(dark) and dark[:, 1].min() > crop.shape[1] * 0.3  # seule l'encre du bloc, au centre, reste


def _contains(outer, inner, slack: int = 0) -> bool:
    ox, oy, ow, oh = outer
    x, y, w, h = inner
    return x >= ox - slack and y >= oy - slack and x + w <= ox + ow + slack and y + h <= oy + oh + slack


def test_columns_of_one_bubble_are_merged_and_art_is_ignored() -> None:
    from PIL import Image, ImageDraw

    from modules.scantrad.testpage import jp_font

    try:
        font = jp_font(30)
    except SystemExit:
        pytest.skip("police japonaise absente (machine sans Windows)")
    image = Image.new("RGB", (700, 1000), (225, 225, 225))  # papier scanné : jamais blanc pur
    draw = ImageDraw.Draw(image)
    draw.ellipse((380, 60, 640, 600), fill=(228, 228, 228), outline=(20, 20, 20), width=3)
    for column, text in ((540, "愛してた"), (480, "結婚して")):  # deux colonnes verticales, une bulle
        for k, char in enumerate(text):
            draw.text((column, 150 + k * 40), char, font=font, fill=(25, 25, 25))
    draw.rectangle((40, 650, 300, 950), fill=(70, 70, 70))  # dessin sombre : rien à détecter
    page = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    blocks = detect_text_blocks(page)
    assert len(blocks) == 1 and blocks[0].vertical
    x, y, w, h = blocks[0].box
    assert x <= 485 and x + w >= 565 and y <= 155 and y + h >= 300


def test_blank_page_and_drawing_without_text_give_nothing() -> None:
    blank = np.full((400, 300, 3), 255, np.uint8)
    assert detect_bubbles(blank) == []
    drawn = np.full((400, 300, 3), 170, np.uint8)
    drawn[100:200, 80:220] = 255  # zone claire fermée, mais sans texte
    assert detect_bubbles(drawn) == []


def test_cleaning_removes_text_but_keeps_outline_and_background(page) -> None:
    bubbles = detect_bubbles(page)
    cleaned = clean_bubbles(page, bubbles)
    for bubble in bubbles:
        x, y, w, h = bubble.box
        inside = cleaned[y:y + h, x:x + w][bubble.text_mask > 0]
        assert (inside.min(axis=1) > 200).mean() > 0.97  # le texte est devenu blanc
    outside = np.ones(page.shape[:2], bool)
    for bubble in bubbles:
        x, y, w, h = bubble.box
        outside[y:y + h, x:x + w] &= bubble.mask == 0
    assert np.array_equal(cleaned[outside], page[outside])  # rien d'autre n'a bougé


def test_fit_wraps_and_shrinks_text() -> None:
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    load = font_loader()
    size, lines, line_height = fit("Attends, je vais chercher mon appareil photo !", 200, 90, load, draw)
    assert len(lines) >= 2 and len(lines) * line_height <= 90
    assert all(draw.textlength(line, font=load(size)) <= 200 for line in lines)
    small, _, _ = fit("Un texte bien trop long pour une toute petite bulle de rien du tout", 60, 30, load, draw)
    assert small < size


def fake_chat(log: list):
    """Faux Hub : OCR = texte de vérité selon la position, traduction = JSON numéroté."""
    by_size = {}

    def chat(messages, extra):
        log.append(extra)
        content = messages[0]["content"]
        if isinstance(content, list):  # OCR : on reconnaît la bulle à la taille de l'image envoyée
            return "「" + by_size.setdefault(len(log), TRUTH[(len(log) - 1) % 5]["text"]) + "」"
        count = sum(1 for line in content.splitlines() if line[:1].isdigit() and ". " in line)
        return "<think>…</think>" + json.dumps({str(i): f"Réplique {i}" for i in range(1, count + 1)})
    return chat


def test_full_pipeline_with_fake_models(page, tmp_path: Path) -> None:
    log: list = []
    chat = fake_chat(log)
    glossary = Glossary(tmp_path / "g.json", characters={"ユキ": "Yuki"}, terms={"海": "la mer"})
    pipeline = Scantrad(detect_bubbles, make_vision_ocr(chat), clean_bubbles, make_translator(chat, glossary),
                        make_typesetter(), vram_used_mib=lambda: 1234)
    result = pipeline.run(page)
    assert [b.source for b in result.bubbles] == [t["text"] for t in TRUTH]  # guillemets japonais retirés
    assert [b.translation for b in result.bubbles] == [f"Réplique {i}" for i in range(1, 6)]
    assert log[0] == {"model": "qwen2.5vl:7b", "num_ctx": 4096, "temperature": 0}  # vision : contexte court
    assert log[-1]["think"] is False
    assert result.metrics["steps"] == ["detection", "ocr", "effacement", "traduction", "incrustation"]
    assert result.metrics["vram_peak_mib"] == 1234 and result.metrics["bubbles"] == 5
    assert not np.array_equal(result.image, page)
    write_image(tmp_path / "accentué é" / "sortie.png", result.image)  # chemins accentués sous Windows
    assert read_image(tmp_path / "accentué é" / "sortie.png").shape == page.shape


def test_translation_prompt_uses_only_relevant_glossary(tmp_path: Path) -> None:
    glossary = Glossary(tmp_path / "g.json", characters={"ユキ": "Yuki", "ケン": "Ken"}, terms={"海": "la mer"})
    prompt = translation_prompt(["ユキ、海に行こう！"], glossary)
    assert "ユキ = Yuki" in prompt and "海 = la mer" in prompt and "Ken" not in prompt
    glossary.save()
    assert Glossary.load(tmp_path / "g.json").characters == {"ユキ": "Yuki", "ケン": "Ken"}


@pytest.mark.parametrize("answer, expected", [
    ('{"1": "Salut", "2": "Ça va ?"}', ["Salut", "Ça va ?"]),
    ('Voici : ```json\n{"1": "Salut", "2": "Ça va ?"}\n```', ["Salut", "Ça va ?"]),
    ('{"1": "Salut"}', None),  # une bulle manquante : repli
    ("pas de json", None),
])
def test_parse_translations(answer, expected) -> None:
    assert parse_translations(answer, 2) == expected


@pytest.mark.parametrize("raw, expected", [
    ("「はい、サンジ!!!」", "はい、サンジ!!!"),
    ("AUCUN", ""),
    ("Aucun texte.", ""),
    ("No text here", ""),  # aucun caractère japonais : hallucination écartée
    ("<think>…</think>サンジ？\nちゃんと", "サンジ？ ちゃんと"),
])
def test_accept_ocr(raw, expected) -> None:
    assert accept_ocr(raw) == expected


def test_ocr_second_read_and_rejection_in_pipeline(page) -> None:
    answers = iter(["AUCUN", "はい…"] + ["AUCUN"] * 20)  # bulle 1 : relue avec plus de contexte ; les autres : rien
    sent = []

    def chat(messages, extra):
        sent.append(messages)
        return next(answers)
    pipeline = Scantrad(detect_bubbles, make_vision_ocr(chat), clean_bubbles, None, make_typesetter())
    result = pipeline.run(page)
    assert [b.source for b in result.bubbles] == ["はい…"] and result.bubbles[0].index == 1
    assert result.metrics["rejected_by_ocr"] == 4 and len(sent) == 2 + 4 * 2


def test_small_pages_are_upscaled() -> None:
    assert upscale_small_page(np.zeros((451, 443, 3), np.uint8)).shape == (1100, 1080, 3)
    big = np.zeros((1600, 1000, 3), np.uint8)
    assert upscale_small_page(big) is big


def test_punctuation_never_starts_a_line() -> None:
    from PIL import Image, ImageDraw

    from modules.scantrad.typeset import wrap

    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = font_loader()(20)
    width = int(draw.textlength("m'épouser ?", font=font)) + 2
    lines = wrap("Tu vas m'épouser ?", font, width, draw)
    assert lines and lines[-1] == "m'épouser ?"  # le « ? » reste collé à son mot
    assert wrap("Tu vas m'épouser ?", font, width - 10, draw) is None  # trop étroit : `fit` réduira la police


def test_translator_falls_back_bubble_by_bubble() -> None:
    calls = []

    def chat(messages, extra):
        calls.append(messages[0]["content"])
        return "Bonjour" if len(calls) > 1 else "réponse illisible"
    assert make_translator(chat)(["こんにちは", "さようなら"]) == ["Bonjour", "Bonjour"]
    assert len(calls) == 3


def test_cli_no_llm_and_glossary(tmp_path: Path, monkeypatch, capsys) -> None:
    from core import config

    monkeypatch.setattr(config, "section", lambda name, path=None: {"data_dir": str(tmp_path)})
    out = tmp_path / "sortie.png"
    assert main([str(DATA / "page_test.png"), "--no-llm", "--out", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"]["bubbles"] == 5 and out.is_file()
    assert main(["--glossary", "Ma Série !", "--add", "ユキ=Yuki"]) == 0
    assert json.loads((tmp_path / "glossaires" / "ma-serie.json").read_text(encoding="utf-8"))["terms"] == {
        "ユキ": "Yuki"}
    assert series_slug("../../Windows") == "windows"  # aucun chemin ne sort du dossier des glossaires
    with pytest.raises(ValueError):
        series_slug("ユキ")  # que des caractères non latins : refus clair plutôt qu'un fichier vide


def test_reading_order_of_a_double_page() -> None:
    """Page de droite d'abord, rangées de haut en bas, de droite à gauche (double page de Jérémy, simplifiée)."""
    import numpy as np

    from modules.scantrad.detect import sort_reading
    from modules.scantrad.pipeline import Bubble

    def bubble(x: int, y: int, w: int, h: int) -> Bubble:
        return Bubble(0, (x, y, w, h), np.zeros((1, 1), np.uint8), np.zeros((1, 1), np.uint8))

    boxes = {"5": (572, 208, 148, 441), "8": (78, 874, 156, 210), "1": (1410, 99, 143, 364),
             "3": (1388, 893, 174, 136), "6": (15, 307, 133, 491), "2": (874, 374, 74, 401),
             "7": (616, 876, 141, 208), "4": (864, 874, 188, 180)}
    ordered = sort_reading([bubble(*b) for b in boxes.values()], 1150, 1600)
    names = {v: k for k, v in boxes.items()}
    assert [names[b.box] for b in ordered] == list("12345678")
