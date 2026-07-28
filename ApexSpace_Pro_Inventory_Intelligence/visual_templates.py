from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

ASSET_DIR = Path(__file__).resolve().parent / "assets" / "templates"

ZONE_WEIGHT = {"Feature": 0.95, "Prime": 1.20, "Secondary": 1.00, "Tertiary": 0.75}


def _slot(slot_id: str, bay: int, row: int, slot: int, box: tuple[int, int, int, int], *, zone: str | None = None) -> dict[str, Any]:
    zone = zone or {1: "Feature", 2: "Prime", 3: "Secondary", 4: "Tertiary"}.get(row, "Secondary")
    return {
        "slot_id": slot_id,
        "bay": bay,
        "row": row,
        "slot": slot,
        "zone": zone,
        "visibility_weight": ZONE_WEIGHT[zone],
        "position_type": "Product",
        "posm_label": "",
        "box": list(box),
    }


def _wall_slots(layout: dict[int, dict[int, list[int]]], y_by_row: dict[int, int], *, box_w: int = 76, box_h: int = 52) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    for bay, rows in layout.items():
        for row, x_values in rows.items():
            for index, x in enumerate(x_values, start=1):
                y = y_by_row[row]
                slots.append(_slot(f"B{bay}-R{row}-S{index}", bay, row, index, (x - box_w // 2, y - box_h // 2, box_w, box_h)))
    return slots


APEX_SLOTS = _wall_slots(
    {
        1: {1: [38, 215], 2: [38, 130, 220], 3: [45, 135, 225], 4: [55, 135, 225]},
        2: {1: [305, 400], 2: [310, 405, 500], 3: [310, 405, 500], 4: [315, 410, 500]},
        3: {1: [585, 680, 770], 2: [675, 770], 3: [590, 680, 770], 4: [590, 680, 770]},
    },
    {1: 220, 2: 290, 3: 360, 4: 430},
    box_w=74,
    box_h=50,
)

VENTURINI_SLOTS = _wall_slots(
    {
        1: {1: [70], 2: [70, 175], 3: [70, 175], 4: [70, 175]},
        2: {1: [345, 465], 2: [345, 465], 3: [345, 465], 4: [345, 465]},
        3: {1: [610, 735], 2: [610], 3: [610, 735], 4: [610, 735]},
    },
    {1: 220, 2: 290, 3: 360, 4: 430},
    box_w=86,
    box_h=52,
)

NINO_SLOTS = _wall_slots(
    {
        1: {1: [35, 220], 2: [35, 125, 220], 3: [35, 125, 220], 4: [35, 125, 220]},
        2: {1: [315, 405], 2: [315, 495], 3: [405, 495], 4: [315, 405, 495]},
        3: {1: [585, 680, 780], 2: [585, 680, 780], 3: [585, 680, 780], 4: [585, 680, 780]},
    },
    {1: 220, 2: 285, 3: 355, 4: 425},
    box_w=72,
    box_h=52,
)

MOOCHIE_SLOTS = _wall_slots(
    {
        1: {1: [60, 215], 2: [60, 215], 3: [60, 215], 4: [60, 215]},
        2: {1: [315, 455], 2: [365, 480], 3: [330, 480], 4: [330, 480]},
        3: {1: [610, 735], 2: [610, 735], 3: [610, 735], 4: [610, 735]},
    },
    {1: 220, 2: 285, 3: 355, 4: 425},
    box_w=82,
    box_h=54,
)

TWINKLER_SLOTS = _wall_slots(
    {
        1: {1: [50, 215], 2: [45, 105, 165, 225], 3: [45, 105, 165, 225], 4: [45, 105, 165, 225]},
        2: {1: [315, 385, 455], 2: [315, 385, 455, 515], 3: [315, 385, 455, 515], 4: [315, 385, 455, 515]},
        3: {1: [575, 635, 770], 2: [575, 635, 700, 770], 3: [575, 635, 700, 770], 4: [575, 635, 700, 770]},
    },
    {1: 215, 2: 285, 3: 355, 4: 425},
    box_w=58,
    box_h=42,
)


def _fixture_slots(points: list[tuple[int, int]], *, box: tuple[int, int], zones: list[str] | None = None) -> list[dict[str, Any]]:
    slots = []
    for i, (x, y) in enumerate(points, start=1):
        zone = zones[i - 1] if zones else ("Prime" if i <= max(2, len(points) // 4) else "Secondary")
        slots.append(_slot(f"F-S{i:02d}", 1, 1 + (i - 1) // 6, i, (x - box[0] // 2, y - box[1] // 2, box[0], box[1]), zone=zone))
    return slots


FIXTURE_1_POINTS = [
    (835, 170), (925, 170), (1015, 170), (1105, 170), (1190, 170),
    (835, 260), (835, 350), (835, 440),
    (1190, 260), (1190, 350), (1190, 440),
    (835, 530), (925, 530), (1015, 530), (1105, 530), (1190, 530),
    (925, 260), (1015, 260), (1105, 260),
    (925, 350), (1105, 350),
    (925, 440), (1015, 440), (1105, 440),
]

FIXTURE_2_POINTS = [(260, 340), (405, 340), (550, 340), (260, 470), (550, 470), (260, 590), (405, 590), (550, 590)]

FIXTURE_3_POINTS = [
    (855, 125), (1005, 125),
    (835, 250), (935, 250), (1040, 250),
    (835, 360), (1040, 360),
    (835, 470), (935, 470), (1040, 470),
    (855, 585), (1005, 585),
    (180, 315), (320, 355), (500, 355), (650, 315),
]


BASE_TEMPLATES: dict[str, dict[str, Any]] = {
    "apex_wall": {
        "key": "apex_wall", "name": "Apex Brand Wall", "kind": "wall", "brand": "APEX",
        "asset": "apex_wall.png", "slots": APEX_SLOTS, "family": "Brand walls",
        "source_rule": "Apex branded three-bay wall. Fixed campaign, POSM and visual areas remain untouched.",
    },
    "venturini_wall": {
        "key": "venturini_wall", "name": "Venturini Brand Wall", "kind": "wall", "brand": "VENTURINI",
        "asset": "venturini_wall.png", "slots": VENTURINI_SLOTS, "family": "Brand walls",
        "source_rule": "Venturini premium leather wall with approved purple, beige and brand-story elements.",
    },
    "nino_rossi_wall": {
        "key": "nino_rossi_wall", "name": "Nino Rossi Brand Wall", "kind": "wall", "brand": "NINO ROSSI",
        "asset": "nino_rossi_wall.png", "slots": NINO_SLOTS, "family": "Brand walls",
        "source_rule": "Nino Rossi women's wall with approved pastel and striped visual language.",
    },
    "moochie_wall": {
        "key": "moochie_wall", "name": "Moochie Brand Wall", "kind": "wall", "brand": "MOOCHIE",
        "asset": "moochie_wall.png", "slots": MOOCHIE_SLOTS, "family": "Brand walls",
        "source_rule": "Moochie women's fashion wall with approved maroon and brown visual language.",
    },
    "twinkler_wall": {
        "key": "twinkler_wall", "name": "Twinkler Brand Wall", "kind": "wall", "brand": "TWINKLER",
        "asset": "twinkler_wall.png", "slots": TWINKLER_SLOTS, "family": "Brand walls",
        "source_rule": "Twinkler kids wall with approved rainbow, campaign and character elements.",
    },
    "fixture_1": {
        "key": "fixture_1", "name": "Fixture 1. Large Table", "kind": "fixture", "brand": "ALL",
        "asset": "fixture_1.png", "slots": _fixture_slots(FIXTURE_1_POINTS, box=(78, 66)), "family": "Fixtures",
        "feature_positions": [(175, 395, 100, 62), (300, 370, 100, 62), (550, 370, 100, 62), (675, 395, 100, 62)],
        "source_rule": "Maximum 24 options. Group similar styles. Use raisers for best sellers and fresh stock plus signage cube.",
    },
    "fixture_2": {
        "key": "fixture_2", "name": "Fixture 2. Gondola", "kind": "fixture", "brand": "ALL",
        "asset": "fixture_2.png", "slots": _fixture_slots(FIXTURE_2_POINTS, box=(98, 112)), "family": "Fixtures",
        "source_rule": "Eight-position visual layout around a central signage cube, interpreted from the docket diagram.",
    },
    "fixture_3": {
        "key": "fixture_3", "name": "Fixture 3. Compact Table", "kind": "fixture", "brand": "ALL",
        "asset": "fixture_3.png", "slots": _fixture_slots(FIXTURE_3_POINTS, box=(82, 78)), "family": "Fixtures",
        "source_rule": "Maximum 16 options. Use raisers for best sellers and fresh stock plus signage cube.",
    },
}


BRAND_TEMPLATE = {
    "APEX": "apex_wall",
    "VENTURINI": "venturini_wall",
    "NINO ROSSI": "nino_rossi_wall",
    "MOOCHIE": "moochie_wall",
    "TWINKLER": "twinkler_wall",
}


def get_templates_for_brand(brand: str) -> dict[str, dict[str, Any]]:
    brand_upper = str(brand).strip().upper()
    result: dict[str, dict[str, Any]] = {}
    wall_key = BRAND_TEMPLATE.get(brand_upper)
    if wall_key:
        wall = deepcopy(BASE_TEMPLATES[wall_key])
        result[wall["name"]] = _finalize(wall)
    else:
        fallback = deepcopy(BASE_TEMPLATES["apex_wall"])
        fallback["name"] = "Apex Reference Wall. Fallback Template"
        fallback["brand"] = brand_upper
        fallback["source_rule"] = "No dedicated uploaded wall template exists for this brand. The Apex wall is used only as a configurable fallback."
        result[fallback["name"]] = _finalize(fallback)

    for key in ("fixture_1", "fixture_2", "fixture_3"):
        item = deepcopy(BASE_TEMPLATES[key])
        item["brand"] = brand_upper
        result[item["name"]] = _finalize(item)
    return result


def _finalize(template: dict[str, Any]) -> dict[str, Any]:
    template["asset_path"] = str(ASSET_DIR / template["asset"])
    template["capacity"] = len(template["slots"])
    template["total_cells"] = len(template["slots"])
    template["bays"] = max((int(s["bay"]) for s in template["slots"]), default=1)
    template["rows"] = max((int(s["row"]) for s in template["slots"]), default=1)
    template["columns"] = max((int(s["slot"]) for s in template["slots"]), default=1)
    template["slots_per_bay"] = template["columns"]
    return template


TEMPLATE_ORDER = (
    "apex_wall",
    "venturini_wall",
    "nino_rossi_wall",
    "moochie_wall",
    "twinkler_wall",
    "fixture_1",
    "fixture_2",
    "fixture_3",
)


def get_all_templates(fixture_brand: str = "APEX", family: str = "All included") -> dict[str, dict[str, Any]]:
    """Return every uploaded visual planogram template in a stable display order.

    Brand-wall templates keep their approved brand identity. Floor fixtures use
    the currently selected product brand because the fixture drawings are generic.
    """
    requested_family = str(family or "All included").strip().lower()
    result: dict[str, dict[str, Any]] = {}
    for key in TEMPLATE_ORDER:
        item = deepcopy(BASE_TEMPLATES[key])
        if item["kind"] == "fixture":
            item["brand"] = str(fixture_brand).strip().upper() or "APEX"
        if requested_family == "brand walls" and item["kind"] != "wall":
            continue
        if requested_family == "fixtures" and item["kind"] != "fixture":
            continue
        result[item["name"]] = _finalize(item)
    return result
