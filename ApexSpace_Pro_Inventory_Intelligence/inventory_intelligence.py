from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Iterable

import numpy as np
import pandas as pd


CURRENT_DATA_BASIS = "6.5-month cumulative sales and current stock snapshot"

ZONE_ORDER = {
    "Feature": 4,
    "Prime": 3,
    "Secondary": 2,
    "Tertiary": 1,
    "Remove": 0,
    "Backroom": 0,
    "Unknown": -1,
}

LIFECYCLE_THRESHOLDS = {
    "Fashion / Seasonal": {
        "new": 30,
        "productive": 60,
        "mature": 90,
        "aging": 120,
        "high_risk": 180,
        "dead": 180,
    },
    "Core / Replenishment": {
        "new": 60,
        "productive": 120,
        "mature": 180,
        "aging": 270,
        "high_risk": 365,
        "dead": 365,
    },
}

NETWORK_COLUMN_ALIASES = {
    "week": "week_start",
    "date": "week_start",
    "week_date": "week_start",
    "store": "store_id",
    "store_name": "store_id",
    "sku": "article_code",
    "product_code": "article_code",
    "article": "article_code",
    "sales_qty": "sales_units",
    "units_sold": "sales_units",
    "net_sales": "sales_value",
    "closing_stock_units": "closing_stock",
    "stock_qty": "closing_stock",
    "inventory": "closing_stock",
    "first_receipt": "first_receipt_date",
    "launch": "launch_date",
    "zone": "current_zone",
}

DISPLAY_COLUMN_ALIASES = {
    "store": "store_id",
    "article": "article_code",
    "sku": "article_code",
    "zone": "current_zone",
    "slot": "current_slot",
}

DISTANCE_COLUMN_ALIASES = {
    "source_store": "from_store",
    "sender_store": "from_store",
    "destination_store": "to_store",
    "receiver_store": "to_store",
    "km": "distance_km",
}


@dataclass(frozen=True)
class IntelligenceSummary:
    articles: int
    fast_movers: int
    slow_movers: int
    non_movers: int
    dead_stock_or_risk: int
    broken_size_curves: int
    critical_alerts: int
    transfer_candidates: int
    age_available: bool
    data_basis: str


def _clean_col_name(value: object) -> str:
    return str(value).strip().lower().replace("/", "_").replace(" ", "_").replace("-", "_")


