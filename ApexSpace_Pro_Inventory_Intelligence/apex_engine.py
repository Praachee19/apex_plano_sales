from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Iterable

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from visual_templates import get_all_templates, get_templates_for_brand

SALES_PERIOD_MONTHS = 6.5
SALES_PERIOD_WEEKS = SALES_PERIOD_MONTHS * 52 / 12
WALL_WIDTH_FT = 15
WALL_HEIGHT_FT = 8
MERCH_HEIGHT_FT = 6

CLIENT_SALES_COLUMNS = {
    "Sku / Product Code": "article_code",
    "Brand / Product Line": "brand",
    "Merchant Category": "merchant_category_sales",
    "Category": "category_sales",
    "Main Group ": "main_group_sales",
    "Main Group": "main_group_sales",
    "Sub Group": "sub_group_sales",
    "Gender": "gender_raw",
    "Color Code": "color_code",
    "Color": "color_raw",
    "Size": "size",
    "Sales Qty (6.5 Months)": "sales_qty",
    "Sales Value (6.5 Months)": "sales_value",
    "Stock Qty (16- July Stock)": "stock_qty",
}

MASTER_COLUMNS = {
    "ArtNo": "article_code",
    "MainGroupName": "main_group_master",
    "SubGroupName": "sub_group_master",
    "CategoryName": "category_master",
    "SubCategoryName": "subcategory_master",
    "BrandName": "brand_master",
    "MerchCategory": "merchant_category_master",
    "GroupDesc": "group_desc",
}

BRAND_CONFIG = {
    "APEX": {"accent": "#E31E24", "story": "Apex brand and seasonal story"},
    "VENTURINI": {"accent": "#5B3A29", "story": "Premium leather and formal story"},
    "MAVERICK": {"accent": "#333333", "story": "Free-to-be casual story"},
    "SPRINT": {"accent": "#D71920", "story": "Running and sports story"},
    "MOOCHIE": {"accent": "#8B1E3F", "story": "Women's fashion and accessories story"},
    "NINO ROSSI": {"accent": "#81A39A", "story": "Women's contemporary story"},
    "TWINKLER": {"accent": "#6B4FA1", "story": "Children and colour story"},
    "DR. MAUCH": {"accent": "#597A87", "story": "Comfort footwear story"},
    "SCHOOL SMART": {"accent": "#355C7D", "story": "School footwear story"},
    "GENERIC": {"accent": "#E65A00", "story": "Footwear category story"},
}

DISPLAY_CATEGORY_COLORS = {
    "Formal Shoes": "#383838",
    "Casual Shoes": "#8D6E63",
    "Sports / Sneakers": "#607D8B",
    "Sandals": "#D97A24",
    "Slippers": "#7B6EB0",
    "Pumps / Heels": "#B04A68",
    "School Shoes": "#2A7A63",
    "Accessories": "#B88734",
    "Apparel": "#767676",
    "Other Footwear": "#4E79A7",
}

ZONE_WEIGHTS = {
    "Feature": 0.95,
    "Prime": 1.20,
    "Secondary": 1.00,
    "Tertiary": 0.75,
}


@dataclass(frozen=True)
class SourceSummary:
    source_name: str
    sales_sheet: str
    master_sheet: str | None
    size_rows: int
    unique_articles: int
    brands: int
    period_description: str


def _clean_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _find_header_row(xls: pd.ExcelFile, sheet_name: str, target: str, max_rows: int = 10) -> int:
    preview = pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=max_rows)
    for idx, row in preview.iterrows():
        if row.astype(str).str.strip().eq(target).any():
            return int(idx)
    return 0


def _choose_sheet(sheet_names: Iterable[str], preferred: str, contains: str) -> str:
    names = list(sheet_names)
    for name in names:
        if name.strip().upper() == preferred.upper():
            return name
    for name in names:
        if contains.upper() in name.upper():
            return name
    raise ValueError(f"Required sheet not found. Expected a sheet containing '{contains}'.")


def _map_display_category(row: pd.Series) -> str:
    text = " ".join(
        str(row.get(k, ""))
        for k in ["category", "subcategory", "merchant_category", "group_desc", "sub_group"]
    ).upper()
    if "SCHOOL" in text:
        return "School Shoes"
    if any(x in text for x in ["DRESS SHOE", "FORMAL"]):
        return "Formal Shoes"
    if any(x in text for x in ["CASUAL SHOE", "LIFESTYLE"]):
        return "Casual Shoes"
    if any(x in text for x in ["SPORTS RUNNING", "SPORTS FIELD", "SPORTS OUTDOOR", "CANVAS", "SNEAKER"]):
        return "Sports / Sneakers"
    if "SPORTS SANDAL" in text or "SANDAL" in text or "CHAPLIES" in text:
        return "Sandals"
    if any(x in text for x in ["PLASTIC-EVA", "PLASTIC-PVC", "THONG", "SLIPPER", "FLIP FLOP"]):
        return "Slippers"
    if any(x in text for x in ["PUMPIES", "HEEL", "PUMP"]):
        return "Pumps / Heels"
    if any(x in text for x in ["LEATHER GOODS", "ACCESSORIES", "BAG"]):
        return "Accessories"
    if any(x in text for x in ["MENSWEAR", "WOMENSWEAR", "APPAREL", "SOCK"]):
        return "Apparel"
    return "Other Footwear"


