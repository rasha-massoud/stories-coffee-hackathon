"""Uptown pricing: Uptown sells every item 8.6% below Harbour although its costs are ~4% below.
What is that worth, and how sure can we be?"""
import pandas as pd

from common import COST, GP, OUT, PRICE, REV, Log, load

log = Log("08_uptown_pricing")
d = load()
months = d["dt"].dt.to_period("M").nunique()
ANNUAL = 12 / months

unit = d.groupby(["Product", "Branch"]).agg(cost=(COST, "first"), price=(PRICE, "first")).unstack()
u = d[d["Branch"] == "Uptown"]
prod = u.groupby("Product").agg(units=("Quantity", "sum"), revenue=(REV, "sum"), gp=(GP, "sum"))
prod["price"], prod["cost"] = unit["price"]["Uptown"], unit["cost"]["Uptown"]
summary = d.groupby("Branch").agg(revenue=(REV, "sum"), gp=(GP, "sum"))
summary["margin"] = summary["gp"] / summary["revenue"]

log("# Uptown pricing")
log(f"Uptown: revenue ${summary.loc['Uptown', 'revenue']:,.0f} in 6 months, margin {summary.loc['Uptown', 'margin']:.1%} "
    f"(Harbour {summary.loc['Harbour', 'margin']:.1%}). Price vs Harbour: "
    f"{(unit['price']['Uptown'] / unit['price']['Harbour']).mean():.3f}; cost vs Harbour: "
    f"{(unit['cost']['Uptown'] / unit['cost']['Harbour']).mean():.3f} (observed)")

rows = []
for target in ["Garden", "Harbour"]:
    x = unit["price"][target] / prod["price"] - 1
    m = 1 - prod["cost"] / prod["price"]
    for e in [0, -0.5, -1, -1.5, -2]:
        gain = (prod["units"] * (1 + e * x) * (prod["price"] * (1 + x) - prod["cost"])
                - prod["units"] * (prod["price"] - prod["cost"])).sum() * ANNUAL
        rows.append({"move Uptown prices to": f"{target} level (+{x.mean():.1%})", "elasticity": e, "GP change $/yr": gain})
    be = 1 - (m * prod["revenue"]).sum() / prod["revenue"].sum() / (
        (m * prod["revenue"]).sum() / prod["revenue"].sum() + x.mean())
    log(f"Break-even for moving to {target} level (+{x.mean():.1%}): pays off unless volume falls more than {be:.1%}")
sens = pd.DataFrame(rows).pivot(index="elasticity", columns="move Uptown prices to", values="GP change $/yr")
log.table("Annual gross-profit change from repricing Uptown (ESTIMATE, H1 x 2 volume)", sens.round(0))
sens.to_csv(OUT / "uptown_pricing_sensitivity.csv")

early, late = d[d["month"] <= 2], d[d["month"] >= 5]
growth = late.groupby("Branch")["Quantity"].sum() / early.groupby("Branch")["Quantity"].sum() - 1
log(f"\nContext (observed): unit growth Jan-Feb -> May-Jun: Uptown {growth['Uptown']:+.1%}, Garden {growth['Garden']:+.1%}, "
    f"Harbour {growth['Harbour']:+.1%}. The cheapest branch grows slowest - low prices are not visibly buying growth "
    "(correlation only; location and footfall differ).")
log("Alternative explanation: Uptown may be priced low on purpose (competition, local incomes). The data cannot tell; "
    "Stories' management knows. Recommendation: a pilot (+4% to Garden's level on a few items for one calendar month), "
    "not a blanket rise.")
