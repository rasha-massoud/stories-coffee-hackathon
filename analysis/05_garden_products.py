"""Garden product by product: where the excess cost sits, which items barely make money,
and which items to put in the price pilot first."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from common import COST, FIG, GP, OUT, PRICE, REV, Log, load

log = Log("05_garden_products")
d = load()
months = d["dt"].dt.to_period("M").nunique()
ANNUAL = 12 / months  # H1 x 2; conservative (ignores growth, see script 02 for the June run-rate)

unit = d.groupby(["Product", "Branch"]).agg(cost=(COST, "first"), price=(PRICE, "first")).unstack()
g = d[d["Branch"] == "Garden"]
prod = g.groupby("Product").agg(category=("Category", "first"), units=("Quantity", "sum"),
                                revenue=(REV, "sum"), gp=(GP, "sum"), cogs=("cogs", "sum"))
prod["price"] = unit["price"]["Garden"]
prod["cost"] = unit["cost"]["Garden"]
prod["harbour_price"] = unit["price"]["Harbour"]
prod["harbour_cost"] = unit["cost"]["Harbour"]
prod["garden_margin"] = prod["gp"] / prod["revenue"]
prod["harbour_margin"] = 1 - prod["harbour_cost"] / prod["harbour_price"]
prod["gp_per_unit"] = prod["gp"] / prod["units"]

# ---------------------------------------------------------------- 1. Where the excess cost sits
prod["excess_cost_6m"] = prod["cogs"] - prod["units"] * prod["harbour_cost"]
prod["excess_cost_yr"] = prod["excess_cost_6m"] * ANNUAL
pareto = prod.sort_values("excess_cost_6m", ascending=False)
pareto["cum_share"] = pareto["excess_cost_6m"].cumsum() / pareto["excess_cost_6m"].sum()
n50 = int((pareto["cum_share"] < 0.5).sum() + 1)
n80 = int((pareto["cum_share"] < 0.8).sum() + 1)
log("# Garden product-level analysis")
log(f"Total Garden excess cost vs Harbour cost levels: ${prod['excess_cost_6m'].sum():,.0f} in 6 months "
    f"(${prod['excess_cost_yr'].sum():,.0f}/yr, H1 x 2; observed costs, counterfactual estimate)")
log(f"The top {n50} of 45 products hold 50% of the excess cost; the top {n80} hold 80%.")
log.table("Top 15 products by excess cost (procurement priority list)",
          pareto[["category", "units", "cost", "harbour_cost", "excess_cost_6m", "excess_cost_yr", "cum_share"]]
          .head(15).round(2))
cat = prod.groupby("category")[["excess_cost_6m", "revenue"]].sum()
cat["share_of_gap"] = cat["excess_cost_6m"] / cat["excess_cost_6m"].sum()
log.table("Excess cost by category", cat.sort_values("excess_cost_6m", ascending=False).round(3))

# ---------------------------------------------------------------- 2. Items that barely make money at Garden
log("\n# Garden margin by product (observed)")
LOW = 0.35
low = prod[prod["garden_margin"] < LOW].sort_values("garden_margin")
log(f"Garden products below {LOW:.0%} gross margin: {len(low)} of 45, ${low['revenue'].sum():,.0f} of revenue "
    f"({low['revenue'].sum() / prod['revenue'].sum():.0%} of Garden sales). At Harbour, none is below "
    f"{prod['harbour_margin'].min():.0%}.")
low = low.assign(
    price_for_harbour_margin=lambda x: x["cost"] / (1 - x["harbour_margin"]),
    price_for_40pct=lambda x: x["cost"] / 0.6,
)
low["increase_for_40pct"] = low["price_for_40pct"] / low["price"] - 1
log.table("Low-margin Garden products: current vs required prices (estimate)",
          low[["category", "units", "price", "harbour_price", "cost", "garden_margin", "harbour_margin",
               "price_for_40pct", "increase_for_40pct", "gp_per_unit"]].round(2))
log(f"Reading: with today's costs, reaching 40% margin on these items needs price rises of "
    f"{low['increase_for_40pct'].min():.0%}-{low['increase_for_40pct'].max():.0%}, above Harbour's own price for every one of them; "
    "reaching Harbour's margin would need far more. Repricing alone cannot fix them; the cost fix (script 02) is the real lever.")

# ---------------------------------------------------------------- 3. Pilot product list
# Gain from +5% (to roughly Harbour's price) at elasticity e: units*(1+e*x)*(p*(1+x)-c) - units*(p-c)
x = prod["harbour_price"] / prod["price"] - 1
for e in [0, -1, -2]:
    prod[f"gain_yr_e{e}"] = (prod["units"] * (1 + e * x) * (prod["price"] * (1 + x) - prod["cost"])
                             - prod["units"] * (prod["price"] - prod["cost"])) * ANNUAL
prod["break_even_volume_loss"] = 1 - prod["garden_margin"] / (prod["garden_margin"] + x)
# Pilot picks: biggest $ gain at elasticity -1, among items with enough daily volume to measure.
prod["units_per_day"] = prod["units"] / g["dt"].nunique()
pilot = prod[prod["units_per_day"] >= 2].sort_values("gain_yr_e-1", ascending=False).head(8)
log.table("Price pilot candidates: +~5% to Harbour price (estimate; ranked by $ gain at elasticity -1)",
          pilot[["category", "units_per_day", "price", "harbour_price", "garden_margin", "break_even_volume_loss",
                 "gain_yr_e0", "gain_yr_e-1", "gain_yr_e-2"]].round(2))
log(f"Pilot list total: ${pilot['gain_yr_e0'].sum():,.0f}/yr at elasticity 0, ${pilot['gain_yr_e-1'].sum():,.0f} at -1, "
    f"${pilot['gain_yr_e-2'].sum():,.0f} at -2 ({pilot['revenue'].sum() / prod['revenue'].sum():.0%} of Garden revenue). "
    f"These items sell {pilot['units_per_day'].sum():.0f} units/day at Garden; see section 4 below for how long a pilot on them needs.")
log("Why these: the most daily volume and the largest $ gain at elasticity -1 (how long a pilot on them needs: section 4 below). "
    f"Low-margin items (desserts, {pilot['break_even_volume_loss'].max():.0%} break-even) have MORE room for volume loss than "
    f"high-margin drinks ({pilot['break_even_volume_loss'].min():.0%}): when the margin is thin, a 5% price rise is a large share "
    "of the profit per item. So desserts are the safest place to start; Iced Latte and Classic Matcha are the riskiest.")
log(f"All 45 products at Harbour price: ${prod['gain_yr_e0'].sum():,.0f}/yr (e=0), ${prod['gain_yr_e-1'].sum():,.0f} (e=-1), "
    f"${prod['gain_yr_e-2'].sum():,.0f} (e=-2) - close to script 02 (small differences: script 02 uses discounted revenue).")

prod.round(4).to_csv(OUT / "garden_products.csv")
pilot[["category", "price", "harbour_price"]].to_csv(OUT / "garden_pilot_products.csv")

# ---------------------------------------------------------------- Figures
fig, ax = plt.subplots(figsize=(9, 4.5))
top = pareto.head(20)
ax.bar(range(len(top)), top["excess_cost_yr"] / 1000, color="#c05621")
ax.set_xticks(range(len(top)), top.index, rotation=60, ha="right", fontsize=8)
ax.set_ylabel("Excess cost at Garden ($k/yr)")
ax2 = ax.twinx()
ax2.plot(range(len(top)), top["cum_share"] * 100, color="#2b6cb0", marker="o", ms=3)
ax2.set(ylabel="Cumulative share of the gap (%)", ylim=(0, 100))
ax.set_title(f"{n50} products hold half of Garden's excess cost: negotiate these first")
fig.tight_layout(); fig.savefig(FIG / "08_garden_excess_cost_pareto.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(7, 5))
ax.scatter(prod["harbour_margin"] * 100, prod["garden_margin"] * 100, s=prod["units"] / 15, color="#c05621", alpha=0.7)
for name, r in prod[prod["garden_margin"] < LOW].iterrows():
    ax.annotate(name, (r["harbour_margin"] * 100, r["garden_margin"] * 100), fontsize=7, xytext=(4, -3),
                textcoords="offset points")
lim = [0, 85]
ax.plot(lim, lim, ls="--", color="#a0aec0", lw=1, label="same margin as Harbour")
ax.axhline(LOW * 100, color="#4a5568", lw=0.8, ls=":", label=f"{LOW:.0%} margin")
ax.set(xlim=lim, ylim=lim, xlabel="Harbour gross margin (%)", ylabel="Garden gross margin (%)",
       title=f"Every product earns less at Garden; {len(low)} items fall below {LOW:.0%}")
ax.legend(frameon=False, loc="upper left")
fig.tight_layout(); fig.savefig(FIG / "09_garden_vs_harbour_margin.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 4. Can a pilot on just these items be measured?
pdays = g[g["Product"].isin(pilot.index)].groupby("dt")["Quantity"].sum().reindex(
    pd.date_range(d["dt"].min(), d["dt"].max()), fill_value=0).to_frame("units")
pdays["t"] = np.arange(len(pdays))
Xp = pd.get_dummies(pdays.index.dayofweek, prefix="dow", drop_first=True).astype(float).set_index(pdays.index)
Xp["t"] = pdays["t"]
train = pdays.index < "2026-05-01"
mdl = LinearRegression().fit(Xp[train], np.log1p(pdays.loc[train, "units"]))
resid_sd = (np.log1p(pdays.loc[~train, "units"]) - mdl.predict(Xp[~train])).std()
log.table("Detectable drop in pilot-item units at Garden (same method as script 03; 5% test, 80% power)",
          pd.DataFrame({"pilot days": [30, 61, 91],
                        "min detectable drop": [f"{2.8 * resid_sd / np.sqrt(n):.1%}" for n in [30, 61, 91]]}).set_index("pilot days"))
log("If one month cannot detect drops below the ~10% break-even, the pilot on these 8 items needs 2 calendar months, "
    "or the +5% should apply to the whole Garden menu (whole-branch traffic is measurable to ~6% in one month, script 03).")