def _map_gender(row: pd.Series) -> str:
    main_group = str(row.get("main_group", "")).upper()
    gender = str(row.get("gender_raw", "")).upper()
    if any(x in main_group for x in ["CHILD", "JUNIOR", "SCHOOL"]):
        return "Kids"
    if gender == "FEMALE" or "LADIES" in main_group:
        return "Women"
    if gender == "MALE" or "MENS" in main_group:
        return "Men"
    return "Unisex"


def standardize_apex_sales(sales: pd.DataFrame, master: pd.DataFrame | None = None, color_table: pd.DataFrame | None = None) -> pd.DataFrame:
    sales = sales.rename(columns={c: CLIENT_SALES_COLUMNS.get(str(c).strip(), CLIENT_SALES_COLUMNS.get(c, str(c).strip())) for c in sales.columns})
    required = ["article_code", "brand", "category_sales", "main_group_sales", "gender_raw", "size", "sales_qty", "sales_value", "stock_qty"]
    missing = [c for c in required if c not in sales.columns]
    if missing:
        raise ValueError(f"The Apex sales sheet is missing required columns: {missing}")

    keep = list(dict.fromkeys(c for c in CLIENT_SALES_COLUMNS.values() if c in sales.columns))
    out = sales[keep].copy()
    for c in ["article_code", "brand", "merchant_category_sales", "category_sales", "main_group_sales", "sub_group_sales", "gender_raw", "color_raw", "size"]:
        if c not in out.columns:
            out[c] = ""
        out[c] = _clean_text(out[c])
    for c in ["color_code", "sales_qty", "sales_value", "stock_qty"]:
        if c not in out.columns:
            out[c] = 0
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out = out[out["article_code"].ne("")].copy()

    if master is not None and not master.empty:
        m = master.rename(columns={c: MASTER_COLUMNS.get(str(c).strip(), str(c).strip()) for c in master.columns})
        master_keep = [c for c in MASTER_COLUMNS.values() if c in m.columns]
        m = m[master_keep].copy()
        m["article_code"] = _clean_text(m["article_code"])
        m = m.drop_duplicates("article_code")
        out = out.merge(m, on="article_code", how="left")
    else:
        for c in ["main_group_master", "sub_group_master", "category_master", "subcategory_master", "brand_master", "merchant_category_master", "group_desc"]:
            out[c] = ""

    if color_table is not None and not color_table.empty:
        ct = color_table.copy()
        ct.columns = [str(c).strip().upper() for c in ct.columns]
        if {"CODE", "COLOR"}.issubset(ct.columns):
            ct["CODE"] = pd.to_numeric(ct["CODE"], errors="coerce")
            ct = ct.dropna(subset=["CODE"]).drop_duplicates("CODE")
            color_map = dict(zip(ct["CODE"].astype(int), ct["COLOR"].astype(str)))
            out["color_family"] = out["color_code"].round().astype(int).map(color_map)
        else:
            out["color_family"] = np.nan
    else:
        out["color_family"] = np.nan

    out["brand"] = np.where(_clean_text(out.get("brand_master", pd.Series(index=out.index, dtype=str))).ne(""), _clean_text(out["brand_master"]), _clean_text(out["brand"]))
    out["main_group"] = np.where(_clean_text(out.get("main_group_master", pd.Series(index=out.index, dtype=str))).ne(""), _clean_text(out["main_group_master"]), _clean_text(out["main_group_sales"]))
    out["sub_group"] = np.where(_clean_text(out.get("sub_group_master", pd.Series(index=out.index, dtype=str))).ne(""), _clean_text(out["sub_group_master"]), _clean_text(out["sub_group_sales"]))
    out["category"] = np.where(_clean_text(out.get("category_master", pd.Series(index=out.index, dtype=str))).ne(""), _clean_text(out["category_master"]), _clean_text(out["category_sales"]))
    out["subcategory"] = _clean_text(out.get("subcategory_master", pd.Series(index=out.index, dtype=str)))
    out["merchant_category"] = np.where(_clean_text(out.get("merchant_category_master", pd.Series(index=out.index, dtype=str))).ne(""), _clean_text(out["merchant_category_master"]), _clean_text(out["merchant_category_sales"]))
    out["group_desc"] = _clean_text(out.get("group_desc", pd.Series(index=out.index, dtype=str)))
    out["color"] = np.where(out["color_family"].fillna("").astype(str).str.strip().ne(""), out["color_family"], out["color_raw"])
    out["display_category"] = out.apply(_map_display_category, axis=1)
    out["display_gender"] = out.apply(_map_gender, axis=1)
    out["is_footwear"] = ~out["display_category"].isin(["Accessories", "Apparel"])
    return out.reset_index(drop=True)


