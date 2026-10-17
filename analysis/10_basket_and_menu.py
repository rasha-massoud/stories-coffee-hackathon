"""Basket attach rates (how often a drink comes with food and vice versa) and a menu-engineering matrix."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import FIG, GP, OUT, REV, Log, load

log = Log("10_basket_and_menu")
d = load()
DRINKS = ["Hot Coffee", "Cold Coffee", "Matcha & Tea", "Cold Drinks"]
months = d["dt"].dt.to_period("M").nunique()
ANNUAL = 12 / months

# ================================================================ 1. Attach rates
log("# 1. Attach rates: drink-only and food-only visits")
d["is_drink"] = d["Category"].isin(DRINKS)
t = d.groupby("Transaction ID").agg(Branch=("Branch", "first"), hour=("hour", "first"), otype=("Order Type", "first"),
                                    drink=("is_drink", "max"), food=("is_drink", lambda s: (~s).any()),
                                    revenue=(REV, "sum"), gp=(GP, "sum"))
t["type"] = np.select([t.drink & t.food, t.drink], ["drink + food", "drink only"], "food only")
mix = t["type"].value_counts(normalize=True)
gp_type = t.groupby("type")[["revenue", "gp"]].mean()
gp_type["share"] = mix
log.table("Visit types (observed)", gp_type.round(3))

# Internal benchmark: is the attach rate different anywhere? If one segment already does better, that is an achievable target.
t["daypart"] = pd.cut(t["hour"], [0, 11, 18, 24], labels=["morning", "day", "evening"])
for col in ["Branch", "otype", "daypart"]:
    log.table(f"Share of visits that are drink + food, by {col}",
              t.groupby(col, observed=True)["type"].apply(lambda s: (s == "drink + food").mean()).round(3).to_frame("attach"))

# What a food item adds to a drink-only visit, and a drink to a food-only visit (GP of the added line).
lines = d.merge(t[["type"]], left_on="Transaction ID", right_index=True)
combo = lines[lines["type"] == "drink + food"]
food_gp = (combo.loc[~combo["is_drink"], GP] / combo.loc[~combo["is_drink"], "Quantity"]).mean()
drink_gp = (combo.loc[combo["is_drink"], GP] / combo.loc[combo["is_drink"], "Quantity"]).mean()
n_drink_only = (t["type"] == "drink only").sum() * ANNUAL
n_food_only = (t["type"] == "food only").sum() * ANNUAL
log(f"\nAverage GP of the food item in a drink+food visit: ${food_gp:.2f}; of the drink item: ${drink_gp:.2f} (observed)")
log(f"Drink-only visits per year: {n_drink_only:,.0f}; food-only: {n_food_only:,.0f} (H1 x 2)")
rows = []
for conv in [0.03, 0.05, 0.10]:
    for disc in [0.0, 0.5]:
        rows.append({"conversion": conv, "combo discount $": disc,
                     "drink-only + food $/yr": n_drink_only * conv * (food_gp - disc),
                     "food-only + drink $/yr": n_food_only * conv * (drink_gp - disc)})
up = pd.DataFrame(rows).set_index(["conversion", "combo discount $"])
up["total $/yr"] = up.sum(axis=1)
log.table("Upsell value (ESTIMATE; conversion = share of single-category visits that add the other category)", up.round(0))
log("Caveat: a combo discount also goes to customers who would have bought both anyway (deadweight). With a $0.50 "
    f"discount on all {(t['type'] == 'drink + food').sum() * ANNUAL:,.0f} existing combo visits/yr, the giveaway would be "
    f"${(t['type'] == 'drink + food').sum() * ANNUAL * 0.5:,.0f}/yr - more than most upsell gains above. So: a barista "
    "prompt or a menu-board suggestion (no discount), not a discounted combo.")

# Most common pairings, to choose the suggestion.
pairs = combo.groupby("Transaction ID").apply(
    lambda g: [(a, b) for a in g.loc[g.is_drink, "Category"] for b in g.loc[~g.is_drink, "Category"]])
pair_counts = pd.Series([p for ps in pairs for p in ps]).value_counts().head(8)
log.table("Most common drink-food category pairs (observed)", pair_counts.to_frame("visits"))

# ================================================================ 2. Menu-engineering matrix
log("\n# 2. Menu engineering (company-wide; GP per unit at Harbour/Uptown costs to avoid Garden's cost distortion)")
nong = d[d["Branch"] != "Garden"]
menu = nong.groupby("Product").agg(category=("Category", "first"), units=("Quantity", "sum"), gp=(GP, "sum"))
menu["gp_per_unit"] = menu["gp"] / menu["units"]
menu["units_all"] = d.groupby("Product")["Quantity"].sum()
pop_cut = 0.7 * menu["units_all"].mean()  # Kasavana-Smith popularity rule
gp_cut = (menu["gp"].sum() / menu["units"].sum())  # weighted average GP per unit
menu["class"] = np.select(
    [(menu["units_all"] >= pop_cut) & (menu["gp_per_unit"] >= gp_cut),
     (menu["units_all"] >= pop_cut) & (menu["gp_per_unit"] < gp_cut),
     (menu["units_all"] < pop_cut) & (menu["gp_per_unit"] >= gp_cut)],
    ["Star (keep, feature)", "Plowhorse (popular, low $: reprice/re-cost)", "Puzzle (high $, low sales: promote)"],
    "Dog (review)")
log(f"Cut-offs: popularity >= {pop_cut:,.0f} units (70% of average); GP/unit >= ${gp_cut:.2f} (weighted average)")
for cls, g in menu.groupby("class"):
    log(f"\n{cls}: {len(g)} items, {g['units_all'].sum() / menu['units_all'].sum():.0%} of units")
    log(g.sort_values("units_all", ascending=False)[["category", "units_all", "gp_per_unit"]].round(2).to_string())
menu.round(3).to_csv(OUT / "menu_engineering.csv")
log("\nReading: 'Dogs' are candidates for review, not automatic removal - removing an item only saves money if its "
    "buyers switch to a better item rather than leave. Test removal at one branch before acting.")

fig, ax = plt.subplots(figsize=(8, 5.5))
colors = {"Star (keep, feature)": "#2f855a", "Plowhorse (popular, low $: reprice/re-cost)": "#c05621",
          "Puzzle (high $, low sales: promote)": "#2b6cb0", "Dog (review)": "#a0aec0"}
for cls, g in menu.groupby("class"):
    ax.scatter(g["units_all"], g["gp_per_unit"], color=colors[cls], label=cls, s=30)
for name, r in menu.iterrows():
    if r["units_all"] > 1500 or r["gp_per_unit"] > 5 or r["gp_per_unit"] < 2.4 or r["units_all"] < pop_cut:
        ax.annotate(name, (r["units_all"], r["gp_per_unit"]), fontsize=6.5, xytext=(3, 2), textcoords="offset points")
ax.axvline(pop_cut, color="#4a5568", lw=0.8, ls=":")
ax.axhline(gp_cut, color="#4a5568", lw=0.8, ls=":")
ax.set(xlabel="Units sold, Jan-Jun (all branches)", ylabel="Gross profit per unit ($, Harbour/Uptown costs)",
       title="Menu engineering: popularity vs profit per item")
ax.legend(frameon=False, fontsize=8, loc="upper right")
fig.tight_layout(); fig.savefig(FIG / "15_menu_engineering.png", dpi=150); plt.close(fig)
