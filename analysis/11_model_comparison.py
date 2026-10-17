"""Model check for the pilot counterfactual: stronger baselines, ML models, honest uncertainty, and whether a
company-level profit metric is detectable at all. Every model is tested only on months it never saw."""
import os

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "4")  # silences a harmless joblib core-count warning on Windows
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, PoissonRegressor

from common import FIG, GP, OUT, Log, load

log = Log("11_model_comparison")
d = load()
PROMO_DAYS = set(pd.date_range("2026-03-12", "2026-03-19")) | set(pd.date_range("2026-05-12", "2026-05-19"))
TEST_MONTHS = [3, 4, 5, 6]


def daily_series(frame, value):
    s = (frame.groupby("dt")["Transaction ID"].nunique() if value == "txns" else frame.groupby("dt")[GP].sum())
    s = s.reindex(pd.date_range(d["dt"].min(), d["dt"].max()), fill_value=0).to_frame("y")
    s["dow"] = s.index.dayofweek
    s["t"] = np.arange(len(s), dtype=float)
    s["dom"] = s.index.day
    s["promo"] = s.index.isin(PROMO_DAYS).astype(float)
    return s


def onehot(df):
    X = pd.get_dummies(df["dow"], prefix="dow").astype(float).reindex(columns=[f"dow_{i}" for i in range(1, 7)], fill_value=0.0)
    X["t"] = df["t"]
    return X


def tree_X(df):
    return df[["dow", "t", "dom", "promo"]]


MODELS = {
    "B1 naive: same weekday last week": None,
    "B2 baseline: mean of last 4 same weekdays": None,
    "M1 log-linear: weekday + trend (chosen)": lambda tr, te: np.exp(
        LinearRegression().fit(onehot(tr), np.log(tr["y"])).predict(onehot(te))),
    "M4 Poisson GLM: weekday + trend": lambda tr, te: PoissonRegressor(alpha=1e-6, max_iter=1000).fit(
        onehot(tr).assign(t=tr["t"] / 100), tr["y"]).predict(onehot(te).assign(t=te["t"] / 100)),
    "M5 gradient boosting: weekday, day, day-of-month, promo": lambda tr, te: HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.05, random_state=0).fit(tree_X(tr), tr["y"]).predict(tree_X(te)),
    "M6 random forest: same features": lambda tr, te: RandomForestRegressor(
        n_estimators=300, min_samples_leaf=3, random_state=0).fit(tree_X(tr), tr["y"]).predict(tree_X(te)),
}


def backtest(s):
    rows, preds = [], {}
    for m in TEST_MONTHS:
        tr, te = s[s.index.month < m], s[s.index.month == m]
        for name, fn in MODELS.items():
            if name.startswith("B1"):
                p = s["y"].shift(7).loc[te.index].values
            elif name.startswith("B2"):
                p = sum(s["y"].shift(7 * k).loc[te.index].values for k in range(1, 5)) / 4
            else:
                p = fn(tr, te)
            err = te["y"].values - p
            rows.append({"model": name, "test month": m, "MAE": np.abs(err).mean(), "MAPE": (np.abs(err) / te["y"].values).mean()})
            preds[(name, m)] = pd.Series(p, index=te.index)
    res = pd.DataFrame(rows)
    table = res.pivot(index="model", columns="test month", values="MAPE")
    table["average MAPE"] = table.mean(axis=1)
    table["months best"] = (res.loc[res.groupby("test month")["MAPE"].idxmin(), "model"].value_counts()
                            .reindex(table.index, fill_value=0))
    return table.sort_values("average MAPE"), preds


# ================================================================ 1. Garden daily traffic: baselines vs linear vs ML
log("# 1. Garden daily transactions: rolling backtest (train on all earlier months, test on the next month)")
garden = daily_series(d[d["Branch"] == "Garden"], "txns")
tbl, preds = backtest(garden)
log.table("MAPE by test month (lower is better)", tbl.round(3))
tbl.to_csv(OUT / "model_comparison_garden.csv")
best_ml = tbl.loc[[i for i in tbl.index if i.startswith(("M5", "M6"))], "average MAPE"].min()
log(f"\nM1 average MAPE {tbl.loc['M1 log-linear: weekday + trend (chosen)', 'average MAPE']:.1%} vs strongest baseline "
    f"{tbl.loc[[i for i in tbl.index if i.startswith('B')], 'average MAPE'].min():.1%} vs best tree model {best_ml:.1%}.")