def load_apex_workbook(source: str | Path | BinaryIO) -> tuple[pd.DataFrame, SourceSummary]:
    xls = pd.ExcelFile(source)
    sales_sheet = _choose_sheet(xls.sheet_names, "ARTICLE SAMPLE", "ARTICLE SAMPLE")
    header_row = _find_header_row(xls, sales_sheet, "Sku / Product Code")
    sales = pd.read_excel(xls, sheet_name=sales_sheet, header=header_row)

    master_sheet = None
    master = None
    for name in xls.sheet_names:
        if name.strip().upper() == "ARTICLE":
            master_sheet = name
            master = pd.read_excel(xls, sheet_name=name)
            break

    color_table = None
    for name in xls.sheet_names:
        if "COLOR" in name.upper():
            color_table = pd.read_excel(xls, sheet_name=name)
            break

    size_df = standardize_apex_sales(sales, master, color_table)
    source_name = getattr(source, "name", None) or Path(source).name if isinstance(source, (str, Path)) else "Uploaded Apex workbook"
    summary = SourceSummary(
        source_name=str(source_name),
        sales_sheet=sales_sheet,
        master_sheet=master_sheet,
        size_rows=len(size_df),
        unique_articles=int(size_df["article_code"].nunique()),
        brands=int(size_df["brand"].nunique()),
        period_description="Cumulative sales for 6.5 months and stock snapshot dated 16 July",
    )
    return size_df, summary


def load_csv(source: str | Path | BinaryIO) -> tuple[pd.DataFrame, SourceSummary]:
    raw = pd.read_csv(source)
    if "Sku / Product Code" in raw.columns:
        size_df = standardize_apex_sales(raw)
    elif {"sku", "product_line", "category", "gender", "size", "sales_units", "closing_stock_units"}.issubset(raw.columns):
        temp = pd.DataFrame({
            "Sku / Product Code": raw["sku"],
            "Brand / Product Line": raw["product_line"],
            "Merchant Category": raw.get("category", ""),
            "Category": raw["category"],
            "Main Group ": raw.get("gender", ""),
            "Sub Group": raw.get("style", ""),
            "Gender": raw["gender"].map({"Men": "MALE", "Women": "FEMALE", "Kids": "UNISEX"}).fillna(raw["gender"]),
            "Color Code": 0,
            "Color": raw.get("colour", ""),
            "Size": raw["size"],
            "Sales Qty (6.5 Months)": raw.groupby("sku")["sales_units"].transform("sum"),
            "Sales Value (6.5 Months)": raw.groupby("sku")["net_sales_value"].transform("sum"),
            "Stock Qty (16- July Stock)": raw.groupby("sku")["closing_stock_units"].transform("last"),
        }).drop_duplicates(["Sku / Product Code", "Size"])
        size_df = standardize_apex_sales(temp)
    else:
        raise ValueError("CSV format not recognised. Upload the Apex workbook or a CSV using the Apex client column names.")
    summary = SourceSummary(
        source_name=getattr(source, "name", "Uploaded CSV"),
        sales_sheet="CSV",
        master_sheet=None,
        size_rows=len(size_df),
        unique_articles=int(size_df["article_code"].nunique()),
        brands=int(size_df["brand"].nunique()),
        period_description="Uploaded cumulative sales and stock data",
    )
    return size_df, summary


def load_source(source: str | Path | BinaryIO, filename: str | None = None) -> tuple[pd.DataFrame, SourceSummary]:
    name = (filename or getattr(source, "name", None) or str(source)).lower()
    if name.endswith(".csv"):
        return load_csv(source)
    return load_apex_workbook(source)


