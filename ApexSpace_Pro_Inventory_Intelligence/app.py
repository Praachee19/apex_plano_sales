from __future__ import annotations

import sys
import textwrap
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from apex_engine import (
    SALES_PERIOD_WEEKS,
    allocate_planogram,
    all_planogram_templates,
    build_article_master,
    export_execution_xlsx,
    generate_synthetic_client_data,
    load_source,
    make_execution_legend,
    next_review_date,
    score_articles,
)
from visual_renderer import (
    build_product_image_map,
    image_to_pdf_bytes,
    image_to_png_bytes,
    render_visual_planogram,
)

from inventory_intelligence import (
    build_intelligence_summary,
    build_inventory_health,
    build_size_sku_health,
    build_within_store_actions,
    export_inventory_intelligence_xlsx,
    generate_network_alerts,
    generate_single_store_alerts,
    generate_size_sku_alerts,
    load_current_display,
    load_network_data,
    load_store_distances,
    recommend_store_transfers,
)

st.set_page_config(page_title="ApexSpace Pro", page_icon="👟", layout="wide")

ROOT = Path(__file__).resolve().parent
EXPECTED_VENV = (ROOT / ".venv").resolve()
CURRENT_PREFIX = Path(sys.prefix).resolve()

# Prevent Windows from silently using the global or an outer-folder environment.
if CURRENT_PREFIX != EXPECTED_VENV:
    st.error("ApexSpace Pro is running with the wrong Python environment.")
    st.code(f"Current Python: {sys.executable}\nCurrent environment: {CURRENT_PREFIX}\nRequired environment: {EXPECTED_VENV}")
    st.info("Close this server and double-click RESET_AND_RUN.bat inside this exact project folder.")
    st.stop()

st.markdown(
    """
    <style>
    .main .block-container {padding-top: 1.2rem; max-width: 1550px;}
    section[data-testid="stSidebar"] {background:#f4f5f7;}
    .hero-title {font-size:40px; font-weight:800; color:#E65A00; margin-bottom:0;}
    .hero-sub {color:#6f737b; font-size:14px; margin-bottom:14px;}
    .source-pill {display:inline-block; padding:5px 10px; border-radius:14px; background:#E8F1FB; color:#1E5B91; font-weight:700; font-size:12px;}
    .section-title {font-size:28px; font-weight:800; margin:10px 0 12px 0;}
    .warning-box {background:#FFF8E6; border-left:5px solid #E6A100; padding:12px; border-radius:8px;}
    .good-box {background:#EEF8F1; border-left:5px solid #2E7D32; padding:12px; border-radius:8px;}
    .info-box {background:#EEF5FC; border-left:5px solid #2F6DA1; padding:12px; border-radius:8px;}
    </style>
    """,
    unsafe_allow_html=True,
)

DEFAULT_FILE = ROOT / "data" / "Space Pro Sample Data File.xlsx"


@st.cache_data(show_spinner=False)
def cached_load_path(path: str):
    return load_source(path)


@st.cache_data(show_spinner=False)
def cached_load_upload(file_bytes: bytes, filename: str):
    return load_source(BytesIO(file_bytes), filename=filename)


@st.cache_data(show_spinner=False)
def cached_article_master(size_df: pd.DataFrame) -> pd.DataFrame:
    return build_article_master(size_df)


@st.cache_data(show_spinner=False)
def cached_score(article_df: pd.DataFrame) -> pd.DataFrame:
    return score_articles(article_df)


def slugify(value: str) -> str:
    return "_".join(str(value).strip().lower().replace("/", " ").replace(".", " ").split())


def filter_article_master(
    master: pd.DataFrame,
    brand_name: str,
    gender_name: str = "All",
    category_name: str = "All",
) -> pd.DataFrame:
    result = master[master["brand"] == brand_name].copy()
    if gender_name != "All":
        result = result[result["display_gender"] == gender_name]
    if category_name != "All":
        result = result[result["display_category"] == category_name]
    return result


