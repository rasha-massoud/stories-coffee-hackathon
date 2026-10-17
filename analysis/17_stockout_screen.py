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
log(f"Extreme low days (P(sales <= observed) < 0.1%): {n_low} observed; chance alone would give up to ~{len(u) * 0.001:.0f}")
u.loc[u.p_low < 0.01].sort_values("p_low").head(50).to_csv(OUT / "stockout_low_days.csv", index=False)
log("Reading: zero-sales days run only slightly above chance (consistent with ordinary extra variation, dispersion ~1.09), "
    "and there are no extreme low-sales days at all. The transaction data shows no stock-out signal, so product "
    "availability does not appear to be a profit lever. Limit: a product that runs out late in the day would only show "
    "as a partial shortfall, which this daily screen can't separate from noise; an hourly screen or inventory records "
    "would be needed.")