def generate_synthetic_client_data(seed: int = 17, articles: int = 240) -> tuple[pd.DataFrame, SourceSummary]:
    rng = np.random.default_rng(seed)
    brands = ["APEX", "VENTURINI", "SPRINT", "MOOCHIE", "NINO ROSSI", "TWINKLER"]
    categories = ["DRESS SHOES", "CASUAL SHOES", "SPORTS RUNNING", "SANDAL", "PUMPIES", "SCHOOL"]
    colors = ["Black", "Light Brown/ Tanned", "Dark Brown", "Blue", "Red/ Maroon/ Pink/ Bordeaux", "White"]
    rows: list[dict[str, Any]] = []
    for i in range(articles):
        brand = rng.choice(brands)
        category = rng.choice(categories)
        gender = "FEMALE" if category == "PUMPIES" or brand in ["MOOCHIE", "NINO ROSSI"] else "MALE"
        main = "LADIES" if gender == "FEMALE" else "MENS"
        if brand == "TWINKLER" or category == "SCHOOL":
            main, gender = "CHILDREN", "UNISEX"
        code = f"{rng.integers(1000,9999)}{chr(65 + i % 20)}{rng.integers(10,99)}"
        sizes = rng.choice(np.arange(35, 45), size=rng.integers(2, 7), replace=False)
        article_sales = int(rng.gamma(2.3, 12))
        article_stock = int(rng.gamma(2.0, 8))
        for size in sorted(sizes):
            share = rng.dirichlet(np.ones(len(sizes)))[0]
            sales = max(0, int(article_sales / len(sizes) + rng.normal(0, 2)))
            stock = max(0, int(article_stock / len(sizes) + rng.normal(0, 1.5)))
            price = int(rng.choice([1490, 1990, 2490, 2990, 3490, 3990]))
            rows.append({
                "article_code": code,
                "brand": brand,
                "merchant_category_sales": category,
                "category_sales": category,
                "main_group_sales": main,
                "sub_group_sales": main,
                "gender_raw": gender,
                "color_code": 0,
                "color_raw": rng.choice(colors),
                "size": str(size),
                "sales_qty": sales,
                "sales_value": sales * price,
                "stock_qty": stock,
                "main_group_master": main,
                "sub_group_master": main,
                "category_master": category,
                "subcategory_master": category,
                "brand_master": brand,
                "merchant_category_master": category,
                "group_desc": category,
                "color_family": np.nan,
            })
    df = pd.DataFrame(rows)
    df["main_group"] = df["main_group_master"]
    df["sub_group"] = df["sub_group_master"]
    df["category"] = df["category_master"]
    df["subcategory"] = df["subcategory_master"]
    df["merchant_category"] = df["merchant_category_master"]
    df["color"] = df["color_raw"]
    df["display_category"] = df.apply(_map_display_category, axis=1)
    df["display_gender"] = df.apply(_map_gender, axis=1)
    df["is_footwear"] = ~df["display_category"].isin(["Accessories", "Apparel"])
    summary = SourceSummary("Synthetic Apex-format demo", "Generated", "Generated", len(df), df["article_code"].nunique(), df["brand"].nunique(), "Synthetic 6.5-month cumulative view")
    return df, summary


def build_article_master(size_df: pd.DataFrame) -> pd.DataFrame:
    working = size_df.copy()
    static_cols = [
        "brand", "merchant_category", "category", "subcategory", "main_group", "sub_group",
        "display_gender", "display_category", "color", "group_desc", "is_footwear",
    ]
    for c in static_cols:
        if c not in working.columns:
            working[c] = ""

    def first_nonblank(series: pd.Series):
        cleaned = series.dropna()
        if cleaned.empty:
            return ""
        if cleaned.dtype == bool:
            return bool(cleaned.iloc[0])
        text = cleaned.astype(str).str.strip()
        nonblank = cleaned[text.ne("")]
        return nonblank.iloc[0] if not nonblank.empty else cleaned.iloc[0]

    aggregations = {c: (c, first_nonblank) for c in static_cols}
    aggregations.update({
        "sales_qty": ("sales_qty", "sum"),
        "sales_value": ("sales_value", "sum"),
        "stock_qty": ("stock_qty", "sum"),
        "size_count": ("size", "nunique"),
    })
    agg = working.groupby("article_code", as_index=False).agg(**aggregations)
    in_stock = working[working["stock_qty"] > 0].groupby("article_code")["size"].nunique().rename("sizes_in_stock").reset_index()
    agg = agg.merge(in_stock, on="article_code", how="left")
    agg["sizes_in_stock"] = agg["sizes_in_stock"].fillna(0).astype(int)
    agg["size_set_completeness"] = np.where(agg["size_count"] > 0, agg["sizes_in_stock"] / agg["size_count"], 0)
    agg["weekly_sales_units"] = agg["sales_qty"] / SALES_PERIOD_WEEKS
    agg["avg_selling_price"] = np.where(agg["sales_qty"] > 0, agg["sales_value"] / agg["sales_qty"], 0)
    agg["weeks_cover"] = np.where(agg["weekly_sales_units"] > 0, agg["stock_qty"] / agg["weekly_sales_units"], 999.0)
    agg["sell_through_proxy"] = np.where(agg["sales_qty"] + agg["stock_qty"] > 0, agg["sales_qty"] / (agg["sales_qty"] + agg["stock_qty"]), 0)
    agg["stock_value_proxy"] = agg["stock_qty"] * agg["avg_selling_price"]
    agg["sales_to_stock_value"] = np.where(agg["stock_value_proxy"] > 0, agg["sales_value"] / agg["stock_value_proxy"], 0)
    agg["available_for_display"] = agg["stock_qty"] > 0
    return agg


def _pct_rank(series: pd.Series) -> pd.Series:
    if len(series) <= 1:
        return pd.Series(np.ones(len(series)), index=series.index)
    return series.rank(method="average", pct=True)


