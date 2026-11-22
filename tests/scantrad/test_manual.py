"""Mode manuel de Scantrad : zones posées à la main, effacement dans les zones, réincrustation."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from modules.scantrad import manual
from modules.scantrad.cli import read_image, write_image
from modules.scantrad.module import compose, work_paths

PAGE = Path(__file__).resolve().parents[1] / "data" / "scantrad" / "page_test.png"


def bubble_page() -> np.ndarray:
    """Une bulle blanche à contour noir sur fond gris, avec trois « caractères » noirs dedans."""
    page = np.full((300, 300, 3), 170, np.uint8)
    cv2.ellipse(page, (150, 150), (110, 80), 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(page, (150, 150), (110, 80), 0, 0, 360, (0, 0, 0), 3)
    for x in (110, 140, 170):
        cv2.rectangle(page, (x, 135), (x + 14, 165), (0, 0, 0), -1)
    return page


def test_parse_boxes_clips_and_refuses_garbage() -> None:
    assert manual.parse_boxes([[-5, -5, 50, 50], [280, 10, 100, 40.4]], (300, 300, 3)) == [
        (0, 0, 45, 45), (280, 10, 20, 40)]
    for bad in ([], "x", [[1, 2, 3]], [[0, 0, 3, 3]], [[True, 0, 50, 50]], [[400, 400, 20, 20]],
                [[0, 0, 20, 20]] * (manual.MAX_BOXES + 1)):
        with pytest.raises(ValueError):
            manual.parse_boxes(bad, (300, 300, 3))


def test_bubbles_follow_the_drawing_order() -> None:
    bubbles = manual.bubbles_from_boxes([(200, 0, 50, 50), (0, 0, 50, 50)])
    assert [(b.index, b.box, b.area) for b in bubbles] == [(1, (200, 0, 50, 50), (200, 0, 50, 50)),
                                                           (2, (0, 0, 50, 50), (0, 0, 50, 50))]


def test_erase_removes_the_text_but_keeps_the_bubble_outline() -> None:
    page = bubble_page()
    out = manual.erase_in_boxes(page, [(45, 75, 210, 150)])  # boîte large : le contour y est en entier
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    assert gray[135:166, 110:185].min() > 200  # les caractères ont disparu
    assert gray[150, 40] < 60 and gray[70, 150] < 60  # le contour de la bulle est intact
    assert np.array_equal(out[:, :30], page[:, :30])  # hors des boîtes, rien ne bouge


def test_suggestion_reuses_the_automatic_detection() -> None:
    boxes = manual.suggest_boxes(read_image(PAGE))
    assert len(boxes) == 5 and all(w > 0 and h > 0 for _x, _y, w, h in boxes)


def test_compose_writes_the_text_in_the_hand_drawn_boxes(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    write_image(source, bubble_page())
    output = tmp_path / "page_fr.png"
    rows = [{"box": [45, 75, 210, 150], "source": "こんにちは", "translation": "  Bonjour   toi ! "}]
    bubbles = compose(source, output, rows)
    assert bubbles[0]["translation"] == "Bonjour toi !" and bubbles[0]["area"] == [45, 75, 210, 150]
    clean_path, job_path = work_paths(output)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert clean_path.is_file() and job["bubbles"][0]["source"] == "こんにちは"
    written = cv2.cvtColor(read_image(output), cv2.COLOR_BGR2GRAY)
    assert (written[80:220, 50:250] < 100).sum() > 50  # du texte français est posé dans la bulle


def test_compose_starts_from_the_page_erased_by_hand(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    write_image(source, bubble_page())
    output = tmp_path / "page_fr.png"
    brushed = bubble_page()
    brushed[10:40, 10:40] = 255  # coup de gomme hors des boîtes : doit se retrouver dans la page finale
    write_image(work_paths(output)[0], brushed)
    compose(source, output, [{"box": [45, 75, 210, 150], "translation": ""}], auto_erase=False)
    assert read_image(output)[20, 20].tolist() == [255, 255, 255]
    assert cv2.cvtColor(read_image(output), cv2.COLOR_BGR2GRAY)[135:166, 110:185].min() < 60  # texte laissé
    compose(source, output, [{"box": [45, 75, 210, 150], "translation": ""}])  # gomme + effacement auto
    final = cv2.cvtColor(read_image(output), cv2.COLOR_BGR2GRAY)
    assert final[20, 20] == 255 and final[135:166, 110:185].min() > 200
    write_image(work_paths(output)[0], brushed[:100])
    with pytest.raises(ValueError, match="taille"):
        compose(source, output, [{"box": [45, 75, 210, 150], "translation": ""}])
    with pytest.raises(ValueError, match="400"):
        write_image(work_paths(output)[0], brushed)
        compose(source, output, [{"box": [45, 75, 210, 150], "translation": "x" * 401}])


def column_page() -> np.ndarray:
    """Bulle blanche avec trois colonnes de « caractères » (blocs de 14 px séparés de 3 px, colonnes à 8 px)."""
    page = np.full((260, 220, 3), 255, np.uint8)
    for col in range(3):
        x = 150 - col * 22
        for row in range(5):
            cv2.rectangle(page, (x, 40 + row * 17), (x + 13, 40 + row * 17 + 13), (0, 0, 0), -1)
    return page


def test_columns_are_found_right_to_left() -> None:
    page = column_page()
    assert manual.is_vertical(page[20:160, 90:190])
    columns = manual.split_columns(page[20:160, 90:190])
    assert len(columns) == 3
    assert [c[0] for c in columns] == sorted((c[0] for c in columns), reverse=True)  # droite → gauche


def test_horizontal_lines_are_recognised() -> None:
    page = np.full((200, 300, 3), 255, np.uint8)
    for line in range(3):
        for k in range(8):
            cv2.rectangle(page, (30 + k * 17, 40 + line * 26), (43 + k * 17, 53 + line * 26), (0, 0, 0), -1)
    assert not manual.is_vertical(page[20:150, 20:190])


def test_a_narrow_column_gets_room_for_french() -> None:
    page = np.full((300, 300, 3), 255, np.uint8)
    cv2.rectangle(page, (0, 0), (60, 299), (40, 40, 40), -1)  # dessin à gauche : la zone s'arrête avant
    x, y, w, h = manual.widen_area(page, (120, 50, 40, 200))
    assert w > 100 and x >= 61 and (y, h) == (50, 200)
    assert manual.widen_area(page, (100, 50, 150, 120)) == (100, 50, 150, 120)  # déjà large : inchangée


def test_evaluate_compares_auto_detection_with_hand_drawn_zones(tmp_path: Path) -> None:
    import shutil

    (tmp_path / "entrees").mkdir()
    shutil.copy(PAGE, tmp_path / "entrees" / "p.png")
    boxes = manual.suggest_boxes(read_image(PAGE))
    rows = [{"box": b, "translation": "x"} for b in boxes] + [{"box": [0, 0, 30, 30], "translation": ""}]
    compose(tmp_path / "entrees" / "p.png", tmp_path / "sorties" / "p_fr.png", rows, series="demo")
    report = manual.evaluate(tmp_path)
    assert report["pages"] == 1 and report["zones"] == 6
    assert report["recall"] == round(5 / 6, 3)  # la zone du coin n'est pas détectée
    assert report["order_agreement"] == 1.0 and report["per_page"][0]["series"] == "demo"

def test_auto_ocr_rereads_vertical_blocks_column_by_column() -> None:
    from modules.scantrad.hub_stages import MANUAL_OCR_COLUMN, make_column_aware_ocr

    calls = []

    def chat(messages, extra):  # faux modèle : lecture globale dans le désordre, colonnes lues une à une
        prompt = messages[0]["content"][0]["text"]
        calls.append(prompt)
        if prompt == MANUAL_OCR_COLUMN:
            return "一二三"[sum(1 for c in calls if c == MANUAL_OCR_COLUMN) - 1]
        return "三一二"

    page = column_page()
    bubble = manual.bubbles_from_boxes([(100, 35, 70, 90)])[0]
    bubble.vertical = True
    assert make_column_aware_ocr(chat)(page, bubble) == "一二三"
    calls.clear()
    empty = make_column_aware_ocr(lambda m, e: "AUCUN")(page, bubble)
    assert empty == ""  # faux positif de la détection : écarté sans relecture


def test_languages_accept_their_own_script_only() -> None:
    from modules.scantrad.hub_stages import accept_ocr
    from modules.scantrad.languages import language, ocr_prompt

    assert accept_ocr("안녕하세요", "ko") == "안녕하세요" and accept_ocr("こんにちは", "ko") == ""
    assert accept_ocr("你好", "zh") == "你好" and accept_ocr("HELLO THERE!", "en") == "HELLO THERE!"
    assert accept_ocr("AUCUN", "en") == "" and accept_ocr("…", "en") == ""
    assert "coréen" in ocr_prompt(language("ko")) and "manhwa" in ocr_prompt(language("ko"))
    assert "colonnes" not in ocr_prompt(language("en"))  # l'anglais n'est jamais vertical
    with pytest.raises(ValueError):
        language("de")


def test_left_to_right_reading_and_forced_layout() -> None:
    from modules.scantrad.detect import sort_reading
    from modules.scantrad.pipeline import Bubble

    def bubble(x: int, y: int) -> Bubble:
        return Bubble(0, (x, y, 50, 50), np.zeros((1, 1), np.uint8), np.zeros((1, 1), np.uint8))

    row = [bubble(500, 10), bubble(10, 10)]
    assert [b.box[0] for b in sort_reading(row, 400, 600, right_to_left=True)] == [500, 10]
    assert [b.box[0] for b in sort_reading(row, 400, 600, right_to_left=False)] == [10, 500]
    # une page large déclarée « simple » n'est pas coupée en deux pages : rangées de haut en bas seulement
    spread = [bubble(900, 300), bubble(100, 10)]
    assert [b.box[1] for b in sort_reading(spread, 400, 1000, spread=False)] == [10, 300]
    assert [b.box[1] for b in sort_reading(spread, 400, 1000)] == [300, 10]  # devinée double : droite d'abord


def test_an_annex_zone_keeps_the_art_and_gets_outlined_text(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    page = bubble_page()
    page[230:280, 20:120] = 90  # « dessin » gris sous l'onomatopée
    write_image(source, page)
    rows = [{"box": [45, 75, 210, 150], "translation": "Salut"},
            {"box": [10, 225, 120, 60], "translation": "BAM", "kind": "annexe"}]
    bubbles = compose(source, tmp_path / "page_fr.png", rows)
    assert bubbles[1]["kind"] == "annexe" and bubbles[1]["outline"] is True
    out = read_image(tmp_path / "page_fr.png")
    zone = out[225:285, 10:130]
    assert (zone == 255).all(axis=2).sum() > 20  # texte blanc posé par-dessus
    assert (np.abs(out[275, 115].astype(int) - 90) < 5).all()  # le dessin autour n'est pas effacé


def test_lama_rebuilds_hatching_under_a_drawn_sound_effect() -> None:
    from modules.scantrad import lama

    if not lama.available():
        pytest.skip("poids LaMa absents (scripts\\setup.ps1 -Weights)")
    page = np.full((300, 300, 3), 255, np.uint8)
    for x in range(0, 300, 6):  # hachures fines
        cv2.line(page, (x, 0), (x, 299), (0, 0, 0), 1)
    cv2.rectangle(page, (120, 100), (180, 200), (0, 0, 0), -1)  # « onomatopée » épaisse posée dessus
    mask = manual.stroke_mask(page)
    assert mask[150, 150] == 255 and mask[20, 30] == 0  # le trait épais est masqué, pas les hachures
    out = lama.inpaint(page, mask)
    inside = cv2.cvtColor(out[110:190, 130:170], cv2.COLOR_BGR2GRAY)
    assert inside.mean() > 120  # le bloc noir a disparu : LaMa a redessiné un fond clair et rayé
    assert np.array_equal(out[:, :90], page[:, :90])  # hors du masque, rien ne bouge


def test_annex_set_to_erase_loses_its_thick_strokes(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    page = bubble_page()
    cv2.rectangle(page, (30, 240), (90, 260), (0, 0, 0), -1)  # onomatopée épaisse hors bulle
    write_image(source, page)
    rows = [{"box": [20, 230, 90, 40], "translation": "", "kind": "annexe", "style": "efface"}]
    compose(source, tmp_path / "page_fr.png", rows)
    out = cv2.cvtColor(read_image(tmp_path / "page_fr.png"), cv2.COLOR_BGR2GRAY)
    assert out[245:255, 40:80].mean() > 100  # le trait noir a été effacé et le fond reconstruit