log("Why the tree models lose: they cannot extrapolate the growth trend - every test month has more traffic than any "
    "training month, and a tree can only predict values it has seen. With +8.5%/month growth this is a structural "
    "failure, not a tuning problem. Complexity does not help here; we keep the simple, explainable M1.")

# ================================================================ 2. Is the uncertainty honest? Interval coverage
log("\n# 2. Prediction-interval coverage for M1 (do 80%/95% intervals contain 80%/95% of unseen days?)")
cov_rows = []
for m in TEST_MONTHS:
    tr, te = garden[garden.index.month < m], garden[garden.index.month == m]
    lr = LinearRegression().fit(onehot(tr), np.log(tr["y"]))
    sd = (np.log(tr["y"]) - lr.predict(onehot(tr))).std(ddof=onehot(tr).shape[1] + 1)
    mu = lr.predict(onehot(te))
    for level, z in [(0.80, 1.2816), (0.95, 1.96)]:
        inside = (np.log(te["y"]) >= mu - z * sd) & (np.log(te["y"]) <= mu + z * sd)
        cov_rows.append({"test month": m, "interval": f"{level:.0%}", "coverage": inside.mean()})
cov = pd.DataFrame(cov_rows).pivot(index="test month", columns="interval", values="coverage")
cov.loc["all months"] = pd.DataFrame(cov_rows).groupby("interval")["coverage"].mean()
log.table("Share of unseen days inside the interval (target: 80% and 95%)", cov.round(3))
log("Reading: daily interval coverage is a useful diagnostic of the forecast's uncertainty. It does not validate the "
    "monthly pilot decision probabilities, which are assessed separately (script 15).")

# ================================================================ 3. Can a company-level profit effect be detected at all?
log("\n# 3. Is the README's company-level metric detectable? (company gross profit per day)")
company = daily_series(d, "gp")
ctbl, _ = backtest(company)
log.table("Company GP/day: MAPE by test month", ctbl.round(3))
tr, te = company[company.index.month < 5], company[company.index.month >= 5]
lr = LinearRegression().fit(onehot(tr), np.log(tr["y"]))
sd_c = (np.log(te["y"]) - lr.predict(onehot(te))).std()
mde_c = 2.8 * sd_c / np.sqrt(30)
gp_day = te["y"].mean()
expected = {"elasticity 0": 9972, "elasticity -1, nobody switches": 4797}
log(f"Company GP/day in May-Jun: ${gp_day:,.0f}. Smallest detectable change in one calendar month (30 days, 5% test, "
    f"80% power): {mde_c:.1%} = ${mde_c * gp_day:,.0f}/day.")
for k, v in expected.items():
    log(f"Expected effect of +5% at Garden ({k}): ${v / 365:,.0f}/day = {v / 365 / gp_day:.1%} of company GP/day -> "
        f"{'detectable' if v / 365 / gp_day > mde_c else 'NOT detectable'} directly.")
log("Conclusion: the company-level profit effect of a Garden price rise (~1-3% of company GP) is far below what one month "
    "can detect. Judging the pilot on company GP directly would almost always say 'no effect'. Design used instead "
    "(scripts 14-15): measure Garden's traffic vs the frozen M1 forecast, cross-check against Garden / (Harbour + Uptown), "
    "and decide with a one-sided bound. (Customer IDs cannot measure switching - script 13.)")

# ================================================================ Figure
fig, ax = plt.subplots(figsize=(8, 4))
order = tbl.index.tolist()
colors = ["#2b6cb0" if n.startswith("M1") else "#a0aec0" if n.startswith("B") else "#c05621" if n.startswith(("M5", "M6"))
          else "#718096" for n in order]
ax.barh(range(len(order)), tbl["average MAPE"] * 100, color=colors)
short = {"B1": "B1 naive (last week)", "B2": "B2 mean of last 4 weeks", "M1": "M1 linear (chosen)",
         "M4": "M4 Poisson GLM", "M5": "M5 gradient boosting", "M6": "M6 random forest"}
ax.set_yticks(range(len(order)), [short[n[:2]] for n in order], fontsize=9)
ax.invert_yaxis()
ax.set(xlabel="Average error on unseen months, MAPE (%)", title="Simple model beats baselines and ML models")
fig.tight_layout(); fig.savefig(FIG / "16_model_comparison.png", dpi=150); plt.close(fig)