def score_articles(article_df: pd.DataFrame) -> pd.DataFrame:
    out = article_df.copy()
    group_keys = ["brand", "display_category"]
    out["velocity_index"] = out.groupby(group_keys, dropna=False)["weekly_sales_units"].transform(_pct_rank)
    out["sales_value_index"] = out.groupby(group_keys, dropna=False)["sales_value"].transform(_pct_rank)
    out["stock_index"] = out.groupby(group_keys, dropna=False)["stock_qty"].transform(_pct_rank)
    out["sell_through_index"] = out.groupby(group_keys, dropna=False)["sell_through_proxy"].transform(_pct_rank)
    out["commercial_score"] = 100 * (
        0.35 * out["velocity_index"]
        + 0.25 * out["sales_value_index"]
        + 0.20 * out["sell_through_index"]
        + 0.15 * out["size_set_completeness"].clip(0, 1)
        + 0.05 * out["stock_index"]
    )
    out["commercial_score"] = out["commercial_score"].round(1)

    def price_band(group: pd.Series) -> pd.Series:
        valid = group.replace(0, np.nan)
        if valid.notna().sum() < 3 or valid.nunique() < 3:
            return pd.Series(["Mid"] * len(group), index=group.index)
        ranks = valid.rank(pct=True).fillna(0.5)
        return pd.cut(ranks, bins=[-0.01, 0.33, 0.67, 1.01], labels=["Low", "Mid", "High"]).astype(str)

    out["price_band"] = out.groupby("brand", dropna=False)["avg_selling_price"].transform(price_band)

    def decision(r: pd.Series) -> str:
        if r["stock_qty"] <= 0:
            return "Do not display. No stock"
        if r["sales_qty"] <= 0:
            return "Tertiary or transfer review"
        if r["weeks_cover"] > 26 and r["velocity_index"] < 0.35:
            return "Reduce visibility or transfer review"
        if r["commercial_score"] >= 80:
            return "Prime placement"
        if r["commercial_score"] >= 60:
            return "Secondary placement"
        return "Tertiary placement"

    def zone(r: pd.Series) -> str:
        if r["display_category"] == "Accessories":
            return "Feature"
        if r["commercial_score"] >= 80:
            return "Prime"
        if r["commercial_score"] >= 55:
            return "Secondary"
        return "Tertiary"

    def reason(r: pd.Series) -> str:
        parts = [f"score {r['commercial_score']:.1f}/100"]
        if r["velocity_index"] >= 0.75:
            parts.append("high sales velocity within its brand and category")
        elif r["velocity_index"] <= 0.25:
            parts.append("low relative sales velocity")
        if r["sell_through_proxy"] >= 0.65:
            parts.append("strong sales-to-stock movement")
        if r["size_set_completeness"] >= 0.75:
            parts.append("healthy size availability")
        elif r["size_set_completeness"] < 0.40:
            parts.append("incomplete size set")
        if r["weeks_cover"] > 26:
            parts.append("high stock cover")
        if r["stock_qty"] <= 0:
            parts.append("no displayable stock")
        return "; ".join(parts)

    out["recommended_action"] = out.apply(decision, axis=1)
    out["recommended_zone"] = out.apply(zone, axis=1)
    out["xai_reason"] = out.apply(reason, axis=1)
    return out.sort_values(["commercial_score", "sales_value"], ascending=False).reset_index(drop=True)


def fixture_templates(brand: str) -> dict[str, dict[str, Any]]:
    """Backward-compatible selected-brand template collection."""
    return get_templates_for_brand(brand)


def all_planogram_templates(brand: str = "APEX", family: str = "All included") -> dict[str, dict[str, Any]]:
    """Return all approved wall and fixture planograms included in the app."""
    return get_all_templates(brand, family=family)


def _row_zone(row: int, rows: int) -> str:
    if rows == 4:
        return {1: "Feature", 2: "Prime", 3: "Secondary", 4: "Tertiary"}[row]
    if rows == 2:
        return {1: "Prime", 2: "Secondary"}[row]
    midpoint = (rows + 1) / 2
    if abs(row - midpoint) <= 0.5:
        return "Prime"
    if row == 1:
        return "Feature"
    if row == rows:
        return "Tertiary"
    return "Secondary"


def build_slots(template: dict[str, Any]) -> pd.DataFrame:
    """Build logical slots from the visual-template coordinate map."""
    if template.get("slots"):
        slots = pd.DataFrame(template["slots"]).copy()
        if "position_type" not in slots:
            slots["position_type"] = "Product"
        if "posm_label" not in slots:
            slots["posm_label"] = ""
        if "visibility_weight" not in slots:
            slots["visibility_weight"] = slots["zone"].map(ZONE_WEIGHTS).fillna(1.0)
        return slots

    rows: list[dict[str, Any]] = []
    for row in range(1, template.get("rows", 1) + 1):
        for col in range(1, template.get("columns", 1) + 1):
            zone = _row_zone(row, template.get("rows", 1))
            rows.append({
                "slot_id": f"R{row}-C{col}", "bay": 1, "row": row, "slot": col,
                "zone": zone, "visibility_weight": ZONE_WEIGHTS[zone],
                "position_type": "Product", "posm_label": "",
            })
    return pd.DataFrame(rows)


def _story_group(display_category: str, display_gender: str) -> str:
    if display_category in ["Formal Shoes", "Casual Shoes"]:
        return "Classic"
    if display_category in ["Sports / Sneakers"]:
        return "Sports"
    if display_category in ["School Shoes"] or display_gender == "Kids":
        return "Kids"
    if display_category in ["Pumps / Heels"]:
        return "Women Fashion"
    if display_category in ["Sandals", "Slippers"]:
        return "Open Footwear"
    if display_category == "Accessories":
        return "Accessories"
    return display_category


