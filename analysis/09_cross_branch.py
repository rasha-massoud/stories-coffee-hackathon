"""Cross-branch customers: 94% of identified customers use 2+ branches. If a Garden price rise moves visits to
Harbour/Uptown instead of losing them, what does that do to the company-level break-even?"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import COLORS, FIG, GP, OUT, REV, Log, load

log = Log("09_cross_branch")
d = load()

tx = d.groupby("Transaction ID").agg(cust=("Customer ID", "first"), Branch=("Branch", "first"),
                                     revenue=(REV, "sum"), gp=(GP, "sum"))
per_txn = tx.groupby("Branch")[["revenue", "gp"]].mean()
log("# Cross-branch customers and the company-level value of a Garden price rise")
log.table("Revenue and gross profit per visit by branch (observed)", per_txn.round(2))
log(f"Each visit made at Harbour instead of Garden earns ${per_txn.loc['Harbour', 'gp'] - per_txn.loc['Garden', 'gp']:.2f} "
    f"more gross profit ({per_txn.loc['Harbour', 'gp'] / per_txn.loc['Garden', 'gp'] - 1:+.0%}), at a similar basket "
    f"(${per_txn.loc['Harbour', 'revenue']:.2f} vs ${per_txn.loc['Garden', 'revenue']:.2f}).")

g_lines = d[d["Branch"] == "Garden"]
cost_ratio = (d[d["Branch"] == "Garden"].groupby("Product")["Unit Cost (USD)"].first()
              / d[d["Branch"] == "Harbour"].groupby("Product")["Unit Cost (USD)"].first())
gp_fixed = (g_lines[REV] - g_lines["cogs"] / g_lines["Product"].map(cost_ratio)).sum() / (tx["Branch"] == "Garden").sum()
log(f"Garden GP per visit if its costs were at Harbour level (ESTIMATE): ${gp_fixed:.2f} vs Harbour ${per_txn.loc['Harbour', 'gp']:.2f} "
    "-> most of the per-visit gap is the cost uplift, not anything about Garden's customers.")

# ---------------------------------------------------------------- 1. How mixed are customers?
k = tx.dropna(subset=["cust"])
cb = k.groupby(["cust", "Branch"]).size().unstack(fill_value=0)
cb["n"] = cb.sum(axis=1)
cb["branches"] = (cb[["Garden", "Harbour", "Uptown"]] > 0).sum(axis=1)
cb["home"] = cb[["Garden", "Harbour", "Uptown"]].idxmax(axis=1)
log(f"\nIdentified customers: {len(cb):,}; using 2+ branches: {(cb['branches'] >= 2).mean():.1%}; all 3: {(cb['branches'] == 3).mean():.1%}")
share = cb[["Garden", "Harbour", "Uptown"]].div(cb["n"], axis=0)
home_tbl = share.groupby(cb["home"]).mean()
home_tbl["customers"] = cb["home"].value_counts()
log.table("Where customers make their visits, by home branch (observed; rows = home branch)", home_tbl.round(3))

# Is the mix just each branch's overall size? Compare with the branch shares of all identified visits.
overall = k["Branch"].value_counts(normalize=True)
log(f"Branch shares of all identified visits: {overall.round(3).to_dict()}")
# Simulate: if every customer picked a branch at random with these shares, how many would use 2+ branches?
rng = np.random.default_rng(1)
sim_multi = np.mean([(np.array([len(set(rng.choice(3, size=n, p=overall[['Garden', 'Harbour', 'Uptown']].values)))
                                for n in cb["n"].values]) >= 2).mean() for _ in range(20)])
log(f"If each visit picked a branch at random by overall share: {sim_multi:.1%} would use 2+ branches vs {(cb['branches'] >= 2).mean():.1%} "
    "observed -> customers are about as mixed as pure chance: branch loyalty is weak.")

# ---------------------------------------------------------------- 2. Company-level break-even for a Garden price rise
# Garden raises prices by x (to Harbour level). Garden loses a fraction L of its visits. A share s of those lost visits
# moves to Harbour/Uptown (in proportion to where Garden-home customers already go) instead of leaving Stories.
x = 0.05
gp_g, rev_g = per_txn.loc["Garden", "gp"], per_txn.loc["Garden", "revenue"]
garden_home = home_tbl.loc["Garden", ["Harbour", "Uptown"]]
w = garden_home / garden_home.sum()
gp_other = (per_txn.loc[["Harbour", "Uptown"], "gp"] * w).sum()
gp_g_new = gp_g + rev_g * x
log(f"\nGarden GP/visit now ${gp_g:.2f}; after +5% ${gp_g_new:.2f}. A switched visit earns ${gp_other:.2f} at the "
    f"Harbour/Uptown mix Garden customers already use ({w.round(2).to_dict()}).")
rows = []
for s in [0, 0.25, 0.5, 0.75, 1.0]:
    denom = gp_g_new - s * gp_other
    be = rev_g * x / denom if denom > 0 else np.inf
    rows.append({"share of lost Garden visits that switch branch (s)": s,
                 "company break-even Garden volume loss": "none: stays profitable at any loss" if be > 1 else f"{be:.1%}"})
be_tbl = pd.DataFrame(rows).set_index("share of lost Garden visits that switch branch (s)")
log.table("Company-level break-even for +5% at Garden (ESTIMATE)", be_tbl)
s_star = gp_g_new / gp_other
log(f"If at least {s_star:.0%} of lost Garden visits move to another Stories branch, the company gains GP whatever Garden's "
    "volume loss - because a visit at Harbour earns more than a visit at Garden even after the price rise.")

N = len(tx[tx["Branch"] == "Garden"]) * 2  # Garden visits per year (H1 x 2)
grid = []
for s in [0, 0.5, 0.75]:
    for L in [0.0, 0.05, 0.10, 0.15, 0.20]:
        grid.append({"s": s, "Garden volume loss": L,
                     "company GP change $/yr": N * ((1 - L) * gp_g_new - gp_g + L * s * gp_other)})
grid = pd.DataFrame(grid).pivot(index="Garden volume loss", columns="s", values="company GP change $/yr")
grid.columns = [f"s = {c:.0%} switch" for c in grid.columns]
log.table("Company GP change from +5% at Garden, $/yr (ESTIMATE; H1 x 2 Garden visits)", grid.round(0))
grid.to_csv(OUT / "garden_price_company_level.csv")
log("Implication for the pilot: measure Garden's loss AND where lost identified customers go (Customer IDs). The decision "
    "rule should be company-level gross profit, not Garden's alone. A Garden-only rule would reject a price rise that "
    "makes Stories more money.")
log("Caveat: switching behaviour under a price change is not observed in this data (prices never change). The fact that "
    "customers already spread their visits across branches about as much as chance suggests switching is easy, but s "
    "must be measured in the pilot.")

fig, ax = plt.subplots(figsize=(7, 4))
for col, c in zip(grid.columns, ["#c05621", "#718096", "#2f855a"]):
    ax.plot(grid.index * 100, grid[col] / 1000, marker="o", color=c, label=col)
ax.axhline(0, color="#4a5568", lw=0.8)
ax.set(xlabel="Garden volume lost after +5% prices (%)", ylabel="Company gross profit change ($k/yr)",
       title="If lost Garden visits move to Harbour, a price rise pays even with big losses")
ax.legend(frameon=False, title="share of lost visits that switch branch")
fig.tight_layout(); fig.savefig(FIG / "14_garden_price_company_level.png", dpi=150); plt.close(fig)

# ---------------------------------------------------------------- 3. Customer concentration (identified customers)
cv = k.groupby("cust").agg(visits=("gp", "size"), revenue=("revenue", "sum"), gp=("gp", "sum")).sort_values("gp", ascending=False)
top = int(len(cv) * 0.2)
log(f"\nTop 20% of identified customers ({top:,}) bring {cv['gp'].head(top).sum() / cv['gp'].sum():.1%} of identified gross profit "
    f"and {cv['visits'].head(top).sum() / cv['visits'].sum():.1%} of identified visits (observed). A strict 80/20 rule would be 80%.")
log(f"Identified customers bring {k['gp'].sum() / tx['gp'].sum():.1%} of all gross profit; anonymous visits the rest.")
log(f"Visits per identified customer in 6 months: median {cv['visits'].median():.0f}, 90th percentile {cv['visits'].quantile(0.9):.0f}, "
    f"max {cv['visits'].max()}. GP per visit, top 20% vs rest: ${cv['gp'].head(top).sum() / cv['visits'].head(top).sum():.2f} vs "
    f"${cv['gp'].iloc[top:].sum() / cv['visits'].iloc[top:].sum():.2f}")
log("Reading: value is spread fairly evenly (no 80/20). Top customers are worth more mostly because they come more often "
    "(30% of visits) and partly because each visit earns more (ranking by GP also selects higher-GP visits). There is no "
    "small VIP group to target; a loyalty scheme should reward frequency.")
