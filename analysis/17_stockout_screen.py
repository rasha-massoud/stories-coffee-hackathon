"""Stock-out screen: are there days when a normally selling product sold nothing (or far less than expected) at a branch?
Expected units per product-branch-day = that product's share of the branch's traffic x that day's branch transactions,
so weekday, growth and branch effects are built in. Under a Poisson model we compare observed zero days and extreme
low days with what chance alone predicts."""
import pandas as pd
from scipy.stats import poisson

from common import OUT, Log, load

log = Log("17_stockout_screen")
d = load()
days = pd.date_range(d["dt"].min(), d["dt"].max())
u = d.groupby(["Branch", "Product", "dt"])["Quantity"].sum()
idx = pd.MultiIndex.from_product([sorted(d["Branch"].unique()), sorted(d["Product"].unique()), days],
                                 names=["Branch", "Product", "dt"])
u = u.reindex(idx, fill_value=0).reset_index()
u = u.join(d.groupby(["Branch", "dt"])["Transaction ID"].nunique().rename("tx"), on=["Branch", "dt"])
rate = (u.groupby(["Branch", "Product"])["Quantity"].sum() / u.groupby(["Branch", "Product"])["tx"].sum()).rename("rate")
u = u.join(rate, on=["Branch", "Product"])
u["expected"] = u["rate"] * u["tx"]

log("# Stock-out screen: zero or unusually low sales days")
log(f"Product-branch-days: {len(u):,}. Days with zero sales: {(u.Quantity == 0).sum():,} observed vs "
    f"{poisson.pmf(0, u.expected).sum():,.0f} expected by chance (Poisson).")
rows = []
for t in [2, 3, 4, 6]:
    h = u[u["expected"] >= t]
    rows.append({"expected units that day >=": t, "days": len(h), "zero-sales days observed": int((h.Quantity == 0).sum()),
                 "zero-sales days expected by chance": poisson.pmf(0, h.expected).sum()})
log.table("Zero-sales days for products that normally sell (observed vs chance)", pd.DataFrame(rows).set_index(
    "expected units that day >=").round(2))
u["pearson"] = (u.Quantity - u.expected) / u.expected.pow(0.5)
log(f"Overall dispersion (variance / Poisson variance): {(u.pearson ** 2).mean():.3f} (1.0 = pure chance)")
u["p_low"] = poisson.cdf(u.Quantity, u.expected)
n_low = int((u.p_low < 0.001).sum())
eligible = u[poisson.pmf(0, u.expected) < 0.001]  # only these days could ever be flagged, even with zero sales
exp_flags_all = 0.0  # expected number of flags by chance: P(X <= largest k with CDF < 0.001), summed over days
for m in u.expected:
    k = int(poisson.ppf(0.001, m))
    while k >= 0 and poisson.cdf(k, m) >= 0.001:
        k -= 1
    if k >= 0:
        exp_flags_all += poisson.cdf(k, m)
log(f"Extreme low days (P(sales <= observed) < 0.1%): {n_low} observed. Only {len(eligible):,} of {len(u):,} product-branch-days "
    f"have enough expected demand for even zero sales to be flagged, and the expected number of flags by chance is "
    f"~{exp_flags_all:.2f}. So observing 0 says little: this screen has LOW power to detect shortages.")
log("Note: units include 2-unit lines, so a unit-Poisson model under-predicts zero days; a model of basket incidence would "
    "expect more zeros, so the small excess of zero days may be a modelling artefact rather than a shortage signal.")
u.loc[u.p_low < 0.01].sort_values("p_low").head(50).to_csv(OUT / "stockout_low_days.csv", index=False)
log("Reading: this daily screen does not provide sufficient evidence to recommend inventory investment, but it also has "
    "limited ability to detect shortages, especially for slow-selling products. Availability remains unresolved without "
    "stock records or hourly availability data.")