def _category_quotas(eligible: pd.DataFrame, capacity: int) -> dict[str, int]:
    if eligible.empty or capacity <= 0:
        return {}
    sales = eligible.groupby("display_category")["sales_value"].sum().sort_values(ascending=False)
    if sales.sum() <= 0:
        sales = eligible.groupby("display_category").size().astype(float)
    raw = sales / sales.sum() * capacity
    quotas = raw.apply(np.floor).astype(int).to_dict()
    for cat in sales.index:
        quotas[cat] = max(1, quotas.get(cat, 0))
    while sum(quotas.values()) > capacity:
        reducible = [c for c, q in quotas.items() if q > 1]
        if not reducible:
            break
        cat = min(reducible, key=lambda c: raw.get(c, 0) - quotas[c])
        quotas[cat] -= 1
    while sum(quotas.values()) < capacity:
        cat = max(sales.index, key=lambda c: raw.get(c, 0) - quotas.get(c, 0))
        quotas[cat] = quotas.get(cat, 0) + 1
    return quotas


def allocate_planogram(scored: pd.DataFrame, template: dict[str, Any], include_accessories: bool = True, min_stock: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = scored[scored["stock_qty"] >= min_stock].copy()
    if not include_accessories:
        candidates = candidates[candidates["is_footwear"]].copy()
    candidates = candidates[~candidates["display_category"].eq("Apparel")].copy()
    candidates["story_group"] = candidates.apply(lambda r: _story_group(r["display_category"], r["display_gender"]), axis=1)

    slots = build_slots(template)
    product_slots = slots[slots["position_type"] == "Product"].copy()
    capacity = min(template["capacity"], len(product_slots), len(candidates))
    quotas = _category_quotas(candidates, capacity)

    selected_parts: list[pd.DataFrame] = []
    used_codes: set[str] = set()
    for category, quota in quotas.items():
        part = candidates[candidates["display_category"] == category].head(quota)
        selected_parts.append(part)
        used_codes.update(part["article_code"].astype(str))
    selected = pd.concat(selected_parts, ignore_index=True) if selected_parts else candidates.head(0)
    if len(selected) < capacity:
        fill = candidates[~candidates["article_code"].astype(str).isin(used_codes)].head(capacity - len(selected))
        selected = pd.concat([selected, fill], ignore_index=True)
    selected = selected.drop_duplicates("article_code").head(capacity).copy()

    story_sales = selected.groupby("story_group")["sales_value"].sum().sort_values(ascending=False)
    bay_story = {bay: story for bay, story in zip(range(1, template.get("bays", 1) + 1), story_sales.index)}

    slot_order = product_slots.assign(zone_order=product_slots["zone"].map({"Prime": 1, "Feature": 2, "Secondary": 3, "Tertiary": 4}).fillna(5)).sort_values(["zone_order", "bay", "row", "slot"])
    remaining = selected.copy()
    placements: list[dict[str, Any]] = []
    bay_categories: dict[int, list[str]] = {}

    for _, slot in slot_order.iterrows():
        if remaining.empty:
            break
        scores = remaining["commercial_score"] * float(slot["visibility_weight"])
        scores += np.where(remaining["recommended_zone"] == slot["zone"], 18, 0)
        scores += np.where((remaining["recommended_zone"] == "Prime") & (slot["zone"] in ["Feature", "Secondary"]), 6, 0)
        scores += np.where((remaining["display_category"] == "Accessories") & (slot["zone"] == "Feature"), 20, 0)
        scores += np.where((remaining["price_band"] == "Low") & (slot["zone"] == "Tertiary"), 8, 0)
        target_story = bay_story.get(int(slot["bay"]))
        if target_story:
            scores += np.where(remaining["story_group"] == target_story, 16, 0)
        existing = bay_categories.get(int(slot["bay"]), [])
        if existing:
            scores += remaining["display_category"].isin(existing).astype(int) * 5
        best_idx = scores.idxmax()
        r = remaining.loc[best_idx]
        placement = {**slot.to_dict(), **r.to_dict(), "placement_score": round(float(scores.loc[best_idx]), 1)}
        placements.append(placement)
        bay_categories.setdefault(int(slot["bay"]), []).append(str(r["display_category"]))
        remaining = remaining.drop(index=best_idx)

    placement_df = pd.DataFrame(placements)
    reserved = slots[slots["position_type"] == "POSM"].copy()
    for c in placement_df.columns:
        if c not in reserved.columns:
            reserved[c] = np.nan
    for c in reserved.columns:
        if c not in placement_df.columns:
            placement_df[c] = np.nan
    placement_df = pd.concat([placement_df, reserved[placement_df.columns]], ignore_index=True, sort=False)

    selected_codes = set(placement_df.loc[placement_df["position_type"] == "Product", "article_code"].astype(str))
    unselected = candidates[~candidates["article_code"].astype(str).isin(selected_codes)].copy()

    if not placement_df.empty:
        for idx, r in placement_df[placement_df["position_type"] == "Product"].iterrows():
            pool = unselected[(unselected["display_category"] == r["display_category"]) & (unselected["display_gender"] == r["display_gender"])]
            if pool.empty:
                pool = unselected[unselected["display_category"] == r["display_category"]]
            if pool.empty:
                pool = unselected
            if not pool.empty:
                alt = pool.iloc[0]
                placement_df.loc[idx, "next_best_article"] = alt["article_code"]
                placement_df.loc[idx, "next_best_score"] = alt["commercial_score"]
                placement_df.loc[idx, "next_best_reason"] = f"Next-ranked {alt['display_category']} article with stock {int(alt['stock_qty'])} and score {alt['commercial_score']:.1f}."
            else:
                placement_df.loc[idx, "next_best_article"] = ""
                placement_df.loc[idx, "next_best_score"] = np.nan
                placement_df.loc[idx, "next_best_reason"] = "No eligible alternative in the current filter."

    allocation = scored.copy()
    slot_map = placement_df[placement_df["position_type"] == "Product"].set_index("article_code")["slot_id"].to_dict() if not placement_df.empty else {}
    allocation["selected_for_planogram"] = allocation["article_code"].map(lambda x: str(x) in selected_codes)
    allocation["assigned_slot"] = allocation["article_code"].map(slot_map).fillna("")
    allocation["selection_reason"] = np.where(
        allocation["selected_for_planogram"],
        "Selected by commercial score, stock availability and VM slot compatibility.",
        np.where(allocation["stock_qty"] <= 0, "Not eligible. No stock.", "Not selected within the current fixture capacity."),
    )
    return placement_df.sort_values(["bay", "row", "slot"]).reset_index(drop=True), allocation


def make_execution_legend(placements: pd.DataFrame) -> pd.DataFrame:
    products = placements[placements["position_type"] == "Product"].copy()
    if products.empty:
        return products
    products = products.reset_index(drop=True)
    products["display_code"] = [f"A{i:03d}" for i in range(1, len(products) + 1)]
    cols = [
        "display_code", "slot_id", "bay", "row", "zone", "article_code", "brand", "display_gender",
        "display_category", "color", "sales_qty", "weekly_sales_units", "stock_qty", "size_set_completeness",
        "commercial_score", "recommended_action", "xai_reason", "next_best_article", "next_best_score", "next_best_reason",
    ]
    return products[[c for c in cols if c in products.columns]]


def _safe_font(size: int, bold: bool = False):
    """Load a readable Windows/Linux font, falling back to Pillow default."""
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_center(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill: str = "black") -> None:
    box = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=3)
    width = box[2] - box[0]
    height = box[3] - box[1]
    draw.multiline_text((xy[0] - width / 2, xy[1] - height / 2), text, font=font, fill=fill, align="center", spacing=3)


