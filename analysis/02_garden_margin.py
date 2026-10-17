"""Main problem: why does Garden earn ~47% gross margin when Harbour earns ~65% on the same menu,
what is it worth to fix, and which assumptions could change the recommendation?"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import BRANCHES, COLORS, COST, FIG, GP, PRICE, REV, Log, load

log = Log("02_garden_margin")
d = load()
g, h, u = (d[d["Branch"] == b] for b in ["Garden", "Harbour", "Uptown"])

# ---------------------------------------------------------------- 1. The gap
summary = d.groupby("Branch").agg(revenue=(REV, "sum"), gross_profit=(GP, "sum"), cogs=("cogs", "sum"),
                                  lines=(REV, "size"))
summary["margin"] = summary.gross_profit / summary.revenue
log("# Garden margin analysis")
log.table("Branch totals, Jan-Jun 2026 (observed)", summary.round(3))

monthly = d.groupby(["Branch", "month"])[[REV, GP]].sum()
monthly = (monthly[GP] / monthly[REV]).unstack(0)
log.table("Gross margin by month (observed)", monthly.round(3))

# ---------------------------------------------------------------- 2. Diagnosis: cost and price per product
unit = d.groupby(["Product", "Branch"]).agg(cost=(COST, "first"), price=(PRICE, "first")).unstack()
ratios = pd.DataFrame({
    "garden_cost_vs_harbour": unit["cost"]["Garden"] / unit["cost"]["Harbour"],
    "uptown_cost_vs_harbour": unit["cost"]["Uptown"] / unit["cost"]["Harbour"],
    "garden_price_vs_harbour": unit["price"]["Garden"] / unit["price"]["Harbour"],
    "uptown_price_vs_harbour": unit["price"]["Uptown"] / unit["price"]["Harbour"],
})
log.table("Per-product ratios vs Harbour (45 products, observed)", ratios.describe().round(4))
log("\nFinding: every one of 45 products costs Garden 1.426-1.439x what it costs Harbour, while Uptown's costs "
    "are ~0.96x Harbour's. Garden's prices are 0.952x Harbour's on every product; Uptown's 0.914x.")
log("Unit costs never change within (product, branch) over 6 months -> they are standard/recipe costs "
    "set in a costing sheet, not measured purchase prices.")

# Does the ratio depend on anything operational?
def ratio_by(col):
    c = d.groupby([col, "Branch", "Product"])[COST].first().unstack("Branch")
    return (c["Garden"] / c["Harbour"]).groupby(level=0).agg(["mean", "min", "max"]).round(3)

for col in ["month", "Category", "Order Type", "weekday"]:
    log.table(f"Garden/Harbour unit-cost ratio by {col}", ratio_by(col))

# ---------------------------------------------------------------- 3. Alternative explanations
log("\n# Alternative explanations tested")

# (a) Product mix: re-price every branch on the SAME company-wide mix.
mix = d.groupby("Product")["Quantity"].sum()
std_margin = {}
for b in BRANCHES:
    p, c = unit["price"][b], unit["cost"][b]
    std_margin[b] = 1 - (c * mix).sum() / (p * mix).sum()
log.table("(a) Mix-standardised margin (company-wide mix applied to each branch's prices/costs)",
          pd.DataFrame({"actual": summary.margin, "same_mix": pd.Series(std_margin)}).round(4))

# (b) Discounts, quantity, order type, basket size, time of day.
tx = d.groupby("Transaction ID").agg(Branch=("Branch", "first"), items=("Quantity", "sum"),
                                     revenue=(REV, "sum"), hour=("hour", "first"))
behaviour = pd.DataFrame({
    "discounted_line_share": d.groupby("Branch")["discounted"].mean(),
    "discount_$_share_of_list": d.groupby("Branch").apply(lambda x: 1 - x[REV].sum() / x["list_rev"].sum()),
    "qty2_share": d.groupby("Branch")["Quantity"].apply(lambda s: (s == 2).mean()),
    "takeaway_share": d.groupby("Branch")["Order Type"].apply(lambda s: (s == "Takeaway").mean()),
    "items_per_txn": tx.groupby("Branch")["items"].mean(),
    "evening_txn_share_19h+": tx.groupby("Branch")["hour"].apply(lambda s: (s >= 19).mean()),
})
log.table("(b) Operating behaviour by branch (observed)", behaviour.round(3))

# How much of the margin gap could discounts explain at most?
disc_effect = behaviour["discount_$_share_of_list"]
log(f"Discounts reduce revenue by {disc_effect['Garden']:.2%} at Garden vs {disc_effect['Harbour']:.2%} at Harbour "
    "-> Garden discounts LESS, so discounts cannot explain its lower margin.")

alternatives = pd.DataFrame([
    ["Different product mix", "Rejected", "Margin on identical mix: Garden %.1f%% vs Harbour %.1f%%"
     % (100 * std_margin["Garden"], 100 * std_margin["Harbour"])],
    ["Heavier discounting", "Rejected", "Garden discounts less than Harbour (see table b)"],
    ["Waste, spoilage, theft, over-portioning", "Not testable here", "Costs are fixed standard costs, so real waste "
     "would not show in this export; the uniform 1.43 is a rule, not a waste pattern"],
    ["Recent supplier price rise / inflation", "Not testable from this export", "Recorded costs are flat Jan-Jun, but a "
     "cost sheet that is never updated would also be flat; invoices would show it"],
    ["Packaging or labour loaded into COGS", "Not distinguishable from a fixed allocation", "A standard-cost uplift can "
     "include packaging or labour without varying by order type or weekday; recipe/packaging/payroll records would show it"],
    ["Different supplier contract or delivery premium for Garden", "Consistent", "A uniform markup on all inputs "
     "matches a contract-level or logistics surcharge"],
    ["Rent/overhead allocated into Garden's COGS", "Consistent", "A uniform 43% uplift also matches an "
     "accounting allocation; this would mean NO cash saving (see assumption A1)"],
    ["Data entry / costing-sheet error", "Consistent", "A single wrong multiplier in the cost sheet "
     "would look exactly like this"],
], columns=["explanation", "verdict", "evidence"])
log.table("Alternative explanations", alternatives.set_index("explanation"))
alternatives.to_csv(FIG.parent / "results" / "alternative_explanations.csv", index=False)

# ---------------------------------------------------------------- 4. Value: decompose the gap
cost_ratio = ratios["garden_cost_vs_harbour"]
price_ratio = ratios["garden_price_vs_harbour"]
g = g.assign(cogs_harbour=g["cogs"] / g["Product"].map(cost_ratio),
             rev_harbour_price=g[REV] / g["Product"].map(price_ratio))
gp_actual = g[GP].sum()
gp_cost_fix = (g[REV] - g["cogs_harbour"]).sum()
gp_price_fix = (g["rev_harbour_price"] - g["cogs"]).sum()
gp_both = (g["rev_harbour_price"] - g["cogs_harbour"]).sum()
decomp = pd.Series({
    "Actual Garden gross profit": gp_actual,
    "+ cost effect (costs at Harbour level)": gp_cost_fix - gp_actual,
    "+ price effect (Harbour prices, same volume)": gp_price_fix - gp_actual,
    "= both (interaction included)": gp_both,
    "margin if both fixed": (g["rev_harbour_price"] - g["cogs_harbour"]).sum() / g["rev_harbour_price"].sum(),
})
log.table("Decomposition of Garden's gap, Jan-Jun 2026 (ESTIMATE: counterfactual, same volume)", decomp.round(3))

# Annualise two ways: H1 x 2 (no growth) and June run-rate x 12 (growth already achieved).
june = g[g["month"] == 6]
cost_gap_h1 = gp_cost_fix - gp_actual
cost_gap_june = (june["cogs"] - june["cogs"] / june["Product"].map(cost_ratio)).sum()
annual = pd.DataFrame({
    "conservative (H1 x 2)": [cost_gap_h1 * 2, (gp_price_fix - gp_actual) * 2],
    "run-rate (June x 12)": [cost_gap_june * 12,
                             ((june[REV] / june["Product"].map(price_ratio)) - june[REV]).sum() * 12],
}, index=["cost gap $/yr", "price gap $/yr (0 volume loss)"])
log.table("Annualised value (ESTIMATE)", annual.round(0))
log(f"For scale: company-wide gross profit Jan-Jun = ${summary.gross_profit.sum():,.0f}; "
    f"Garden's cost gap = {cost_gap_h1 / summary.gross_profit.sum():.1%} of it.")

# Partial closure of the cost gap (negotiations rarely reach 100%).
closure = pd.DataFrame({f"{int(f * 100)}% closed": [cost_gap_h1 * 2 * f, cost_gap_june * 12 * f]
                        for f in [0.25, 0.5, 0.75, 1.0]},
                       index=["conservative $/yr", "run-rate $/yr"]).round(0)
log.table("Cost-gap value by share of gap closed (ESTIMATE)", closure)
closure.to_csv(FIG.parent / "results" / "cost_gap_closure.csv")

# ---------------------------------------------------------------- 5. Price alignment: elasticity sensitivity
# Elasticity is NOT estimable here (prices never change within a branch), so we sweep it.
x = 1 / price_ratio - 1  # per-product price increase needed to reach Harbour's price (~5%)
def price_gain(elasticity, cost_scale):
    q_mult = 1 + elasticity * g["Product"].map(x)
    new_gp = (q_mult * (g["rev_harbour_price"] - g["cogs"] / cost_scale)).sum()
    old_gp = (g[REV] - g["cogs"] / cost_scale).sum()
    return 2 * (new_gp - old_gp)

elasticities = [0, -0.5, -1.0, -1.5, -2.0, -2.5, -3.0]
sens = pd.DataFrame({
    "today's costs": [price_gain(e, 1) for e in elasticities],
    "after cost fix": [price_gain(e, g["Product"].map(cost_ratio)) for e in elasticities],
}, index=pd.Index(elasticities, name="price elasticity")).round(0)
log.table("Annual gross-profit change from +5% Garden prices, by assumed elasticity (ESTIMATE)", sens)
avg_x = x.mean()
for label, m in [("today's costs", summary.margin["Garden"]),
                 ("after cost fix", 1 - (g["cogs_harbour"].sum() / g[REV].sum()))]:
    allowed_loss = 1 - m / (m + avg_x)
    log(f"Break-even ({label}): a {avg_x:.1%} price rise pays off unless volume falls more than "
        f"{allowed_loss:.1%} (elasticity worse than {-allowed_loss / avg_x:.2f}).")
sens.to_csv(FIG.parent / "results" / "price_elasticity_sensitivity.csv")

# ---------------------------------------------------------------- 6. Figures
fig, ax = plt.subplots(figsize=(6.5, 5.5))
for b, mark in [("Garden", "o"), ("Uptown", "s")]:
    ax.scatter(unit["cost"]["Harbour"], unit["cost"][b], s=28, marker=mark, color=COLORS[b],
               label=f"{b} (x{ratios[f'{b.lower()}_cost_vs_harbour'].mean():.2f})")
lim = np.array([0, unit["cost"].max().max() * 1.05])
ax.plot(lim, lim, color="#a0aec0", lw=1, ls="--", label="equal to Harbour")
ax.set(xlim=lim, ylim=lim, xlabel="Harbour unit cost (USD)", ylabel="Branch unit cost (USD)",
       title="Garden's recorded unit cost is ~43% above Harbour's on all 45 products")
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "01_unit_cost_vs_harbour.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(7, 4))
for b in BRANCHES:
    ax.plot(monthly.index, monthly[b] * 100, marker="o", color=COLORS[b], label=b)
ax.set(ylim=(40, 70), xlabel="Month (2026)", ylabel="Gross margin (%)",
       title="Garden's margin gap is constant every month")
ax.set_xticks(range(1, 7), ["Jan", "Feb", "Mar", "Apr", "May", "Jun"])
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "02_margin_by_month.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(7, 4))
steps = [gp_actual, cost_gap_h1, gp_both - gp_cost_fix]
labels = ["Garden actual", "+ costs at\nHarbour level", "+ prices at\nHarbour level\n(no volume loss)"]
bottoms = [0, gp_actual, gp_cost_fix]
ax.bar(labels, steps, bottom=bottoms, color=["#c05621", "#2f855a", "#9ae6b4"])
for i, (s, bt) in enumerate(zip(steps, bottoms)):
    ax.text(i, bt + s / 2, f"${s / 1000:,.1f}k", ha="center", va="center", color="white" if i < 2 else "black")
ax.set(ylabel="Gross profit Jan-Jun (USD)", title="Where Garden's missing profit comes from (6 months)")
fig.tight_layout(); fig.savefig(FIG / "03_garden_gap_decomposition.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(7, 4))
for col, color in [("today's costs", "#c05621"), ("after cost fix", "#2f855a")]:
    ax.plot(sens.index, sens[col] / 1000, marker="o", color=color, label=col)
ax.axhline(0, color="#a0aec0", lw=1)
ax.set(xlabel="Assumed price elasticity of demand", ylabel="Annual gross profit change ($k)",
       title="+5% Garden prices: worth it unless demand is very price-sensitive")
ax.invert_xaxis(); ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "04_price_elasticity_sensitivity.png", dpi=150); plt.close(fig)
log("\nFigures written to figures/01-04.")