def build_all_planograms_zip(
    master: pd.DataFrame,
    fixture_brand: str,
    store: str,
    product_images: dict[str, bytes],
    include_accessory_products: bool,
    minimum_stock: int,
    gender_name: str,
    category_name: str,
    show_article_codes: bool,
    show_commercial_scores: bool,
    show_zone_outlines: bool,
) -> bytes:
    """Generate every included wall and fixture planogram in one ZIP."""
    output = BytesIO()
    manifest_rows: list[dict[str, object]] = []
    templates_for_export = all_planogram_templates(fixture_brand, family="All included")

    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for order, (template_name, export_template) in enumerate(templates_for_export.items(), start=1):
            target_brand = export_template["brand"] if export_template["kind"] == "wall" else fixture_brand
            export_gender = "All" if export_template["kind"] == "wall" else gender_name
            export_category = "All" if export_template["kind"] == "wall" else category_name
            source_rows = filter_article_master(master, target_brand, export_gender, export_category)

            folder = f"{order:02d}_{slugify(template_name)}"
            if source_rows.empty:
                archive.writestr(
                    f"{folder}/NOT_GENERATED.txt",
                    f"No product data was available for brand {target_brand}.\n",
                )
                manifest_rows.append({
                    "order": order, "template": template_name, "kind": export_template["kind"],
                    "brand": target_brand, "capacity": export_template["capacity"],
                    "selected_articles": 0, "status": "No matching product data",
                })
                continue

            export_scored = score_articles(source_rows)
            export_placements, _ = allocate_planogram(
                export_scored,
                export_template,
                include_accessories=include_accessory_products,
                min_stock=int(minimum_stock),
            )
            export_legend = make_execution_legend(export_placements)
            export_image, export_stats = render_visual_planogram(
                export_placements,
                export_template,
                target_brand,
                store,
                product_images,
                show_article_codes=show_article_codes,
                show_scores=show_commercial_scores,
                show_zone_outlines=show_zone_outlines,
            )
            archive.writestr(f"{folder}/{slugify(template_name)}.png", image_to_png_bytes(export_image))
            archive.writestr(f"{folder}/{slugify(template_name)}.pdf", image_to_pdf_bytes(export_image))
            archive.writestr(
                f"{folder}/{slugify(template_name)}_article_slot_mapping.csv",
                export_legend.to_csv(index=False).encode("utf-8"),
            )
            manifest_rows.append({
                "order": order, "template": template_name, "kind": export_template["kind"],
                "brand": target_brand, "capacity": export_template["capacity"],
                "selected_articles": export_stats["rendered"], "status": "Generated",
            })

        archive.writestr("00_manifest.csv", pd.DataFrame(manifest_rows).to_csv(index=False).encode("utf-8"))
        archive.writestr(
            "README.txt",
            (
                "ApexSpace Pro. All Planograms Export\n"
                "Included: Apex, Venturini, Nino Rossi, Moochie and Twinkler brand walls, "
                "plus Fixture 1, Fixture 2 and Fixture 3.\n"
                "Brand walls use their fixed approved brand identity. Generic fixtures use the brand selected in the app.\n"
            ),
        )
    return output.getvalue()


with st.sidebar:
    st.markdown("## ApexSpace Pro")
    st.caption("AI-assisted footwear space allocation and VM execution")
    st.divider()

    data_mode = st.radio("Data source", ["Apex client workbook", "Upload workbook or CSV", "Synthetic demo"], index=0)
    uploaded_data = None
    if data_mode == "Upload workbook or CSV":
        uploaded_data = st.file_uploader("Upload Apex data", type=["xlsx", "xls", "csv"], key="data_upload")

try:
    if data_mode == "Apex client workbook":
        if not DEFAULT_FILE.exists():
            st.error("The packaged Apex workbook is missing. Upload the workbook from the sidebar.")
            st.stop()
        size_df, source_summary = cached_load_path(str(DEFAULT_FILE))
    elif data_mode == "Upload workbook or CSV":
        if uploaded_data is None:
            st.info("Upload the Apex workbook or CSV to continue.")
            st.stop()
        size_df, source_summary = cached_load_upload(uploaded_data.getvalue(), uploaded_data.name)
    else:
        size_df, source_summary = generate_synthetic_client_data()
except Exception as exc:
    st.error(f"The data could not be loaded: {exc}")
    st.stop()

article_master = cached_article_master(size_df)
brands = sorted([b for b in article_master["brand"].dropna().astype(str).unique() if b])
if not brands:
    st.error("No brands were found in the source data.")
    st.stop()

default_brand_index = brands.index("APEX") if "APEX" in brands else 0

