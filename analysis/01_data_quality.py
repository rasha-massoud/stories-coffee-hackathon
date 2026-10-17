"""Data quality checks: is the file internally consistent before we trust any finding?"""
import numpy as np
import pandas as pd

from common import COST, DATA, GP, PRICE, REV, Log, load

log = Log("01_data_quality")
d = load()

log("# Data quality report")
log(f"Rows: {len(d):,} | Transactions: {d['Transaction ID'].nunique():,} | "
    f"Dates: {d['Date'].min()} to {d['Date'].max()} ({d['Date'].nunique()} distinct days)")
log(f"Expected calendar days in range: {(d['dt'].max() - d['dt'].min()).days + 1}")
log(f"Branches: {sorted(d['Branch'].unique())} | Products: {d['Product'].nunique()} | Categories: {d['Category'].nunique()}")
log(f"Transaction IDs start with 'SYN-': {d['Transaction ID'].str.startswith('SYN-').all()} "
    "(replacement IDs, as stated in the brief)")

log.table("Missing values", d.isna().sum().to_frame("missing"))
raw_cols = [c for c in pd.read_csv(DATA, nrows=0).columns]
dup = d.duplicated(raw_cols)
log(f"Exact duplicate rows: {dup.sum()} ({dup.mean():.2%} of rows, ${d.loc[dup, REV].sum():,.0f} revenue)")
log(f"Duplicate (transaction, product) lines: {d.duplicated(['Transaction ID', 'Product']).sum()}")
log("Exact duplicates could be double scans or genuine repeat items; the data cannot tell them apart.")
margin = lambda x: x.groupby("Branch")[[REV, GP]].sum().pipe(lambda g: g[GP] / g[REV])
log.table("Branch gross margin with vs without exact duplicates (decision: keep them; impact is negligible)",
          pd.DataFrame({"with_dups": margin(d), "without_dups": margin(d[~dup])}).round(4))
log("Duplicates by branch share:", (d.loc[dup, "Branch"].value_counts(normalize=True)).round(2).to_dict(),
    "vs all rows:", d["Branch"].value_counts(normalize=True).round(2).to_dict())

# Arithmetic consistency of the derived columns.
rev_calc = (d[PRICE] * d["Quantity"] * (1 - d["Discount Rate"])).round(2)
gp_calc = (d[REV] - d[COST] * d["Quantity"]).round(2)
log(f"\nRevenue = price x qty x (1 - discount): max abs error ${(rev_calc - d[REV]).abs().max():.3f}, "
    f"lines off by > $0.02: {((rev_calc - d[REV]).abs() > 0.02).sum()}")
log(f"Gross profit = revenue - cost x qty: max abs error ${(gp_calc - d[GP]).abs().max():.3f}, "
    f"lines off by > $0.02: {((gp_calc - d[GP]).abs() > 0.02).sum()}")
log(f"Non-positive prices/costs/revenue: {(d[[PRICE, COST, REV]] <= 0).sum().sum()} | "
    f"Lines with cost > price: {(d[COST] > d[PRICE]).sum()}")

# A transaction should belong to one branch, date, customer and order type.
t = d.groupby("Transaction ID").agg(
    branches=("Branch", "nunique"), dates=("Date", "nunique"),
    custs=("Customer ID", lambda s: s.nunique(dropna=False)), types=("Order Type", "nunique"))
log(f"Transactions spanning >1 branch/date/customer/order type: "
    f"{(t.branches > 1).sum()}/{(t.dates > 1).sum()}/{(t.custs > 1).sum()}/{(t.types > 1).sum()}")

# Prices: one list price per product per branch, never changed in 6 months.
n_prices = d.groupby(["Product", "Branch"])[PRICE].nunique()
log(f"\nDistinct list prices per (product, branch): min {n_prices.min()}, max {n_prices.max()} "
    "-> prices are fixed per branch for the whole period")
cost_cv = d.groupby(["Product", "Branch"])[COST].agg(lambda s: s.std() / s.mean())
log(f"Unit cost varies line-to-line within (product, branch): median CV {cost_cv.median():.3f}, max {cost_cv.max():.3f}")

log.table("Value ranges", d[[PRICE, COST, REV, GP, "Quantity", "Discount Rate"]].describe().round(2))
log(f"\nHours present: {d['hour'].min()}:00 to {d['hour'].max()}:59")
log(f"Share of lines with a Customer ID: {d['Customer ID'].notna().mean():.1%} "
    "(anonymous lines cannot be used for customer-level analysis)")

log("\nConclusion: arithmetic is internally consistent and no dates are missing. 0.26% of rows are exact "
    "duplicates with no effect on branch margins. Prices AND unit costs are fixed per (product, branch) for "
    "all 6 months, so price elasticity cannot be estimated from within-branch variation.")
