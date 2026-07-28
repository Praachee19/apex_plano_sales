# ApexSpace Pro. Footwear Inventory Intelligence Edition

This version keeps all eight approved visual planograms and adds footwear-specific inventory health, alerts, within-store movement and store-to-store transfer logic.

## Included visual planograms

- Apex Brand Wall
- Venturini Brand Wall
- Nino Rossi Brand Wall
- Moochie Brand Wall
- Twinkler Brand Wall
- Fixture 1. 24 product positions
- Fixture 2. 8 product positions
- Fixture 3. 16 product positions

## New inventory intelligence

- Fast mover, medium mover, slow mover, non-mover and sold-out labels
- Footwear size-curve health using core-size demand weights
- Weeks-of-cover alerts
- Age buckets when launch or first-receipt dates are supplied
- Confirmed dead-stock logic when age and recent no-sale data exist
- Dead-stock risk labels when the current cumulative workbook cannot verify age
- Prime, secondary, tertiary and remove-from-display recommendations
- Current-zone to target-zone movement instructions when a current display file is uploaded
- Size-level store-to-store transfer recommendations when weekly store data is uploaded
- Markdown review only after visibility and transfer checks
- Excel alert pack and WhatsApp-ready alert text

## Important data limitation

The packaged Apex workbook contains cumulative 6.5-month sales and one stock snapshot. It does not contain store-level history, weekly dates, launch dates or current display locations. Therefore:

- The app can classify relative movement and identify excess or no-sale stock risk.
- It cannot confirm actual inventory age without a launch or receipt date.
- It cannot choose a destination store without weekly store-SKU-size data.
- It does not call stock confirmed dead stock when the required evidence is missing.

Use the templates in `data/input_templates` to enable the complete logic.

## First run

Double-click:

`RESET_AND_RUN.bat`

The app opens at:

`http://localhost:8505`

## Later runs

Double-click:

`RUN_APP.bat`

## Weekly network data required columns

`week_start, store_id, article_code, size, sales_units, closing_stock`

Recommended additional columns:

`sales_value, opening_stock, receipts, transfers_in, transfers_out, current_zone, launch_date, first_receipt_date, cost_per_unit`

## Research basis

The logic follows established fashion-retail principles: SKU-store demand is intermittent, transfers should use updated demand and inventory, and footwear decisions must preserve useful size curves rather than optimise article totals alone.