with st.sidebar:
    st.markdown("### Pilot controls")
    store_name = st.text_input("Store", "Adarsha Mirpur-1")

    planogram_family = st.selectbox(
        "Planogram group",
        ["All included", "Brand walls", "Fixtures"],
        index=0,
        help="All eight uploaded visual planograms are included in this app.",
    )
    template_catalogue = all_planogram_templates("APEX", family=planogram_family)
    template_name = st.selectbox("Visual planogram template", list(template_catalogue.keys()), index=0)
    template_preview = template_catalogue[template_name]

    if template_preview["kind"] == "wall":
        required_brand = str(template_preview["brand"]).upper()
        if required_brand in brands:
            brand = required_brand
        else:
            brand = brands[default_brand_index]
            st.warning(f"The template requires {required_brand}, but that brand is not present in the data.")
        st.text_input("Product brand. Fixed by wall template", value=brand, disabled=True)
    else:
        brand = st.selectbox("Product brand for fixture", brands, index=default_brand_index)

    # Rebuild the selected template so generic fixtures carry the chosen product brand.
    templates = all_planogram_templates(brand, family=planogram_family)
    template = templates[template_name]

    brand_rows = article_master[article_master["brand"] == brand]
    gender_options = ["All"] + sorted(brand_rows["display_gender"].dropna().astype(str).unique().tolist())
    category_options = ["All"] + sorted(brand_rows["display_category"].dropna().astype(str).unique().tolist())
    gender_filter = st.selectbox("Gender", gender_options)
    category_filter = st.selectbox("Display category", category_options)

    include_accessories = st.checkbox("Include accessories", value=True)
    min_stock = st.number_input("Minimum article stock", min_value=1, max_value=50, value=1, step=1)
    review_cadence = st.selectbox("Planogram review cadence", ["Weekly", "Fortnightly", "Monthly"], index=0)
    lifecycle_mode = st.selectbox(
        "Inventory lifecycle rule",
        ["Auto by category", "Fashion / Seasonal", "Core / Replenishment"],
        index=0,
        help="Auto treats School and Formal footwear as core. Other categories use fashion-seasonal aging thresholds unless a lifecycle field is supplied.",
    )
    st.caption("Included: 5 brand walls + 3 floor fixtures")

st.markdown('<div class="hero-title">ApexSpace Pro</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="hero-sub">Apex footwear space allocation and visual execution plan. {store_name}.</div>',
    unsafe_allow_html=True,
)
st.markdown(f'<span class="source-pill">{source_summary.source_name}</span>', unsafe_allow_html=True)

filtered = filter_article_master(article_master, brand, gender_filter, category_filter)
if filtered.empty:
    st.warning("No articles match the current filters.")
    st.stop()

scored = cached_score(filtered)
placements, allocation = allocate_planogram(scored, template, include_accessories=include_accessories, min_stock=int(min_stock))
legend = make_execution_legend(placements)
product_placements = placements[placements["position_type"] == "Product"].copy()

selected_codes = set(product_placements.get("article_code", pd.Series(dtype=str)).astype(str))
selected_sales = scored[scored["article_code"].astype(str).isin(selected_codes)]["sales_value"].sum()
total_sales = scored["sales_value"].sum()
selected_share = selected_sales / total_sales if total_sales else 0

kpis = {
    "articles": int(scored["article_code"].nunique()),
    "selected": int(len(product_placements)),
    "capacity": int(template["capacity"]),
    "sales_qty": int(scored["sales_qty"].sum()),
    "stock_qty": int(scored["stock_qty"].sum()),
    "size_complete": float(scored["size_set_completeness"].mean()),
    "selected_sales_share": float(selected_share),
    "not_selected": int((~allocation["selected_for_planogram"] & (allocation["stock_qty"] > 0)).sum()),
}

inventory_health_all = build_inventory_health(
    size_df, article_master, default_lifecycle=lifecycle_mode
)
inventory_health = filter_article_master(
    inventory_health_all, brand, gender_filter, category_filter
)

sku_health_all = build_size_sku_health(size_df, inventory_health_all)
sku_health = sku_health_all[sku_health_all["brand"] == brand].copy()
if gender_filter != "All":
    sku_health = sku_health[sku_health["display_gender"] == gender_filter]
if category_filter != "All":
    sku_health = sku_health[sku_health["display_category"] == category_filter]

(tab_dashboard, tab_xai, tab_alloc, tab_inventory, tab_planogram, tab_data, tab_schedule) = st.tabs(
    ["Dashboard", "Explainable AI", "Allocation", "Inventory Intelligence", "Visual Planogram", "Data", "Schedule"]
)

with tab_dashboard:
    st.markdown('<div class="section-title">Performance and space readiness</div>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Unique styles available", f"{kpis['articles']:,}")
    c2.metric("Display options selected", f"{kpis['selected']} / {kpis['capacity']}")
    c3.metric("6.5-month sales units", f"{kpis['sales_qty']:,}")
    c4.metric("Stock units", f"{kpis['stock_qty']:,}")
    c5.metric("Average size-set completeness", f"{kpis['size_complete']:.0%}")

    st.caption(
        f"Selected articles represent {kpis['selected_sales_share']:.1%} of sales value within the current filter. "
        "This is a concentration measure, not a validated revenue-uplift forecast."
    )

    col1, col2 = st.columns(2)
    with col1:
        chart = scored.groupby("display_category", as_index=False).agg(sales_value=("sales_value", "sum")).sort_values("sales_value", ascending=False)
        st.markdown("**Sales value by display category**")
        sales_view = chart.rename(columns={"display_category": "Category", "sales_value": "Sales value"}).copy()
        sales_max = float(sales_view["Sales value"].max()) if not sales_view.empty else 1.0
        st.dataframe(
            sales_view,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Sales value": st.column_config.ProgressColumn(
                    "Sales value", min_value=0.0, max_value=max(sales_max, 1.0), format="%,.0f"
                )
            },
        )
    with col2:
        size_chart = scored.groupby("display_category", as_index=False).agg(size_set=("size_set_completeness", "mean")).sort_values("size_set", ascending=False)
        st.markdown("**Average size-set completeness**")
        size_view = size_chart.rename(columns={"display_category": "Category", "size_set": "Size-set completeness"})
        st.dataframe(
            size_view,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Size-set completeness": st.column_config.ProgressColumn(
                    "Size-set completeness", min_value=0.0, max_value=1.0, format="%.0f%%"
                )
            },
        )

    st.markdown(
        """
        <div class="good-box">
        The engine operates at article/style level, not size-row level. It scores each article using sales velocity,
        sales value, sales-to-stock movement, available inventory and size-set completeness. It then allocates the
        selected articles into the fixed VM template positions.
        </div>
        """,
        unsafe_allow_html=True,
    )

