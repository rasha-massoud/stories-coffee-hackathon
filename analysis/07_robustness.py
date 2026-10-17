"""Robustness: does the forecast beat the baseline in every month, how uncertain are the $ values,
does the main number survive different data choices, and is there anything odd in the data?"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from common import COST, FIG, GP, OUT, PRICE, REV, Log, load

log = Log("07_robustness")
d = load()
rng = np.random.default_rng(42)
PROMO_DAYS = set(pd.date_range("2026-03-12", "2026-03-19")) | set(pd.date_range("2026-05-12", "2026-05-19"))

# ================================================================ 1. Rolling-origin backtest (Garden daily transactions)
log("# 1. Rolling-origin backtest: M1 (weekday + trend) vs naive baseline, Garden daily transactions")
daily = d[d["Branch"] == "Garden"].groupby("dt")["Transaction ID"].nunique().to_frame("y")
daily["dow"] = daily.index.dayofweek
daily["t"] = (daily.index - daily.index.min()).days

def X(df):
    out = pd.get_dummies(df["dow"], prefix="dow").astype(float).reindex(
        columns=[f"dow_{i}" for i in range(1, 7)], fill_value=0.0)
    out["t"] = df["t"]
    return out

rows = []
for test_month in [3, 4, 5, 6]:
    train = daily[daily.index.month < test_month]
    test = daily[daily.index.month == test_month]
    m = LinearRegression().fit(X(train), np.log(train["y"]))
    pred = np.exp(m.predict(X(test)))
    naive = daily["y"].shift(7).loc[test.index]
    rows.append({"test month": test_month, "train days": len(train),
                 "MAE naive": (test["y"] - naive).abs().mean(), "MAE M1": np.abs(test["y"] - pred).mean(),
                 "MAPE naive": ((test["y"] - naive).abs() / test["y"]).mean(),
                 "MAPE M1": (np.abs(test["y"] - pred) / test["y"]).mean()})
bt = pd.DataFrame(rows).set_index("test month")
bt["M1 better by"] = 1 - bt["MAE M1"] / bt["MAE naive"]
log.table("Backtest by month (each month predicted only from earlier months)", bt.round(3))
log(f"M1 beats the naive baseline in {(bt['M1 better by'] > 0).sum()} of {len(bt)} months; "
    f"average MAE improvement {bt['M1 better by'].mean():.0%}.")
bt.to_csv(OUT / "backtest.csv")

fig, ax = plt.subplots(figsize=(7, 3.5))
xs = np.arange(len(bt))
ax.bar(xs - 0.2, bt["MAPE naive"] * 100, width=0.4, color="#a0aec0", label="naive: same weekday last week")
ax.bar(xs + 0.2, bt["MAPE M1"] * 100, width=0.4, color="#2b6cb0", label="M1: weekday + trend")
ax.set_xticks(xs, ["Mar", "Apr", "May", "Jun"])
ax.set(ylabel="Forecast error, MAPE (%)", title="The model beats the baseline in every test month")
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "13_backtest.png", dpi=150); plt.close(fig)

# ================================================================ 2. Bootstrap the $ values
log("\n# 2. Bootstrap: how uncertain are the main $ values? (resample days, 1,000 times)")
unit = d.groupby(["Product", "Branch"]).agg(cost=(COST, "first"), price=(PRICE, "first")).unstack()
g = d[d["Branch"] == "Garden"].copy()
g["harbour_cost"] = g["Product"].map(unit["cost"]["Harbour"])
g["x"] = g["Product"].map(unit["price"]["Harbour"] / unit["price"]["Garden"] - 1)
g["excess"] = g["cogs"] - g["Quantity"] * g["harbour_cost"]
g["gain_e0"] = g["Quantity"] * g[PRICE] * g["x"]
g["gain_e1"] = g["Quantity"] * ((1 - g["x"]) * (g[PRICE] * (1 + g["x"]) - g[COST]) - (g[PRICE] - g[COST]))
by_day = g.groupby("dt")[["excess", "gain_e0", "gain_e1"]].sum()
n = len(by_day)
boots = np.array([by_day.iloc[rng.integers(0, n, n)].sum().values for _ in range(1000)]) * 365 / n
ci = pd.DataFrame({"point (per yr)": by_day.sum().values * 365 / n,
                   "95% low": np.percentile(boots, 2.5, axis=0), "95% high": np.percentile(boots, 97.5, axis=0)},
                  index=["Garden cost gap", "Garden +5% price, elasticity 0", "Garden +5% price, elasticity -1"])
log.table("Annualised $ values with bootstrap 95% intervals (ESTIMATE; day-level resampling of H1, x365/181)", ci.round(0))
log("These intervals capture sampling noise in volume only. The bigger uncertainties are the assumptions "
    "(is the cost gap real cash? what is elasticity?), handled by scenario tables in scripts 02 and 05.")

# ================================================================ 3. Robustness of the main number to data choices
log("\n# 3. Does the Garden cost gap survive different data choices? ($/yr, per-day x 365)")
raw_cols = pd.read_csv(OUT.parent / "stories_transactions.csv", nrows=0).columns.tolist()
dup = d.duplicated(raw_cols)
def gap_per_year(mask):
    sub = g.loc[mask.reindex(g.index, fill_value=False)]
    return sub["excess"].sum() / sub["dt"].nunique() * 365
choices = {
    "all data": pd.Series(True, index=d.index),
    "drop exact duplicate rows": ~dup,
    "drop promo weeks": ~d["dt"].isin(PROMO_DAYS),
    "Jan-Mar only": d["month"] <= 3,
    "Apr-Jun only": d["month"] >= 4,
    "June only (run-rate)": d["month"] == 6,
}
rob = pd.Series({k: gap_per_year(v) for k, v in choices.items()}).to_frame("cost gap $/yr")
rob["vs all data"] = rob["cost gap $/yr"] / rob.loc["all data", "cost gap $/yr"] - 1
log.table("Garden cost gap under different data choices", rob.round(3))
log("The gap moves only with volume (later months are bigger because of growth); the cost ratio itself never changes. "
    "Data-cleaning choices move it by about 1% or less.")

# ================================================================ 4. Deeper data audit
log("\n# 4. Deeper data audit")
tx = d.groupby("Transaction ID").agg(cust=("Customer ID", "first"), Branch=("Branch", "first"),
                                     ts=("Date", "first"), time=("Time", "first"))
tx["ts"] = pd.to_datetime(tx["ts"] + " " + tx["time"])
k = tx.dropna(subset=["cust"]).sort_values(["cust", "ts"])
k["prev_ts"] = k.groupby("cust")["ts"].shift()
k["prev_branch"] = k.groupby("cust")["Branch"].shift()
k["mins"] = (k["ts"] - k["prev_ts"]).dt.total_seconds() / 60
same_5 = ((k["mins"] <= 5) & (k["Branch"] == k["prev_branch"])).sum()
other_30 = ((k["mins"] <= 30) & (k["Branch"] != k["prev_branch"])).sum()
same_day_two = k.assign(day=k["ts"].dt.date).groupby(["cust", "day"])["Branch"].nunique()
log(f"Same customer, 2 transactions at the same branch within 5 minutes (possible split orders): {same_5}")
log(f"Same customer at two DIFFERENT branches within 30 minutes (possible shared IDs): {other_30}")
log(f"Customer-days with visits to 2+ branches: {(same_day_two > 1).sum()} of {len(same_day_two):,}")
avail = d.groupby("Product")["Branch"].nunique()
log(f"Products sold at all 3 branches: {(avail == 3).sum()} of {len(avail)}")
hourly = d.groupby(["dt", "hour"])["Transaction ID"].nunique()
log(f"Busiest single hour in the data: {hourly.max()} transactions ({hourly.idxmax()[0].date()} {hourly.idxmax()[1]}:00); "
    f"99th percentile hour: {hourly.quantile(0.99):.0f} -> no extreme spikes")
log(f"Customer IDs: {d['Customer ID'].nunique():,} used out of the range C00001-{d['Customer ID'].dropna().max()}")
log("Conclusion: no structural problems in the transaction records themselves. Split orders (3) are negligible; 23 cases "
    "of one ID at two branches within 30 minutes (0.1% of identified visits) suggest occasional shared IDs. NOTE: the "
    "broader validity of Customer IDs is tested separately in script 13, which finds no detectable persistence; "
    "ID-based conclusions are withdrawn there.")