def _rename_aliases(df: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    rename: dict[object, str] = {}
    for col in df.columns:
        cleaned = _clean_col_name(col)
        rename[col] = aliases.get(cleaned, cleaned)
    return df.rename(columns=rename)


def _read_table(source: str | Path | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    name = (filename or getattr(source, "name", None) or str(source)).lower()
    if name.endswith(".csv"):
        return pd.read_csv(source)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(source)
    raise ValueError("Use CSV, XLSX or XLS for the inventory-intelligence input.")


def load_network_data(source: str | Path | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    raw = _rename_aliases(_read_table(source, filename), NETWORK_COLUMN_ALIASES)
    required = ["week_start", "store_id", "article_code", "size", "sales_units", "closing_stock"]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise ValueError(f"The weekly store file is missing required columns: {missing}")

    out = raw.copy()
    out["week_start"] = pd.to_datetime(out["week_start"], errors="coerce")
    if out["week_start"].isna().all():
        raise ValueError("No valid week_start dates were found.")
    out = out.dropna(subset=["week_start"]).copy()
    for col in ["store_id", "article_code", "size"]:
        out[col] = out[col].fillna("").astype(str).str.strip()
    out = out[(out["store_id"] != "") & (out["article_code"] != "")].copy()

    numeric_cols = [
        "sales_units", "sales_value", "opening_stock", "receipts", "transfers_in",
        "transfers_out", "closing_stock", "cost_per_unit",
    ]
    for col in numeric_cols:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    out["negative_sales_flag"] = out["sales_units"] < 0
    out["negative_stock_flag"] = out["closing_stock"] < 0
    out["sales_units"] = out["sales_units"].clip(lower=0)
    out["closing_stock"] = out["closing_stock"].clip(lower=0)

    for col in ["launch_date", "first_receipt_date", "last_receipt_date"]:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    if "current_zone" not in out.columns:
        out["current_zone"] = "Unknown"
    out["current_zone"] = out["current_zone"].fillna("Unknown").astype(str).str.strip().replace("", "Unknown")
    return out.reset_index(drop=True)


def load_current_display(source: str | Path | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    out = _rename_aliases(_read_table(source, filename), DISPLAY_COLUMN_ALIASES)
    required = ["article_code", "current_zone"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"The current-display file is missing required columns: {missing}")
    if "store_id" not in out.columns:
        out["store_id"] = ""
    if "current_slot" not in out.columns:
        out["current_slot"] = ""
    for col in ["store_id", "article_code", "current_zone", "current_slot"]:
        out[col] = out[col].fillna("").astype(str).str.strip()
    return out.drop_duplicates(["store_id", "article_code"], keep="last").reset_index(drop=True)


def load_store_distances(source: str | Path | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    out = _rename_aliases(_read_table(source, filename), DISTANCE_COLUMN_ALIASES)
    required = ["from_store", "to_store", "distance_km"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"The store-distance file is missing required columns: {missing}")
    out["from_store"] = out["from_store"].fillna("").astype(str).str.strip()
    out["to_store"] = out["to_store"].fillna("").astype(str).str.strip()
    out["distance_km"] = pd.to_numeric(out["distance_km"], errors="coerce")
    return out.dropna(subset=["distance_km"]).drop_duplicates(["from_store", "to_store"]).reset_index(drop=True)


def infer_lifecycle_type(display_category: object, explicit: object = "") -> str:
    explicit_text = str(explicit or "").strip().lower()
    if "core" in explicit_text or "replen" in explicit_text or "basic" in explicit_text:
        return "Core / Replenishment"
    if "fashion" in explicit_text or "season" in explicit_text:
        return "Fashion / Seasonal"
    category = str(display_category or "").strip()
    if category in {"School Shoes", "Formal Shoes"}:
        return "Core / Replenishment"
    return "Fashion / Seasonal"


def age_bucket(age_days: float | int | None, lifecycle_type: str) -> str:
    if age_days is None or pd.isna(age_days):
        return "Age unavailable"
    age = max(0, int(age_days))
    limits = LIFECYCLE_THRESHOLDS.get(lifecycle_type, LIFECYCLE_THRESHOLDS["Fashion / Seasonal"])
    if age <= limits["new"]:
        return "New"
    if age <= limits["productive"]:
        return "Productive"
    if age <= limits["mature"]:
        return "Mature"
    if age <= limits["aging"]:
        return "Aging"
    if age <= limits["high_risk"]:
        return "High-risk aging"
    return "Dead-stock age review"


def _percentile_rank(series: pd.Series) -> pd.Series:
    if len(series) <= 1:
        return pd.Series(np.ones(len(series)), index=series.index)
    return series.rank(method="average", pct=True)


def _core_size_table(size_df: pd.DataFrame) -> pd.DataFrame:
    working = size_df.copy()
    working["sales_qty_clean"] = pd.to_numeric(working.get("sales_qty", 0), errors="coerce").fillna(0).clip(lower=0)
    group_cols = ["brand", "display_gender", "display_category"]
    size_sales = (
        working.groupby(group_cols + ["size"], dropna=False, as_index=False)["sales_qty_clean"]
        .sum()
        .rename(columns={"sales_qty_clean": "network_size_sales"})
    )
    size_sales["size_weight"] = size_sales.groupby(group_cols)["network_size_sales"].transform(
        lambda s: s / s.sum() if s.sum() > 0 else np.repeat(1 / max(len(s), 1), len(s))
    )
    size_sales = size_sales.sort_values(group_cols + ["size_weight"], ascending=[True, True, True, False])
    size_sales["cum_weight"] = size_sales.groupby(group_cols)["size_weight"].cumsum()
    size_sales["core_size"] = size_sales["cum_weight"].shift(fill_value=0) < 0.70
    first_rows = size_sales.groupby(group_cols, dropna=False).head(1).index
    size_sales.loc[first_rows, "core_size"] = True
    return size_sales[group_cols + ["size", "network_size_sales", "size_weight", "core_size"]]


def _article_size_health(size_df: pd.DataFrame) -> pd.DataFrame:
    working = size_df.copy()
    for col in ["article_code", "brand", "display_gender", "display_category", "size"]:
        working[col] = working[col].fillna("").astype(str).str.strip()
    working["sales_qty_clean"] = pd.to_numeric(working.get("sales_qty", 0), errors="coerce").fillna(0).clip(lower=0)
    working["stock_qty_clean"] = pd.to_numeric(working.get("stock_qty", 0), errors="coerce").fillna(0).clip(lower=0)
    core = _core_size_table(working)
    working = working.merge(core, on=["brand", "display_gender", "display_category", "size"], how="left")
    working["size_weight"] = working["size_weight"].fillna(0)
    working["core_size"] = working["core_size"].fillna(False)
    working["in_stock"] = working["stock_qty_clean"] > 0
    working["weighted_in_stock"] = working["size_weight"] * working["in_stock"].astype(float)

    def aggregate(group: pd.DataFrame) -> pd.Series:
        weight_sum = group["size_weight"].sum()
        if weight_sum <= 0:
            weighted_availability = float(group["in_stock"].mean()) if len(group) else 0.0
        else:
            weighted_availability = float(group["weighted_in_stock"].sum() / weight_sum)
        core_group = group[group["core_size"]]
        core_availability = float(core_group["in_stock"].mean()) if len(core_group) else weighted_availability
        return pd.Series({
            "known_sizes": int(group["size"].nunique()),
            "sizes_in_stock_detail": int(group.loc[group["in_stock"], "size"].nunique()),
            "weighted_size_availability": weighted_availability,
            "core_size_availability": core_availability,
            "core_sizes_known": int(core_group["size"].nunique()),
            "core_sizes_in_stock": int(core_group.loc[core_group["in_stock"], "size"].nunique()),
        })

    result = working.groupby("article_code", as_index=False).apply(aggregate, include_groups=False)
    if "level_1" in result.columns:
        result = result.drop(columns=["level_1"])
    return result.reset_index(drop=True)


def _extract_article_age(size_df: pd.DataFrame, today: date) -> pd.DataFrame:
    date_columns = [c for c in ["launch_date", "first_receipt_date", "last_receipt_date"] if c in size_df.columns]
    if not date_columns:
        return pd.DataFrame({"article_code": size_df["article_code"].drop_duplicates(), "inventory_start_date": pd.NaT, "age_days": np.nan})

    working = size_df[["article_code"] + date_columns].copy()
    for col in date_columns:
        working[col] = pd.to_datetime(working[col], errors="coerce")
    working["inventory_start_date"] = working[date_columns].min(axis=1)
    article_age = working.groupby("article_code", as_index=False)["inventory_start_date"].min()
    today_ts = pd.Timestamp(today)
    article_age["age_days"] = (today_ts - article_age["inventory_start_date"]).dt.days.clip(lower=0)
    return article_age


def build_inventory_health(
    size_df: pd.DataFrame,
    article_master: pd.DataFrame,
    today: date | None = None,
    default_lifecycle: str = "Auto by category",
) -> pd.DataFrame:
    today = today or date.today()
    health = article_master.copy()
    for col in ["sales_qty", "sales_value", "stock_qty", "weekly_sales_units", "weeks_cover", "sell_through_proxy", "avg_selling_price", "stock_value_proxy"]:
        if col not in health.columns:
            health[col] = 0.0
        health[col] = pd.to_numeric(health[col], errors="coerce").fillna(0.0)

    health["negative_sales_source"] = health["sales_qty"] < 0
    health["negative_stock_source"] = health["stock_qty"] < 0
    health["sales_qty"] = health["sales_qty"].clip(lower=0)
    health["stock_qty"] = health["stock_qty"].clip(lower=0)
    health["weekly_sales_units"] = health["sales_qty"] / (6.5 * 52 / 12)
    health["weeks_cover"] = np.where(health["weekly_sales_units"] > 0, health["stock_qty"] / health["weekly_sales_units"], np.where(health["stock_qty"] > 0, 999.0, 0.0))
    health["sell_through_proxy"] = np.where(
        health["sales_qty"] + health["stock_qty"] > 0,
        health["sales_qty"] / (health["sales_qty"] + health["stock_qty"]),
        0.0,
    )
    health["stock_value_proxy"] = health["stock_qty"] * health["avg_selling_price"]

    size_health = _article_size_health(size_df)
    health = health.merge(size_health, on="article_code", how="left")
    for col in ["weighted_size_availability", "core_size_availability"]:
        health[col] = pd.to_numeric(health[col], errors="coerce").fillna(0).clip(0, 1)
    for col in ["known_sizes", "sizes_in_stock_detail", "core_sizes_known", "core_sizes_in_stock"]:
        health[col] = pd.to_numeric(health[col], errors="coerce").fillna(0).astype(int)

    group_cols = ["brand", "display_gender", "display_category"]
    health["velocity_percentile"] = health.groupby(group_cols, dropna=False)["weekly_sales_units"].transform(_percentile_rank)
    health["sales_value_percentile"] = health.groupby(group_cols, dropna=False)["sales_value"].transform(_percentile_rank)

    age = _extract_article_age(size_df, today)
    health = health.merge(age, on="article_code", how="left")
    if "lifecycle_type" in size_df.columns:
        lifecycle_map = size_df.groupby("article_code")["lifecycle_type"].first()
        health["lifecycle_source"] = health["article_code"].map(lifecycle_map).fillna("")
    else:
        health["lifecycle_source"] = ""

    if default_lifecycle in LIFECYCLE_THRESHOLDS:
        health["lifecycle_type"] = default_lifecycle
    else:
        health["lifecycle_type"] = health.apply(
            lambda r: infer_lifecycle_type(r.get("display_category", ""), r.get("lifecycle_source", "")), axis=1
        )
    health["age_bucket"] = health.apply(lambda r: age_bucket(r.get("age_days"), r["lifecycle_type"]), axis=1)

    def movement(row: pd.Series) -> str:
        if row["stock_qty"] <= 0 and row["sales_qty"] > 0:
            return "Sold out / OOS"
        if row["stock_qty"] <= 0 and row["sales_qty"] <= 0:
            return "Inactive. No stock"
        if row["sales_qty"] <= 0:
            return "Non-mover"
        if row["velocity_percentile"] >= 0.80 and (row["sell_through_proxy"] >= 0.55 or row["weeks_cover"] <= 12):
            return "Fast mover"
        if row["velocity_percentile"] >= 0.40:
            return "Medium mover"
        return "Slow mover"

    health["movement_status"] = health.apply(movement, axis=1)

    def size_curve(row: pd.Series) -> str:
        if row["stock_qty"] <= 0:
            return "No stock"
        if row["core_size_availability"] < 0.50 or row["weighted_size_availability"] < 0.45:
            return "Broken size curve"
        if row["core_size_availability"] < 0.80 or row["weighted_size_availability"] < 0.70:
            return "Size curve at risk"
        return "Healthy size curve"

    health["size_curve_status"] = health.apply(size_curve, axis=1)

    def cover_status(row: pd.Series) -> str:
        if row["stock_qty"] <= 0:
            return "Out of stock"
        if row["weekly_sales_units"] <= 0:
            return "No-sale stock"
        if row["weeks_cover"] < 2:
            return "Critical understock"
        if row["weeks_cover"] < 4:
            return "Understock"
        if row["weeks_cover"] <= 12:
            return "Healthy cover"
        if row["weeks_cover"] <= 24:
            return "Excess cover"
        return "Severe excess cover"

    health["cover_status"] = health.apply(cover_status, axis=1)

    def dead_status(row: pd.Series) -> str:
        limits = LIFECYCLE_THRESHOLDS[row["lifecycle_type"]]
        if pd.notna(row.get("age_days")):
            if row["stock_qty"] > 0 and row["sales_qty"] <= 0 and row["age_days"] >= limits["dead"]:
                return "Dead stock"
            if row["stock_qty"] > 0 and row["age_days"] > limits["high_risk"] and row["movement_status"] in {"Slow mover", "Non-mover"}:
                return "High-risk aged stock"
            return "Not dead stock"
        if row["stock_qty"] > 0 and row["sales_qty"] <= 0:
            return "Dead-stock risk. Age and recent sales unavailable"
        return "Age validation required"

    health["dead_stock_status"] = health.apply(dead_status, axis=1)

    def target_zone(row: pd.Series) -> str:
        if row["stock_qty"] <= 0 or row["dead_stock_status"] == "Dead stock":
            return "Remove"
        if row["movement_status"] == "Non-mover":
            return "Remove"
        if row["movement_status"] == "Fast mover" and row["size_curve_status"] == "Healthy size curve":
            return "Prime" if row["weeks_cover"] <= 16 else "Secondary"
        if row["age_bucket"] == "New" and row["velocity_percentile"] >= 0.60 and row["size_curve_status"] != "Broken size curve":
            return "Feature"
        if row["movement_status"] == "Medium mover" or row["size_curve_status"] == "Size curve at risk":
            return "Secondary"
        return "Tertiary"

    health["target_zone"] = health.apply(target_zone, axis=1)

    def markdown(row: pd.Series) -> str:
        if row["dead_stock_status"] == "Dead stock":
            return "Final clearance / liquidation review"
        if row["dead_stock_status"].startswith("Dead-stock risk"):
            return "Verify age and last sale, then markdown or consolidate"
        if row["age_bucket"] == "High-risk aging" and row["weeks_cover"] > 24:
            return "20-30% markdown review after transfer check"
        if row["movement_status"] == "Slow mover" and row["weeks_cover"] > 24:
            return "10-15% markdown review after visibility and transfer test"
        return "No markdown trigger"

    health["markdown_recommendation"] = health.apply(markdown, axis=1)
    health["transfer_out_candidate"] = (
        (health["stock_qty"] >= 2)
        & (health["movement_status"].isin(["Slow mover", "Non-mover"]))
        & ((health["weeks_cover"] > 24) | (health["weekly_sales_units"] <= 0))
    )
    health["transfer_in_candidate"] = (
        health["movement_status"].isin(["Fast mover", "Medium mover"])
        & ((health["weeks_cover"] < 4) | (health["stock_qty"] <= 0) | (health["core_size_availability"] < 0.50))
    )
    health["data_basis"] = CURRENT_DATA_BASIS
    health["classification_confidence"] = np.where(
        health["age_bucket"].eq("Age unavailable"), "Medium. Age and recent-week sales missing", "High"
    )
    return health.sort_values(["brand", "display_category", "movement_status", "sales_value"], ascending=[True, True, True, False]).reset_index(drop=True)


def build_within_store_actions(
    health: pd.DataFrame,
    store_name: str,
    placements: pd.DataFrame | None = None,
    current_display: pd.DataFrame | None = None,
) -> pd.DataFrame:
    result = health.copy()
    result["store_id"] = store_name
    result["current_zone"] = "Unknown"
    result["current_slot"] = ""
    result["target_slot"] = ""

    if current_display is not None and not current_display.empty:
        display = current_display.copy()
        if "store_id" in display.columns and display["store_id"].astype(str).str.strip().ne("").any():
            display = display[(display["store_id"] == store_name) | (display["store_id"] == "")]
        result = result.drop(columns=["current_zone", "current_slot"], errors="ignore").merge(
            display[["article_code", "current_zone", "current_slot"]].drop_duplicates("article_code"),
            on="article_code", how="left",
        )
        result["current_zone"] = result["current_zone"].fillna("Unknown").replace("", "Unknown")
        result["current_slot"] = result["current_slot"].fillna("")

    if placements is not None and not placements.empty and "article_code" in placements.columns:
        target = placements[placements.get("position_type", "Product") == "Product"].copy()
        target = target[[c for c in ["article_code", "zone", "slot_id"] if c in target.columns]].drop_duplicates("article_code")
        target = target.rename(columns={"zone": "planogram_zone", "slot_id": "target_slot"})
        result = result.drop(columns=["target_slot"], errors="ignore").merge(target, on="article_code", how="left")
        result["target_zone"] = result["planogram_zone"].fillna(result["target_zone"])
        result["target_slot"] = result["target_slot"].fillna("")

    def action(row: pd.Series) -> str:
        current = str(row.get("current_zone", "Unknown") or "Unknown").title()
        target = str(row.get("target_zone", "Tertiary") or "Tertiary").title()
        if target == "Remove":
            if row["transfer_out_candidate"]:
                return "Remove from display and send for store-transfer review"
            return "Remove from display"
        if current in {"", "Unknown", "Nan"}:
            return f"Place in {target} space"
        current_rank = ZONE_ORDER.get(current, -1)
        target_rank = ZONE_ORDER.get(target, -1)
        if current_rank < target_rank:
            return f"Promote from {current} to {target}"
        if current_rank > target_rank:
            return f"Demote from {current} to {target}"
        return f"Retain in {target}"

    result["within_store_action"] = result.apply(action, axis=1)
    result["move_priority"] = np.select(
        [
            result["target_zone"].eq("Remove"),
            result["movement_status"].eq("Fast mover") & result["current_zone"].isin(["Secondary", "Tertiary", "Unknown"]),
            result["size_curve_status"].eq("Broken size curve"),
            result["cover_status"].eq("Severe excess cover"),
        ],
        ["Critical", "High", "High", "High"],
        default="Medium",
    )

    replacement_pool = result[
        (result["stock_qty"] > 0)
        & result["movement_status"].isin(["Fast mover", "Medium mover"])
        & ~result["size_curve_status"].eq("Broken size curve")
    ].sort_values(["velocity_percentile", "sales_value"], ascending=False)

    replacements: dict[str, tuple[str, str]] = {}
    for _, row in result.iterrows():
        pool = replacement_pool[
            (replacement_pool["brand"] == row["brand"])
            & (replacement_pool["display_gender"] == row["display_gender"])
            & (replacement_pool["display_category"] == row["display_category"])
            & (replacement_pool["article_code"] != row["article_code"])
        ]
        if pool.empty:
            replacements[row["article_code"]] = ("", "No eligible same-story replacement found")
        else:
            best = pool.iloc[0]
            replacements[row["article_code"]] = (
                str(best["article_code"]),
                f"{best['movement_status']}; {best['size_curve_status']}; WOC {best['weeks_cover']:.1f}",
            )
    result["replacement_article"] = result["article_code"].map(lambda x: replacements.get(x, ("", ""))[0])
    result["replacement_reason"] = result["article_code"].map(lambda x: replacements.get(x, ("", ""))[1])
    return result.reset_index(drop=True)


def generate_single_store_alerts(health_actions: pd.DataFrame, store_name: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(row: pd.Series, severity: str, alert_type: str, message: str, action: str, value_at_risk: float = 0.0) -> None:
        rows.append({
            "severity": severity,
            "alert_type": alert_type,
            "store_id": store_name,
            "article_code": row.get("article_code", ""),
            "brand": row.get("brand", ""),
            "gender": row.get("display_gender", ""),
            "category": row.get("display_category", ""),
            "movement_status": row.get("movement_status", ""),
            "age_bucket": row.get("age_bucket", ""),
            "dead_stock_status": row.get("dead_stock_status", ""),
            "size_curve_status": row.get("size_curve_status", ""),
            "cover_status": row.get("cover_status", ""),
            "current_zone": row.get("current_zone", "Unknown"),
            "target_zone": row.get("target_zone", ""),
            "current_stock": row.get("stock_qty", 0),
            "weekly_sales_units": row.get("weekly_sales_units", 0),
            "weeks_cover": row.get("weeks_cover", 0),
            "estimated_value_at_risk": round(float(value_at_risk or 0), 2),
            "message": message,
            "recommended_action": action,
            "confidence": row.get("classification_confidence", "Medium"),
            "data_basis": row.get("data_basis", CURRENT_DATA_BASIS),
            "status": "Open",
        })

    for _, row in health_actions.iterrows():
        four_week_sales_value = float(row.get("weekly_sales_units", 0) * row.get("avg_selling_price", 0) * 4)
        if row["movement_status"] == "Sold out / OOS" and row["velocity_percentile"] >= 0.60:
            add(row, "Critical", "Fast mover out of stock", "A selling article has no stock.", "Replenish or transfer in core sizes immediately.", four_week_sales_value)
        if row["size_curve_status"] == "Broken size curve" and row["movement_status"] in {"Fast mover", "Medium mover"}:
            add(row, "Critical", "Broken size curve", "Demand exists but important sizes are unavailable.", "Transfer in missing core sizes or replace the display article.", four_week_sales_value)
        if row["dead_stock_status"] == "Dead stock":
            add(row, "Critical", "Dead stock", "Aged inventory has no sales signal.", "Remove from planogram. Transfer, return, liquidate or final-clearance review.", row.get("stock_value_proxy", 0))
        elif str(row["dead_stock_status"]).startswith("Dead-stock risk"):
            add(row, "High", "Dead-stock risk", "Stock has no cumulative sales, but age and recent-week sales are unavailable.", "Verify launch date and last sale. Then transfer, consolidate or markdown.", row.get("stock_value_proxy", 0))
        if row["cover_status"] == "Severe excess cover" and row["stock_qty"] > 0:
            add(row, "High", "Severe excess cover", "Stock cover exceeds 24 weeks or the article has no sales velocity.", "Reduce display depth and review transfer-out before markdown.", row.get("stock_value_proxy", 0))
        if row["transfer_out_candidate"]:
            add(row, "High", "Store-transfer review", "The store has excess or no-sale stock.", "Search the network for a store with demand for the same article and size.", row.get("stock_value_proxy", 0))
        if str(row["within_store_action"]).startswith("Promote"):
            add(row, "Medium", "Promote within store", "A productive article is below its recommended visibility zone.", row["within_store_action"], four_week_sales_value)
        elif str(row["within_store_action"]).startswith("Demote"):
            add(row, "Medium", "Demote within store", "The article is using stronger space than its current productivity supports.", row["within_store_action"], row.get("stock_value_proxy", 0))
        if row["markdown_recommendation"] != "No markdown trigger":
            add(row, "Medium", "Markdown review", row["markdown_recommendation"], "Run transfer and visibility checks before approving markdown.", row.get("stock_value_proxy", 0))
        if row.get("negative_sales_source", False) or row.get("negative_stock_source", False):
            add(row, "High", "Data-quality exception", "Negative sales or stock was found and clipped to zero for decision logic.", "Correct the source transaction or return posting before execution.")

    alerts = pd.DataFrame(rows)
    if alerts.empty:
        return pd.DataFrame(columns=[
            "severity", "alert_type", "store_id", "article_code", "message", "recommended_action", "status"
        ])
    severity_order = pd.Categorical(alerts["severity"], categories=["Critical", "High", "Medium", "Low"], ordered=True)
    alerts = alerts.assign(_severity=severity_order).sort_values(["_severity", "estimated_value_at_risk"], ascending=[True, False]).drop(columns="_severity")
    alerts.insert(0, "alert_id", [f"ALT-{i:05d}" for i in range(1, len(alerts) + 1)])
    alerts["whatsapp_message"] = alerts.apply(
        lambda r: f"{r['severity']} | {r['alert_type']} | {r['article_code']} | {r['recommended_action']}", axis=1
    )
    return alerts.reset_index(drop=True)


def build_network_snapshot(network_df: pd.DataFrame, product_master: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.Timestamp]:
    data = network_df.copy()
    latest_week = pd.Timestamp(data["week_start"].max()).normalize()
    min_week = pd.Timestamp(data["week_start"].min()).normalize()
    available_weeks = max(1, int(((latest_week - min_week).days // 7) + 1))

    latest = data.sort_values("week_start").groupby(["store_id", "article_code", "size"], as_index=False).tail(1)
    latest = latest[[
        "store_id", "article_code", "size", "closing_stock", "current_zone", "cost_per_unit",
        *[c for c in ["launch_date", "first_receipt_date", "last_receipt_date"] if c in latest.columns],
    ]].copy()

    def window_sales(weeks: int, name: str) -> pd.DataFrame:
        start = latest_week - pd.Timedelta(weeks=weeks - 1)
        subset = data[data["week_start"] >= start]
        grouped = subset.groupby(["store_id", "article_code", "size"], as_index=False).agg(
            **{
                f"sales_{name}": ("sales_units", "sum"),
                f"sales_value_{name}": ("sales_value", "sum"),
            }
        )
        grouped[f"observed_weeks_{name}"] = min(weeks, available_weeks)
        return grouped

    snapshot = latest
    for weeks, name in [(4, "4w"), (8, "8w"), (13, "13w")]:
        snapshot = snapshot.merge(window_sales(weeks, name), on=["store_id", "article_code", "size"], how="left")
    for col in ["sales_4w", "sales_8w", "sales_13w", "sales_value_4w", "sales_value_8w", "sales_value_13w"]:
        snapshot[col] = pd.to_numeric(snapshot[col], errors="coerce").fillna(0)
    snapshot["avg_weekly_sales"] = np.maximum(snapshot["sales_4w"] / snapshot["observed_weeks_4w"], snapshot["sales_8w"] / snapshot["observed_weeks_8w"] * 0.80)
    snapshot["weeks_cover"] = np.where(snapshot["avg_weekly_sales"] > 0, snapshot["closing_stock"] / snapshot["avg_weekly_sales"], np.where(snapshot["closing_stock"] > 0, 999.0, 0.0))
    snapshot["avg_selling_price"] = np.where(snapshot["sales_8w"] > 0, snapshot["sales_value_8w"] / snapshot["sales_8w"], 0)

    last_sale = (
        data[data["sales_units"] > 0]
        .groupby(["store_id", "article_code", "size"], as_index=False)["week_start"].max()
        .rename(columns={"week_start": "last_sale_week"})
    )
    snapshot = snapshot.merge(last_sale, on=["store_id", "article_code", "size"], how="left")
    snapshot["weeks_since_sale"] = ((latest_week - snapshot["last_sale_week"]).dt.days / 7).fillna(available_weeks).clip(lower=0)

    if product_master is not None and not product_master.empty:
        meta_cols = [
            "article_code", "brand", "display_gender", "display_category", "color", "avg_selling_price",
            "lifecycle_type",
        ]
        meta = product_master[[c for c in meta_cols if c in product_master.columns]].drop_duplicates("article_code")
        snapshot = snapshot.merge(meta, on="article_code", how="left", suffixes=("", "_master"))
        if "avg_selling_price_master" in snapshot.columns:
            snapshot["avg_selling_price"] = np.where(snapshot["avg_selling_price"] > 0, snapshot["avg_selling_price"], snapshot["avg_selling_price_master"].fillna(0))
    for col in ["brand", "display_gender", "display_category", "color"]:
        if col not in snapshot.columns:
            snapshot[col] = ""
        snapshot[col] = snapshot[col].fillna("")

    snapshot["velocity_percentile_store"] = snapshot.groupby(
        ["store_id", "brand", "display_category"], dropna=False
    )["avg_weekly_sales"].transform(_percentile_rank)
    snapshot["velocity_percentile_network"] = snapshot.groupby(
        ["article_code", "size"], dropna=False
    )["avg_weekly_sales"].transform(_percentile_rank)
    return snapshot.reset_index(drop=True), latest_week


def recommend_store_transfers(
    network_df: pd.DataFrame,
    product_master: pd.DataFrame | None = None,
    distances: pd.DataFrame | None = None,
    receiver_target_woc: float = 6.0,
    sender_protect_woc: float = 4.0,
    fixed_transfer_cost: float = 2.0,
    handling_cost_per_unit: float = 0.5,
    cost_per_km: float = 0.05,
    gross_margin_rate: float = 0.45,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    snapshot, latest_week = build_network_snapshot(network_df, product_master)
    snapshot["receiver_need"] = np.ceil(
        np.maximum(0, receiver_target_woc * snapshot["avg_weekly_sales"] - snapshot["closing_stock"])
    ).astype(int)
    protected_stock = np.maximum(1, np.ceil(sender_protect_woc * snapshot["avg_weekly_sales"])).astype(int)
    snapshot["sender_surplus"] = np.maximum(0, snapshot["closing_stock"].astype(int) - protected_stock).astype(int)
    snapshot["receiver_urgent"] = (
        (snapshot["receiver_need"] > 0)
        & (snapshot["avg_weekly_sales"] > 0)
        & ((snapshot["weeks_cover"] < 4) | (snapshot["closing_stock"] <= 0))
    )
    snapshot["sender_excess"] = (
        (snapshot["sender_surplus"] > 0)
        & ((snapshot["weeks_cover"] > 12) | (snapshot["avg_weekly_sales"] <= 0.05))
    )

    distance_map: dict[tuple[str, str], float] = {}
    if distances is not None and not distances.empty:
        distance_map.update({
            (str(r.from_store), str(r.to_store)): float(r.distance_km)
            for r in distances.itertuples(index=False)
        })

    transfer_rows: list[dict[str, object]] = []
    for (article, size), group in snapshot.groupby(["article_code", "size"], dropna=False):
        receivers = group[group["receiver_urgent"]].sort_values(
            ["receiver_need", "velocity_percentile_network", "avg_weekly_sales"], ascending=False
        ).copy()
        senders = group[group["sender_excess"]].sort_values(
            ["sender_surplus", "weeks_cover"], ascending=False
        ).copy()
        if receivers.empty or senders.empty:
            continue

        sender_remaining = {idx: int(row["sender_surplus"]) for idx, row in senders.iterrows()}
        for receiver_idx, receiver in receivers.iterrows():
            need = int(receiver["receiver_need"])
            if need <= 0:
                continue
            for sender_idx, sender in senders.iterrows():
                if sender["store_id"] == receiver["store_id"]:
                    continue
                available = sender_remaining.get(sender_idx, 0)
                if available <= 0:
                    continue
                qty = min(need, available)
                if qty <= 0:
                    continue
                distance = distance_map.get((str(sender["store_id"]), str(receiver["store_id"])), np.nan)
                logistics_cost = fixed_transfer_cost + handling_cost_per_unit * qty
                if pd.notna(distance):
                    logistics_cost += cost_per_km * float(distance)
                selling_price = float(receiver.get("avg_selling_price", 0) or sender.get("avg_selling_price", 0) or 0)
                revenue_opportunity = qty * selling_price
                margin_opportunity = revenue_opportunity * gross_margin_rate
                net_opportunity = margin_opportunity - logistics_cost
                urgency = min(1.0, float(receiver["receiver_need"]) / max(1.0, receiver_target_woc * receiver["avg_weekly_sales"]))
                curve_bonus = 1.0 if receiver["closing_stock"] <= 0 else 0.5
                sender_excess_score = min(1.0, float(sender["weeks_cover"]) / 24.0) if sender["weeks_cover"] < 999 else 1.0
                transfer_score = 100 * (
                    0.35 * urgency
                    + 0.30 * float(receiver["velocity_percentile_network"])
                    + 0.20 * curve_bonus
                    + 0.15 * sender_excess_score
                )
                transfer_rows.append({
                    "week_start": latest_week.date(),
                    "article_code": article,
                    "size": size,
                    "brand": receiver.get("brand", ""),
                    "category": receiver.get("display_category", ""),
                    "from_store": sender["store_id"],
                    "to_store": receiver["store_id"],
                    "transfer_qty": qty,
                    "sender_stock_before": int(sender["closing_stock"]),
                    "sender_woc_before": round(float(sender["weeks_cover"]), 1),
                    "receiver_stock_before": int(receiver["closing_stock"]),
                    "receiver_woc_before": round(float(receiver["weeks_cover"]), 1),
                    "receiver_avg_weekly_sales": round(float(receiver["avg_weekly_sales"]), 2),
                    "distance_km": None if pd.isna(distance) else round(float(distance), 1),
                    "estimated_revenue_opportunity": round(revenue_opportunity, 2),
                    "estimated_margin_opportunity": round(margin_opportunity, 2),
                    "estimated_logistics_cost": round(logistics_cost, 2),
                    "estimated_net_opportunity": round(net_opportunity, 2),
                    "transfer_score": round(transfer_score, 1),
                    "recommendation": "Recommend" if net_opportunity > 0 or selling_price <= 0 else "Commercial review",
                    "reason": "Receiver understock plus sender excess for the same article and size.",
                })
                sender_remaining[sender_idx] = available - qty
                need -= qty
                if need <= 0:
                    break

    transfers = pd.DataFrame(transfer_rows)
    if not transfers.empty:
        transfers = transfers.sort_values(["recommendation", "transfer_score", "estimated_net_opportunity"], ascending=[True, False, False]).reset_index(drop=True)
    return transfers, snapshot, latest_week


def generate_network_alerts(snapshot: pd.DataFrame, transfers: pd.DataFrame) -> pd.DataFrame:
    alerts: list[dict[str, object]] = []
    for _, row in snapshot.iterrows():
        if row["closing_stock"] <= 0 and row["avg_weekly_sales"] > 0:
            alerts.append({
                "severity": "Critical",
                "alert_type": "Store-size OOS",
                "store_id": row["store_id"],
                "article_code": row["article_code"],
                "size": row["size"],
                "message": "A selling footwear size is out of stock.",
                "recommended_action": "Transfer in or replenish this exact size.",
            })
        elif row["weeks_cover"] < 2 and row["avg_weekly_sales"] > 0:
            alerts.append({
                "severity": "High",
                "alert_type": "Understock",
                "store_id": row["store_id"],
                "article_code": row["article_code"],
                "size": row["size"],
                "message": f"Only {row['weeks_cover']:.1f} weeks of cover remain.",
                "recommended_action": "Transfer in before the size sells out.",
            })
        if row["weeks_since_sale"] >= 8 and row["closing_stock"] > 0:
            alerts.append({
                "severity": "High",
                "alert_type": "No sale for 8+ weeks",
                "store_id": row["store_id"],
                "article_code": row["article_code"],
                "size": row["size"],
                "message": f"No sale recorded for {row['weeks_since_sale']:.0f} weeks.",
                "recommended_action": "Transfer out, consolidate size curve or markdown review.",
            })
    if transfers is not None and not transfers.empty:
        for _, row in transfers[transfers["recommendation"] == "Recommend"].iterrows():
            alerts.append({
                "severity": "High",
                "alert_type": "Store transfer opportunity",
                "store_id": row["from_store"],
                "article_code": row["article_code"],
                "size": row["size"],
                "message": f"Move {row['transfer_qty']} unit(s) from {row['from_store']} to {row['to_store']}.",
                "recommended_action": f"Create transfer order. Estimated net opportunity {row['estimated_net_opportunity']:.2f}.",
            })
    result = pd.DataFrame(alerts)
    if result.empty:
        return pd.DataFrame(columns=["severity", "alert_type", "store_id", "article_code", "size", "message", "recommended_action"])
    severity = pd.Categorical(result["severity"], categories=["Critical", "High", "Medium", "Low"], ordered=True)
    result = result.assign(_severity=severity).sort_values("_severity").drop(columns="_severity").reset_index(drop=True)
    result.insert(0, "alert_id", [f"NET-{i:05d}" for i in range(1, len(result) + 1)])
    return result


def export_inventory_intelligence_xlsx(
    health: pd.DataFrame,
    actions: pd.DataFrame,
    alerts: pd.DataFrame,
    transfers: pd.DataFrame | None = None,
    network_snapshot: pd.DataFrame | None = None,
    sku_health: pd.DataFrame | None = None,
) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        health.to_excel(writer, sheet_name="Article Health", index=False)
        if sku_health is not None and not sku_health.empty:
            sku_health.to_excel(writer, sheet_name="Size SKU Health", index=False)
        actions.to_excel(writer, sheet_name="Within Store Actions", index=False)
        alerts.to_excel(writer, sheet_name="Alerts", index=False)
        if transfers is not None and not transfers.empty:
            transfers.to_excel(writer, sheet_name="Store Transfers", index=False)
        if network_snapshot is not None and not network_snapshot.empty:
            network_snapshot.to_excel(writer, sheet_name="Network Snapshot", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = cell.font.copy(bold=True, color="FFFFFF")
                cell.fill = cell.fill.copy(fill_type="solid", fgColor="1F4E78")
            for column_cells in sheet.columns:
                max_len = max(len(str(cell.value or "")) for cell in list(column_cells)[:500])
                sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_len + 2, 10), 40)
    output.seek(0)
    return output.getvalue()


def build_intelligence_summary(health: pd.DataFrame, alerts: pd.DataFrame, transfers: pd.DataFrame | None = None) -> IntelligenceSummary:
    return IntelligenceSummary(
        articles=int(health["article_code"].nunique()),
        fast_movers=int((health["movement_status"] == "Fast mover").sum()),
        slow_movers=int((health["movement_status"] == "Slow mover").sum()),
        non_movers=int((health["movement_status"] == "Non-mover").sum()),
        dead_stock_or_risk=int(health["dead_stock_status"].astype(str).str.contains("Dead stock|Dead-stock risk", regex=True).sum()),
        broken_size_curves=int((health["size_curve_status"] == "Broken size curve").sum()),
        critical_alerts=int((alerts.get("severity", pd.Series(dtype=str)) == "Critical").sum()),
        transfer_candidates=int(len(transfers)) if transfers is not None else int(health["transfer_out_candidate"].sum()),
        age_available=bool(health["age_bucket"].ne("Age unavailable").any()),
        data_basis=str(health["data_basis"].iloc[0]) if not health.empty else CURRENT_DATA_BASIS,
    )


def build_size_sku_health(size_df: pd.DataFrame, article_health: pd.DataFrame) -> pd.DataFrame:
    """Classify each footwear article-size SKU in the current cumulative workbook."""
    working = size_df.copy()
    for col in ["article_code", "brand", "display_gender", "display_category", "color", "size"]:
        if col not in working.columns:
            working[col] = ""
        working[col] = working[col].fillna("").astype(str).str.strip()
    for col in ["sales_qty", "sales_value", "stock_qty"]:
        if col not in working.columns:
            working[col] = 0
        working[col] = pd.to_numeric(working[col], errors="coerce").fillna(0)
    working["negative_sales_source"] = working["sales_qty"] < 0
    working["negative_stock_source"] = working["stock_qty"] < 0
    working["sales_qty"] = working["sales_qty"].clip(lower=0)
    working["stock_qty"] = working["stock_qty"].clip(lower=0)

    static_cols = ["brand", "display_gender", "display_category", "color"]
    sku = working.groupby(["article_code", "size"], as_index=False).agg(
        **{c: (c, "first") for c in static_cols},
        sales_qty=("sales_qty", "sum"),
        sales_value=("sales_value", "sum"),
        stock_qty=("stock_qty", "sum"),
        negative_sales_source=("negative_sales_source", "max"),
        negative_stock_source=("negative_stock_source", "max"),
    )
    sku["sku_id"] = sku["article_code"] + "-" + sku["size"]
    sku["weekly_sales_units"] = sku["sales_qty"] / (6.5 * 52 / 12)
    sku["avg_selling_price"] = np.where(sku["sales_qty"] > 0, sku["sales_value"] / sku["sales_qty"], 0)
    sku["weeks_cover"] = np.where(
        sku["weekly_sales_units"] > 0,
        sku["stock_qty"] / sku["weekly_sales_units"],
        np.where(sku["stock_qty"] > 0, 999.0, 0.0),
    )
    sku["sell_through_proxy"] = np.where(
        sku["sales_qty"] + sku["stock_qty"] > 0,
        sku["sales_qty"] / (sku["sales_qty"] + sku["stock_qty"]),
        0,
    )
    core_table = _core_size_table(working)
    sku = sku.merge(core_table, on=["brand", "display_gender", "display_category", "size"], how="left")
    sku["core_size"] = sku["core_size"].fillna(False)
    sku["size_weight"] = sku["size_weight"].fillna(0)
    sku["size_role"] = np.where(sku["core_size"], "Core size", "Tail size")
    sku["velocity_percentile"] = sku.groupby(
        ["brand", "display_gender", "display_category", "size"], dropna=False
    )["weekly_sales_units"].transform(_percentile_rank)

    meta_cols = [
        "article_code", "lifecycle_type", "age_days", "age_bucket", "movement_status",
        "size_curve_status", "target_zone", "dead_stock_status", "classification_confidence",
    ]
    meta = article_health[[c for c in meta_cols if c in article_health.columns]].drop_duplicates("article_code")
    sku = sku.merge(meta, on="article_code", how="left", suffixes=("", "_article"))

    def movement(row: pd.Series) -> str:
        if row["stock_qty"] <= 0 and row["sales_qty"] > 0:
            return "Sold out / OOS"
        if row["stock_qty"] <= 0 and row["sales_qty"] <= 0:
            return "Inactive. No stock"
        if row["sales_qty"] <= 0:
            return "Non-mover"
        if row["velocity_percentile"] >= 0.80 and (row["sell_through_proxy"] >= 0.55 or row["weeks_cover"] <= 12):
            return "Fast mover"
        if row["velocity_percentile"] >= 0.40:
            return "Medium mover"
        return "Slow mover"

    sku["sku_movement_status"] = sku.apply(movement, axis=1)

    def cover(row: pd.Series) -> str:
        if row["stock_qty"] <= 0:
            return "Out of stock"
        if row["weekly_sales_units"] <= 0:
            return "No-sale stock"
        if row["weeks_cover"] < 2:
            return "Critical understock"
        if row["weeks_cover"] < 4:
            return "Understock"
        if row["weeks_cover"] <= 12:
            return "Healthy cover"
        if row["weeks_cover"] <= 24:
            return "Excess cover"
        return "Severe excess cover"

    sku["cover_status"] = sku.apply(cover, axis=1)

    def dead(row: pd.Series) -> str:
        lifecycle = row.get("lifecycle_type", "Fashion / Seasonal")
        limits = LIFECYCLE_THRESHOLDS.get(lifecycle, LIFECYCLE_THRESHOLDS["Fashion / Seasonal"])
        if pd.notna(row.get("age_days")) and row["stock_qty"] > 0 and row["sales_qty"] <= 0 and row["age_days"] >= limits["dead"]:
            return "Dead stock"
        if row["stock_qty"] > 0 and row["sales_qty"] <= 0 and pd.isna(row.get("age_days")):
            return "Dead-stock risk. Age and recent sales unavailable"
        return "Not dead stock" if pd.notna(row.get("age_days")) else "Age validation required"

    sku["sku_dead_stock_status"] = sku.apply(dead, axis=1)

    def action(row: pd.Series) -> str:
        if row["sku_dead_stock_status"] == "Dead stock":
            return "Remove and final-clearance review"
        if row["sku_movement_status"] == "Sold out / OOS" and row["size_role"] == "Core size":
            return "Urgent transfer in or replenishment"
        if row["sku_movement_status"] == "Sold out / OOS":
            return "Transfer in if article demand remains active"
        if row["sku_movement_status"] == "Non-mover" and row["stock_qty"] > 0:
            return "Transfer out or consolidate size curve"
        if row["sku_movement_status"] == "Fast mover" and row["weeks_cover"] < 4:
            return "Protect availability. Transfer in"
        if row["sku_movement_status"] == "Slow mover" and row["weeks_cover"] > 24:
            return "Transfer out before markdown"
        return "Retain and monitor"

    sku["sku_action"] = sku.apply(action, axis=1)
    sku["data_basis"] = CURRENT_DATA_BASIS
    return sku.sort_values(
        ["brand", "display_category", "article_code", "core_size", "size"],
        ascending=[True, True, True, False, True],
    ).reset_index(drop=True)


def generate_size_sku_alerts(sku_health: pd.DataFrame, store_name: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in sku_health.iterrows():
        severity = None
        alert_type = None
        message = None
        action = row.get("sku_action", "Review")
        if row["sku_movement_status"] == "Sold out / OOS" and row["size_role"] == "Core size":
            severity = "Critical"
            alert_type = "Core-size OOS"
            message = "A core footwear size with historical demand is out of stock."
        elif row["sku_dead_stock_status"] == "Dead stock":
            severity = "Critical"
            alert_type = "Dead size-SKU"
            message = "An aged size-SKU has stock but no sales."
        elif str(row["sku_dead_stock_status"]).startswith("Dead-stock risk"):
            severity = "High"
            alert_type = "No-sale size-SKU risk"
            message = "This size has stock but no cumulative sales. Verify age and last-sale date."
        elif row["sku_movement_status"] == "Fast mover" and row["weeks_cover"] < 2:
            severity = "High"
            alert_type = "Fast size understock"
            message = "A fast-moving size has less than two weeks of cover."
        elif row["sku_movement_status"] == "Slow mover" and row["weeks_cover"] > 24:
            severity = "Medium"
            alert_type = "Slow size excess"
            message = "A slow size has more than 24 weeks of cover."
        if severity:
            rows.append({
                "severity": severity,
                "alert_type": alert_type,
                "store_id": store_name,
                "article_code": row["article_code"],
                "size": row["size"],
                "sku_id": row["sku_id"],
                "brand": row["brand"],
                "category": row["display_category"],
                "size_role": row["size_role"],
                "movement_status": row["sku_movement_status"],
                "stock_qty": row["stock_qty"],
                "weeks_cover": row["weeks_cover"],
                "age_bucket": row.get("age_bucket", "Age unavailable"),
                "dead_stock_status": row["sku_dead_stock_status"],
                "message": message,
                "recommended_action": action,
                "confidence": row.get("classification_confidence", "Medium"),
                "data_basis": CURRENT_DATA_BASIS,
                "status": "Open",
            })
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=["severity", "alert_type", "store_id", "article_code", "size", "message", "recommended_action"])
    severity_order = pd.Categorical(result["severity"], categories=["Critical", "High", "Medium", "Low"], ordered=True)
    result = result.assign(_severity=severity_order).sort_values(["_severity", "weeks_cover"], ascending=[True, True]).drop(columns="_severity")
    result.insert(0, "alert_id", [f"SKU-{i:05d}" for i in range(1, len(result) + 1)])
    result["whatsapp_message"] = result.apply(
        lambda r: f"{r['severity']} | {r['alert_type']} | {r['sku_id']} | {r['recommended_action']}", axis=1
    )
    return result.reset_index(drop=True)