with tab_xai:
    st.markdown('<div class="section-title">Explainable article recommendations</div>', unsafe_allow_html=True)
    st.write("The workbook does not contain product cost or receipt age. GMROI and inventory age are therefore not calculated.")
    xai_cols = [
        "article_code", "brand", "display_gender", "display_category", "color", "sales_qty", "sales_value",
        "weekly_sales_units", "stock_qty", "weeks_cover", "size_set_completeness", "sell_through_proxy",
        "commercial_score", "recommended_zone", "recommended_action", "xai_reason",
    ]
    st.dataframe(scored[xai_cols], use_container_width=True, height=580)

with tab_alloc:
    st.markdown('<div class="section-title">Fixture allocation</div>', unsafe_allow_html=True)
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Selected", kpis["selected"])
    a2.metric("Eligible but not selected", kpis["not_selected"])
    a3.metric("Template capacity", kpis["capacity"])
    a4.metric("Next review", next_review_date(review_cadence).strftime("%d %b %Y"))

    st.caption(template["source_rule"])
    placement_cols = [
        "slot_id", "zone", "article_code", "display_gender", "display_category", "color", "sales_qty",
        "stock_qty", "size_set_completeness", "commercial_score", "recommended_action", "next_best_article",
        "next_best_score", "next_best_reason",
    ]
    st.dataframe(placements[[c for c in placement_cols if c in placements.columns]], use_container_width=True, height=560)

    execution_bytes = export_execution_xlsx(placements, allocation, source_summary, store_name, review_cadence)
    st.download_button(
        "Download store execution Excel",
        data=execution_bytes,
        file_name=f"{brand.lower().replace(' ', '_')}_apexspace_execution.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

with tab_inventory:
    st.markdown('<div class="section-title">Footwear inventory alerts and movement actions</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="info-box">
        The current Apex workbook supports article-level movement, size-curve and excess-stock alerts for one store.
        Verified inventory age and exact store-to-store transfers require dated weekly store-SKU-size data. The app does
        not label stock as confirmed dead stock when launch date and recent sales are missing. It labels it as a risk.
        </div>
        """,
        unsafe_allow_html=True,
    )

    input_c1, input_c2, input_c3 = st.columns(3)
    with input_c1:
        current_display_upload = st.file_uploader(
            "Optional current display mapping",
            type=["csv", "xlsx", "xls"],
            key="current_display_upload",
            help="Columns: store_id, article_code, current_zone, current_slot.",
        )
    with input_c2:
        network_upload = st.file_uploader(
            "Optional weekly multi-store sales and stock",
            type=["csv", "xlsx", "xls"],
            key="network_upload",
            help="Required: week_start, store_id, article_code, size, sales_units, closing_stock.",
        )
    with input_c3:
        distance_upload = st.file_uploader(
            "Optional store distance table",
            type=["csv", "xlsx", "xls"],
            key="distance_upload",
            help="Columns: from_store, to_store, distance_km.",
        )

    current_display_df = None
    if current_display_upload is not None:
        try:
            current_display_df = load_current_display(
                BytesIO(current_display_upload.getvalue()), current_display_upload.name
            )
        except Exception as exc:
            st.error(f"Current display mapping could not be loaded: {exc}")

    within_actions = build_within_store_actions(
        inventory_health, store_name, placements=placements, current_display=current_display_df
    )
    single_store_alerts = generate_single_store_alerts(within_actions, store_name)
    size_sku_alerts = generate_size_sku_alerts(sku_health, store_name)
    if not single_store_alerts.empty:
        single_store_alerts["decision_level"] = "Article / style"
    if not size_sku_alerts.empty:
        size_sku_alerts["decision_level"] = "Size SKU"
    all_store_alerts = pd.concat([single_store_alerts, size_sku_alerts], ignore_index=True, sort=False)

    network_df = None
    distance_df = None
    transfer_df = pd.DataFrame()
    network_snapshot = pd.DataFrame()
    network_alerts = pd.DataFrame()
    network_latest_week = None

    if network_upload is not None:
        try:
            network_df = load_network_data(BytesIO(network_upload.getvalue()), network_upload.name)
            if distance_upload is not None:
                distance_df = load_store_distances(BytesIO(distance_upload.getvalue()), distance_upload.name)
        except Exception as exc:
            st.error(f"Network input could not be loaded: {exc}")
            network_df = None

    intel_view, move_view, transfer_view, rules_view = st.tabs(
        ["Alerts and SKU health", "Move within store", "Store transfers", "Footwear logic"]
    )

    with intel_view:
        summary = build_intelligence_summary(inventory_health, all_store_alerts)
        q1, q2, q3, q4, q5, q6 = st.columns(6)
        q1.metric("Fast movers", f"{summary.fast_movers:,}")
        q2.metric("Slow movers", f"{summary.slow_movers:,}")
        q3.metric("Non-movers", f"{summary.non_movers:,}")
        q4.metric("Dead stock / risk", f"{summary.dead_stock_or_risk:,}")
        q5.metric("Broken size curves", f"{summary.broken_size_curves:,}")
        q6.metric("Critical alerts", f"{summary.critical_alerts:,}")

        if not summary.age_available:
            st.warning(
                "Inventory age is unavailable in the attached Apex workbook. Add launch_date or first_receipt_date "
                "to calculate New, Productive, Mature, Aging, High-risk aging and Dead-stock age review labels."
            )

        f1, f2, f3 = st.columns(3)
        with f1:
            severity_options = ["All"] + sorted(all_store_alerts.get("severity", pd.Series(dtype=str)).dropna().unique().tolist())
            severity_filter = st.selectbox("Alert severity", severity_options, key="alert_severity_filter")
        with f2:
            movement_options = ["All"] + sorted(inventory_health["movement_status"].dropna().unique().tolist())
            movement_filter = st.selectbox("Movement label", movement_options, key="movement_status_filter")
        with f3:
            alert_type_options = ["All"] + sorted(all_store_alerts.get("alert_type", pd.Series(dtype=str)).dropna().unique().tolist())
            alert_type_filter = st.selectbox("Alert type", alert_type_options, key="alert_type_filter")

        alert_view = all_store_alerts.copy()
        if severity_filter != "All" and not alert_view.empty:
            alert_view = alert_view[alert_view["severity"] == severity_filter]
        if alert_type_filter != "All" and not alert_view.empty:
            alert_view = alert_view[alert_view["alert_type"] == alert_type_filter]
        st.markdown("#### Open alerts")
        st.dataframe(alert_view, use_container_width=True, height=430)

        health_view = inventory_health.copy()
        if movement_filter != "All":
            health_view = health_view[health_view["movement_status"] == movement_filter]
        health_columns = [
            "article_code", "brand", "display_gender", "display_category", "color",
            "movement_status", "weekly_sales_units", "sales_qty", "stock_qty", "weeks_cover",
            "cover_status", "size_curve_status", "core_size_availability", "weighted_size_availability",
            "lifecycle_type", "age_days", "age_bucket", "dead_stock_status", "target_zone",
            "markdown_recommendation", "transfer_out_candidate", "classification_confidence",
        ]
        article_health_tab, size_sku_tab = st.tabs(["Article / style health", "Each size SKU"])
        with article_health_tab:
            st.markdown("#### Article and style health labels")
            st.dataframe(health_view[[c for c in health_columns if c in health_view.columns]], use_container_width=True, height=520)
        with size_sku_tab:
            st.markdown("#### Every article-size SKU")
            size_movement_options = ["All"] + sorted(sku_health["sku_movement_status"].dropna().unique().tolist())
            size_movement_filter = st.selectbox("Size-SKU movement label", size_movement_options, key="size_sku_movement_filter")
            sku_view = sku_health.copy()
            if size_movement_filter != "All":
                sku_view = sku_view[sku_view["sku_movement_status"] == size_movement_filter]
            sku_columns = [
                "sku_id", "article_code", "size", "size_role", "brand", "display_gender", "display_category",
                "sku_movement_status", "sales_qty", "weekly_sales_units", "stock_qty", "weeks_cover",
                "cover_status", "velocity_percentile", "age_days", "age_bucket", "sku_dead_stock_status",
                "sku_action", "target_zone", "classification_confidence",
            ]
            st.dataframe(sku_view[[c for c in sku_columns if c in sku_view.columns]], use_container_width=True, height=520)

        intelligence_bytes = export_inventory_intelligence_xlsx(
            inventory_health, within_actions, all_store_alerts, sku_health=sku_health
        )
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Download inventory alert pack",
                intelligence_bytes,
                f"{slugify(store_name)}_inventory_intelligence.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with d2:
            whatsapp_text = "\n".join(all_store_alerts.get("whatsapp_message", pd.Series(dtype=str)).dropna().head(150).tolist())
            st.download_button(
                "Download WhatsApp-ready alerts",
                whatsapp_text.encode("utf-8"),
                f"{slugify(store_name)}_alerts.txt",
                "text/plain",
                use_container_width=True,
            )

    with move_view:
        st.markdown("#### Recommended movement inside the store")
        st.write(
            "The target zone comes from sales velocity, stock cover, size-curve health and the generated planogram. "
            "A true from-to instruction needs the optional current display mapping."
        )
        move_filter = st.selectbox(
            "Show actions",
            ["All actions", "Moves only", "Remove and transfer review", "Prime promotions"],
            key="within_move_filter",
        )
        move_data = within_actions.copy()
        if move_filter == "Moves only":
            move_data = move_data[~move_data["within_store_action"].str.startswith("Retain")]
        elif move_filter == "Remove and transfer review":
            move_data = move_data[move_data["target_zone"] == "Remove"]
        elif move_filter == "Prime promotions":
            move_data = move_data[move_data["target_zone"] == "Prime"]
        move_cols = [
            "article_code", "brand", "display_gender", "display_category", "movement_status",
            "current_zone", "current_slot", "target_zone", "target_slot", "within_store_action",
            "move_priority", "stock_qty", "weeks_cover", "size_curve_status", "replacement_article",
            "replacement_reason", "markdown_recommendation",
        ]
        st.dataframe(move_data[[c for c in move_cols if c in move_data.columns]], use_container_width=True, height=590)

    with transfer_view:
        st.markdown("#### Size-level store-to-store transfers")
        if network_df is None:
            st.warning(
                "The attached workbook does not contain store_id, week_start or store-level size inventory. "
                "The app can identify transfer-out candidates, but it cannot select a destination store from this file."
            )
            candidates = inventory_health[inventory_health["transfer_out_candidate"]].copy()
            candidate_cols = [
                "article_code", "brand", "display_gender", "display_category", "movement_status",
                "stock_qty", "weeks_cover", "size_curve_status", "stock_value_proxy",
                "dead_stock_status", "markdown_recommendation",
            ]
            st.dataframe(candidates[[c for c in candidate_cols if c in candidates.columns]], use_container_width=True, height=470)

            template_dir = ROOT / "data" / "input_templates"
            weekly_template_path = template_dir / "weekly_store_sales_template.csv"
            display_template_path = template_dir / "current_display_template.csv"
            distance_template_path = template_dir / "store_distance_template.csv"
            t1, t2, t3 = st.columns(3)
            with t1:
                st.download_button(
                    "Download weekly store template",
                    weekly_template_path.read_bytes(),
                    weekly_template_path.name,
                    "text/csv",
                    use_container_width=True,
                )
            with t2:
                st.download_button(
                    "Download current-display template",
                    display_template_path.read_bytes(),
                    display_template_path.name,
                    "text/csv",
                    use_container_width=True,
                )
            with t3:
                st.download_button(
                    "Download distance template",
                    distance_template_path.read_bytes(),
                    distance_template_path.name,
                    "text/csv",
                    use_container_width=True,
                )
        else:
            p1, p2, p3 = st.columns(3)
            with p1:
                receiver_target_woc = st.number_input("Receiver target weeks of cover", 2.0, 12.0, 6.0, 1.0)
            with p2:
                sender_protect_woc = st.number_input("Sender protected weeks of cover", 1.0, 10.0, 4.0, 1.0)
            with p3:
                gross_margin_rate = st.number_input("Gross margin rate", 0.05, 0.90, 0.45, 0.05)
            c1, c2, c3 = st.columns(3)
            with c1:
                fixed_transfer_cost = st.number_input("Fixed transfer cost", 0.0, 5000.0, 2.0, 1.0)
            with c2:
                handling_cost_per_unit = st.number_input("Handling cost per unit", 0.0, 1000.0, 0.5, 0.5)
            with c3:
                cost_per_km = st.number_input("Cost per km", 0.0, 100.0, 0.05, 0.05)

            transfer_df, network_snapshot, network_latest_week = recommend_store_transfers(
                network_df,
                product_master=inventory_health_all,
                distances=distance_df,
                receiver_target_woc=float(receiver_target_woc),
                sender_protect_woc=float(sender_protect_woc),
                fixed_transfer_cost=float(fixed_transfer_cost),
                handling_cost_per_unit=float(handling_cost_per_unit),
                cost_per_km=float(cost_per_km),
                gross_margin_rate=float(gross_margin_rate),
            )
            network_alerts = generate_network_alerts(network_snapshot, transfer_df)
            n1, n2, n3, n4 = st.columns(4)
            n1.metric("Latest network week", network_latest_week.strftime("%d %b %Y"))
            n2.metric("Stores", network_snapshot["store_id"].nunique())
            n3.metric("Transfer lines", len(transfer_df))
            n4.metric("Critical network alerts", int((network_alerts.get("severity", pd.Series(dtype=str)) == "Critical").sum()))
            st.dataframe(transfer_df, use_container_width=True, height=500)
            network_bytes = export_inventory_intelligence_xlsx(
                inventory_health, within_actions, all_store_alerts,
                transfers=transfer_df, network_snapshot=network_snapshot, sku_health=sku_health,
            )
            st.download_button(
                "Download store-transfer execution pack",
                network_bytes,
                f"network_transfer_pack_{network_latest_week.date().isoformat()}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    with rules_view:
        st.markdown("#### Footwear-specific classification logic")
        st.markdown(
            """
            **Movement labels**

            - **Fast mover:** top 20% velocity within brand, gender and category, with healthy sell-through or no more than 12 weeks of cover.
            - **Medium mover:** 40th to 80th velocity percentile.
            - **Slow mover:** below the 40th percentile but with some sales.
            - **Non-mover:** stock exists but no sales are recorded in the available period.
            - **Sold out / OOS:** historical sales exist but current stock is zero.

            **Footwear size-curve labels**

            - The model learns size demand weights by brand, gender and category.
            - Core sizes are the sizes contributing approximately 70% of sales.
            - **Healthy:** at least 80% of core sizes and 70% of weighted size demand are available.
            - **At risk:** partial core-size availability.
            - **Broken:** fewer than 50% of core sizes or less than 45% of weighted size demand is available.

            **Inventory cover and aging**

            - Understock below 4 weeks of cover. Healthy cover from 4 to 12 weeks.
            - Excess cover from 12 to 24 weeks. Severe excess above 24 weeks.
            - Fashion-seasonal age gates: 30, 60, 90, 120 and 180 days.
            - Core-replenishment age gates: 60, 120, 180, 270 and 365 days.
            - Confirmed dead stock requires both age and recent no-sale evidence. The cumulative Apex file can only show a dead-stock risk.

            **Store transfer rule**

            - Transfers are calculated at article-size-store level, not article totals.
            - A sender must retain protected weeks of cover. A receiver must have demand and insufficient cover.
            - The recommendation balances receiver urgency, demand rank, size availability, sender excess and transfer cost.
            - Markdown is recommended only after visibility correction and transfer opportunities are checked.
            """
        )

with tab_planogram:
    st.markdown('<div class="section-title">Visual VM execution planograms</div>', unsafe_allow_html=True)

    upload_col1, upload_col2 = st.columns(2)
    with upload_col1:
        uploaded_images = st.file_uploader(
            "Optional product images. File name must equal article code",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="product_images",
        )
    with upload_col2:
        uploaded_image_zip = st.file_uploader(
            "Or upload one ZIP containing article images",
            type=["zip"],
            key="product_image_zip",
        )

    opt1, opt2, opt3 = st.columns(3)
    with opt1:
        show_codes = st.checkbox("Show article codes", value=True)
    with opt2:
        show_scores = st.checkbox("Show commercial score", value=False)
    with opt3:
        show_zones = st.checkbox("Show zone outlines", value=False)

    image_map = build_product_image_map(uploaded_images, uploaded_image_zip)
    selected_view, gallery_view, bulk_view = st.tabs(
        ["Selected planogram", "All planogram templates", "Export all planograms"]
    )

    with selected_view:
        st.caption(template["source_rule"])
        st.markdown(
            """
            <div class="info-box">
            The approved VM screenshot is the fixed visual template. Campaign visuals, POSM, shelf structure and
            brand design remain unchanged. The app maps recommended article codes or uploaded product images to
            the footwear positions.
            </div>
            """,
            unsafe_allow_html=True,
        )

        visual_image, render_stats = render_visual_planogram(
            placements,
            template,
            brand,
            store_name,
            image_map,
            show_article_codes=show_codes,
            show_scores=show_scores,
            show_zone_outlines=show_zones,
        )
        st.image(visual_image, use_container_width=True)

        s1, s2, s3 = st.columns(3)
        s1.metric("Products rendered", render_stats["rendered"])
        s2.metric("Actual images matched", render_stats["images_matched"])
        s3.metric("Silhouette fallback", render_stats["images_missing"])

        png_bytes = image_to_png_bytes(visual_image)
        pdf_bytes = image_to_pdf_bytes(visual_image)
        d1, d2, d3 = st.columns(3)
        with d1:
            st.download_button(
                "Download visual planogram PNG",
                png_bytes,
                f"{slugify(brand)}_{template['key']}_planogram.png",
                "image/png",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "Download visual planogram PDF",
                pdf_bytes,
                f"{slugify(brand)}_{template['key']}_planogram.pdf",
                "application/pdf",
                use_container_width=True,
            )
        with d3:
            st.download_button(
                "Download article-slot mapping CSV",
                legend.to_csv(index=False).encode("utf-8"),
                f"{slugify(brand)}_{template['key']}_mapping.csv",
                "text/csv",
                use_container_width=True,
            )

        st.markdown("#### Store execution legend")
        st.dataframe(legend, use_container_width=True, height=440)

    with gallery_view:
        st.markdown("#### All eight included templates")
        st.caption("Select any of these from the sidebar. Brand walls automatically use their own brand data.")
        gallery_templates = all_planogram_templates(brand, family="All included")
        gallery_items = list(gallery_templates.items())
        for row_start in range(0, len(gallery_items), 2):
            cols = st.columns(2)
            for col, (gallery_name, gallery_template) in zip(cols, gallery_items[row_start:row_start + 2]):
                with col:
                    st.image(gallery_template["asset_path"], use_container_width=True)
                    st.markdown(f"**{gallery_name}**")
                    fixed_brand_text = gallery_template["brand"] if gallery_template["kind"] == "wall" else f"Selected brand: {brand}"
                    st.caption(
                        f"{gallery_template['family']} | {fixed_brand_text} | "
                        f"{gallery_template['capacity']} product positions"
                    )

    with bulk_view:
        st.markdown("#### Generate all planograms together")
        st.write(
            "The ZIP contains PNG, PDF and article-slot mapping CSV files for every included planogram. "
            "The five brand walls use Apex, Venturini, Nino Rossi, Moochie and Twinkler data. "
            "The three fixtures use the product brand selected in the sidebar."
        )
        prepare_all = st.checkbox("Prepare all eight planograms for download", value=False)
        if prepare_all:
            with st.spinner("Generating all eight planograms..."):
                all_planograms_zip = build_all_planograms_zip(
                    article_master,
                    brand,
                    store_name,
                    image_map,
                    include_accessories,
                    int(min_stock),
                    gender_filter,
                    category_filter,
                    show_codes,
                    show_scores,
                    show_zones,
                )
            st.download_button(
                "Download all planograms ZIP",
                all_planograms_zip,
                f"apexspace_all_planograms_{date.today().isoformat()}.zip",
                "application/zip",
                use_container_width=True,
            )

with tab_data:
    st.markdown('<div class="section-title">Data source and readiness</div>', unsafe_allow_html=True)
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Size-level rows", f"{source_summary.size_rows:,}")
    d2.metric("Unique articles", f"{source_summary.unique_articles:,}")
    d3.metric("Brands", source_summary.brands)
    d4.metric("Normalised period", f"{SALES_PERIOD_WEEKS:.1f} weeks")

    st.write(f"Sales sheet: **{source_summary.sales_sheet}**. Product-master sheet: **{source_summary.master_sheet or 'Not supplied'}**.")
    st.markdown(
        """
        <div class="warning-box">
        The supplied file contains cumulative 6.5-month sales and a stock snapshot. It does not contain weekly dates,
        product cost, launch dates, current display positions or store-photo observations. The app creates a ranked reset
        planogram, but it cannot prove one-week underperformance, physical out-of-display status, GMROI, stock age or sales uplift.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Size-level source preview")
    st.dataframe(size_df.head(500), use_container_width=True, height=350)
    st.markdown("#### Article-level product master and metrics")
    st.dataframe(article_master.head(500), use_container_width=True, height=350)

with tab_schedule:
    st.markdown('<div class="section-title">Planogram refresh schedule</div>', unsafe_allow_html=True)
    st.metric("Next scheduled review", next_review_date(review_cadence).strftime("%d %B %Y"), review_cadence)
    st.write(
        "The current file supports a reset recommendation based on the full 6.5-month period. The cadence controls the "
        "operational review date. It does not create weekly history from cumulative data."
    )
    schedule = pd.DataFrame([
        ["High-scoring articles", review_cadence, "Retain in prime or secondary space while stock and size set remain healthy."],
        ["Zero-stock articles", "Every data refresh", "Remove from the display recommendation until stock becomes available."],
        ["Low velocity with high cover", review_cadence, "Review for tertiary placement, transfer or range reduction."],
        ["Next-best alternatives", review_cadence, "Use when the primary article is unavailable or fails the agreed future rule."],
        ["VM compliance", "After every reset", "Compare the executed store photograph with the approved visual planogram."],
    ], columns=["Decision group", "Frequency", "Action"])
    st.dataframe(schedule, use_container_width=True)

    st.markdown("#### Production data needed for true weekly replacement")
    st.code(textwrap.dedent("""
    week_start, store_id, article_code, size, sales_units, sales_value,
    opening_stock, receipts, transfers_in, transfers_out, closing_stock,
    display_slot, display_status, launch_date, cost_per_unit
    """))

st.divider()
st.caption(
    "ApexSpace Pro. Pilot engine based on the supplied Apex workbook, VM docket and visual templates. "
    "Commercial scores are decision support, not a validated causal sales-uplift forecast."
)