def draw_planogram(placements: pd.DataFrame, template: dict[str, Any], brand: str, store_name: str) -> Image.Image:
    """Create the planogram as a Pillow image. No Matplotlib dependency."""
    brand_key = brand.upper() if brand.upper() in BRAND_CONFIG else "GENERIC"
    accent = BRAND_CONFIG[brand_key]["accent"]
    legend = make_execution_legend(placements)
    code_map = legend.set_index("slot_id")["display_code"].to_dict() if not legend.empty else {}

    if template["kind"] == "wall":
        width, height = 1800, 980
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        title_font = _safe_font(32, bold=True)
        header_font = _safe_font(23, bold=True)
        body_font = _safe_font(17)
        small_font = _safe_font(14)
        code_font = _safe_font(22, bold=True)
        category_font = _safe_font(14)

        left, top, right, bottom = 175, 105, 1750, 875
        wall_w = right - left
        brand_h = 150
        merch_top = top + brand_h
        bay_w = wall_w / 3
        selling_h = bottom - merch_top
        row_h = selling_h / 4
        slot_w = bay_w / 3

        _text_center(draw, (width / 2, 45), f"ApexSpace Pro. {brand.title()} Wall Planogram", title_font, "#222222")
        draw.rectangle((left, top, right, bottom), outline="#222222", width=4)
        draw.rectangle((left, top, right, merch_top), fill="#F4F4F4", outline=accent, width=4)
        _text_center(draw, (width / 2, top + 48), f"{brand.upper()} BRAND / CAMPAIGN AREA", header_font, accent)
        _text_center(draw, (width / 2, top + 100), "Top area reserved for branding, campaign visuals and approved communication", body_font, "#444444")

        for bay in range(1, 3):
            x = left + bay * bay_w
            draw.line((x, merch_top, x, bottom), fill="#777777", width=3)
        for row in range(1, 4):
            y = merch_top + row * row_h
            draw.line((left, y, right, y), fill="#333333", width=3)

        zone_labels = {1: "Feature", 2: "Prime eye level", 3: "Secondary", 4: "Tertiary"}
        for row in range(1, 5):
            cy = merch_top + (row - 0.5) * row_h
            _text_center(draw, (85, cy), zone_labels[row], small_font, "#222222")
        for bay in range(1, 4):
            cx = left + (bay - 0.5) * bay_w
            _text_center(draw, (cx, 905), f"Bay {bay}", body_font, "#222222")

        for _, r in placements.iterrows():
            bay, row, slot = int(r["bay"]), int(r["row"]), int(r["slot"])
            x0 = left + (bay - 1) * bay_w + (slot - 1) * slot_w + 10
            y0 = merch_top + (row - 1) * row_h + 10
            x1 = left + (bay - 1) * bay_w + slot * slot_w - 10
            y1 = merch_top + row * row_h - 10
            if r["position_type"] == "POSM":
                draw.rounded_rectangle((x0, y0, x1, y1), radius=12, fill="#FFF4D6", outline=accent, width=3)
                label = str(r.get("posm_label", "POSM"))[:34]
                _text_center(draw, ((x0 + x1) / 2, (y0 + y1) / 2), f"POSM\n{label}", body_font, "#333333")
            else:
                category = str(r.get("display_category", "Other Footwear"))
                face = DISPLAY_CATEGORY_COLORS.get(category, "#4E79A7")
                draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=face, outline="#111111", width=3)
                code = code_map.get(str(r["slot_id"]), str(r.get("article_code", ""))[:8])
                _text_center(draw, ((x0 + x1) / 2, y0 + (y1-y0)*0.38), code, code_font, "white")
                _text_center(draw, ((x0 + x1) / 2, y0 + (y1-y0)*0.72), category[:22], category_font, "white")

        footer = f"Store: {store_name}. Product capacity: {template['capacity']} options. POSM positions follow the Apex docket rule."
        _text_center(draw, (width / 2, 952), footer, small_font, "#333333")
        return image

    rows, cols = int(template["rows"]), int(template["columns"])
    cell_w, cell_h = 220, 150
    margin_x, margin_y = 90, 145
    width = margin_x * 2 + cols * cell_w
    height = margin_y + rows * cell_h + 100
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _safe_font(28, bold=True)
    code_font = _safe_font(20, bold=True)
    category_font = _safe_font(14)
    small_font = _safe_font(14)
    _text_center(draw, (width / 2, 45), f"{brand.title()}. {template['name']}", title_font, "#222222")
    _text_center(draw, (width / 2, 88), f"Capacity {template['capacity']} options. Add approved raisers and signage cube.", small_font, "#444444")

    for row in range(rows):
        for col in range(cols):
            x0 = margin_x + col * cell_w
            y0 = margin_y + row * cell_h
            draw.rectangle((x0, y0, x0 + cell_w, y0 + cell_h), outline="#777777", width=2)

    for _, r in placements[placements["position_type"] == "Product"].iterrows():
        row, col = int(r["row"]), int(r["slot"])
        x0 = margin_x + (col - 1) * cell_w + 10
        y0 = margin_y + (row - 1) * cell_h + 10
        x1 = x0 + cell_w - 20
        y1 = y0 + cell_h - 20
        category = str(r.get("display_category", "Other Footwear"))
        face = DISPLAY_CATEGORY_COLORS.get(category, "#4E79A7")
        draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=face, outline="#111111", width=3)
        code = code_map.get(str(r["slot_id"]), str(r.get("article_code", ""))[:8])
        _text_center(draw, ((x0+x1)/2, y0 + 45), code, code_font, "white")
        _text_center(draw, ((x0+x1)/2, y0 + 90), category[:24], category_font, "white")
    return image

