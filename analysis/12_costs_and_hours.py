"""(1) Uptown as the procurement benchmark: it pays ~4% less than Harbour for every item. (2) Opening hours:
gross profit earned per open hour by branch, as a break-even rule against staffing cost (labour cost is not in the data)."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import BRANCHES, COLORS, COST, FIG, GP, OUT, Log, load

log = Log("12_costs_and_hours")
d = load()
months = d["dt"].dt.to_period("M").nunique()
ANNUAL = 12 / months

# ================================================================ 1. Uptown as cost benchmark
log("# 1. Procurement benchmark: what if every branch bought at the cheapest branch's unit cost?")
unit_cost = d.groupby(["Product", "Branch"])[COST].first().unstack()
ratio = unit_cost.div(unit_cost["Harbour"], axis=0)
log.table("Unit cost relative to Harbour, across 45 products (observed)", ratio.describe().loc[["mean", "min", "max"]].round(3))
cheapest = unit_cost.idxmin(axis=1).value_counts()
log(f"Branch with the lowest unit cost, per product: {cheapest.to_dict()}")
d["uptown_cost"] = d["Product"].map(unit_cost["Uptown"])
rows = {}
for b in BRANCHES:
    sub = d[d["Branch"] == b]
    actual = sub["cogs"].sum()
    at_h = (sub["Quantity"] * sub["Product"].map(unit_cost["Harbour"])).sum()
    at_u = (sub["Quantity"] * sub["uptown_cost"]).sum()
    rows[b] = {"COGS actual (6m)": actual, "saving at Harbour cost $/yr": (actual - at_h) * ANNUAL,
               "saving at Uptown cost $/yr": (actual - at_u) * ANNUAL}
bench = pd.DataFrame(rows).T
bench.loc["Total"] = bench.sum()
log.table("Annual gross-profit gain if each branch bought at Harbour's or Uptown's unit cost (ESTIMATE, H1 x 2)", bench.round(0))
# Incremental to the Garden-only fix (Garden -> Harbour cost). Do NOT subtract the company-wide Harbour row: it would
# include raising Uptown's costs to Harbour's level, which nobody proposes.
extra = bench.loc["Total", "saving at Uptown cost $/yr"] - bench.loc["Garden", "saving at Harbour cost $/yr"]
log(f"Beyond the Garden-only fix (${bench.loc['Garden', 'saving at Harbour cost $/yr']:,.0f}/yr), matching Uptown's costs "
    f"everywhere adds ${extra:,.0f}/yr (Harbour ${bench.loc['Harbour', 'saving at Uptown cost $/yr']:,.0f}, Garden "
    f"${bench.loc['Garden', 'saving at Uptown cost $/yr'] - bench.loc['Garden', 'saving at Harbour cost $/yr']:,.0f}).")
log("Caveat: Uptown sells the least, but sales volume says nothing about purchasing terms or pooled contracts - the "
    "reason for its lower recorded costs is unknown (local supplier, delivery terms or a different cost rule). Same audit as Garden: compare Uptown's and Harbour's invoices for a few items. "
    "This is a secondary, smaller lever (~4% of COGS) than Garden's 43%.")

# ================================================================ 2. Opening hours: GP per open hour
log("\n# 2. Gross profit per open hour, by branch and hour (observed, averaged over all 181 days)")
days = d["dt"].nunique()
hourly = d.groupby(["Branch", "hour"])[GP].sum().unstack(0) / days
log.table("Average gross profit per hour ($/hour)", hourly.round(1))
d["daytype"] = np.where(d["weekday"] == "Saturday", "Saturday", np.where(d["weekday"] == "Tuesday", "Tuesday", "other days"))
ndays = d.groupby("daytype")["dt"].nunique()
cell = d.groupby(["Branch", "daytype", "hour"])[GP].sum().div(ndays, level="daytype").rename("GP $/hour").reset_index()
low = cell.sort_values("GP $/hour").head(12)
log.table("The 12 weakest branch-hours (observed GP $/hour)", low.set_index(["Branch", "daytype", "hour"]).round(1))
annual_low = {}
for (b, h), g in cell[cell["hour"].isin([7, 23])].groupby(["Branch", "hour"]):
    annual_low[(b, h)] = (d[(d["Branch"] == b) & (d["hour"] == h)][GP].sum()) * ANNUAL
log.table("Gross profit per year earned in the first (7:00) and last (23:00) hour, by branch (observed x2)",
          pd.Series(annual_low).rename("GP $/yr").round(0).to_frame())
log("Decision rule: keep an hour open only if the extra staffing + energy cost of that hour is below the avoidable "
    "contribution it earns (recorded GP is a starting point; applying the rule needs Stories' own labour and energy "
    "costs). If some of its customers would come at another hour instead (unmeasured; could be zero), closing loses "
    "less than the GP figure suggests.")
cell.to_csv(OUT / "gp_per_branch_hour.csv", index=False)

fig, ax = plt.subplots(figsize=(8, 4))
for b in BRANCHES:
    ax.plot(hourly.index, hourly[b], marker="o", ms=3, color=COLORS[b], label=b)
ax.set(xlabel="Hour of day", ylabel="Gross profit per hour ($, average day)",
       title="Profit per open hour: early mornings and Uptown are the weakest")
ax.set_xticks(hourly.index)
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "17_gp_per_hour.png", dpi=150); plt.close(fig)