def export_execution_xlsx(placements: pd.DataFrame, allocation: pd.DataFrame, summary: SourceSummary, store_name: str, review_cadence: str) -> bytes:
    legend = make_execution_legend(placements)
    posm = placements[placements["position_type"] == "POSM"][["slot_id", "bay", "row", "slot", "posm_label"]].copy() if not placements.empty else pd.DataFrame()
    info = pd.DataFrame([
        ["Store", store_name],
        ["Source", summary.source_name],
        ["Analysis basis", summary.period_description],
        ["Review cadence", review_cadence],
        ["Important limitation", "The source is cumulative. It does not contain weekly sales history, product cost, age or live display observations."],
        ["OOD interpretation", "Not selected for this recommended planogram. This is not physical-photo OOD detection."],
    ], columns=["Field", "Value"])
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        info.to_excel(writer, sheet_name="Read Me", index=False)
        legend.to_excel(writer, sheet_name="Execution Plan", index=False)
        posm.to_excel(writer, sheet_name="POSM Positions", index=False)
        allocation.to_excel(writer, sheet_name="Article Allocation", index=False)
    buffer.seek(0)
    return buffer.getvalue()


def next_review_date(cadence: str, today: date | None = None) -> date:
    today = today or date.today()
    days = {"Weekly": 7, "Fortnightly": 14, "Monthly": 30}.get(cadence, 7)
    return today + timedelta(days=days)
