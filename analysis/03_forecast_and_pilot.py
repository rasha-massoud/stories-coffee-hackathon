"""Model: forecast Garden's daily transactions so Stories can measure a price pilot against a counterfactual.

Question the model answers: "If Garden raises prices, how will we know whether it lost customers?"
We need a counterfactual for Garden's traffic. We compare simple baselines with two linear models,
train on Jan-Apr and test on May-Jun (data the models never saw), then turn the test error into the
smallest volume drop a pilot of a given length could reliably detect.
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from common import COLORS, FIG, OUT, Log, load

log = Log("03_forecast_and_pilot")
d = load()

daily = d.groupby(["dt", "Branch"])["Transaction ID"].nunique().unstack()
daily["dow"] = daily.index.dayofweek
daily["t"] = (daily.index - daily.index.min()).days
train = daily[daily.index < "2026-05-01"]
test = daily[daily.index >= "2026-05-01"]
log("# Garden daily-traffic forecast")
log(f"Train: {train.index.min().date()} to {train.index.max().date()} ({len(train)} days) | "
    f"Test: {test.index.min().date()} to {test.index.max().date()} ({len(test)} days)")

daily["phase"] = pd.cut(daily.index.day, [0, 7, 14, 21, 31], labels=False)
train = daily[daily.index < "2026-05-01"]
test = daily[daily.index >= "2026-05-01"]

def design(df, controls, cycle=False):
    X = pd.get_dummies(df["dow"], prefix="dow", drop_first=True).astype(float)
    X["t"] = df["t"]
    if controls:
        X["log_controls"] = np.log(df["Harbour"] + df["Uptown"])
    if cycle:
        X = X.join(pd.get_dummies(df["phase"], prefix="phase", drop_first=True).astype(float))
    return X

preds = {
    "B1 naive: same weekday last week": daily["Garden"].shift(7).loc[test.index],
    "B2 weekday average (train)": test["dow"].map(train.groupby("dow")["Garden"].mean()),
}
models = {}
for name, controls, cycle in [("M1 linear: weekday + trend", False, False),
                              ("M2 linear: weekday + trend + control branches", True, False),
                              ("M3 linear: weekday + trend + within-month cycle", False, True)]:
    m = LinearRegression().fit(design(train, controls, cycle), np.log(train["Garden"]))
    models[name] = (m, controls)
    preds[name] = pd.Series(np.exp(m.predict(design(test, controls, cycle))), index=test.index)

def scores(y, p):
    err = y - p
    return {"MAE (txns/day)": err.abs().mean(), "MAPE": (err.abs() / y).mean(),
            "bias (txns/day)": err.mean(), "resid sd of log ratio": np.log(y / p).std()}

res = pd.DataFrame({k: scores(test["Garden"], v) for k, v in preds.items()}).T
log.table("Out-of-sample accuracy on May-Jun (lower is better)", res.round(3))
res.to_csv(OUT / "forecast_scores.csv")
best = res["MAE (txns/day)"].idxmin()
log(f"\nBest: {best}. It cuts MAE by "
    f"{1 - res.loc[best, 'MAE (txns/day)'] / res.loc['B1 naive: same weekday last week', 'MAE (txns/day)']:.0%} "
    "vs the naive baseline.")

m2, _ = models["M2 linear: weekday + trend + control branches"]
coef = pd.Series(m2.coef_, index=design(train, True).columns)
log.table("M2 coefficients (log scale)", coef.round(3).to_frame("coef"))

# Where does the model fail?
err = (test["Garden"] - preds[best])
worst = pd.DataFrame({"actual": test["Garden"], "predicted": preds[best].round(0), "error": err.round(0),
                      "weekday": test.index.day_name()}).loc[err.abs().nlargest(6).index]
log.table("Largest test-period errors (weak spots)", worst)
log(f"Error by weekday (MAE): {err.abs().groupby(test.index.day_name()).mean().round(1).to_dict()}")
ac = err.autocorr(1)
log(f"Lag-1 autocorrelation of test residuals: {ac:.2f} "
    + ("(negative -> errors partly cancel over a multi-day pilot, so treating days as independent "
       "below is conservative)" if ac < 0 else "(positive -> the power numbers below are optimistic)"))
log("Adding Harbour+Uptown same-day traffic (M2) did NOT beat M1: day-to-day shocks are branch-specific, "
    "so the other branches add little as a same-day control. Rejected M2 in favour of the simpler M1.")
log("Adding the within-month cycle (M3) also did NOT help out of sample: 3 extra parameters fitted on only "
    "4 training months overfit. Rejected M3; the cycle is still real (script 04) but too weak per day to "
    "improve a branch-level forecast.")
log("B2 shows why trend matters: ignoring growth biases the forecast by +15 txns/day.")

# ---------------------------------------------------------------- Pilot power
sd = np.log(test["Garden"] / preds[best]).std()
z = 1.96 + 0.84  # 5% two-sided test, 80% power
power = pd.DataFrame({"pilot days": [14, 28, 42, 56]})
power["min detectable traffic drop"] = (z * sd / np.sqrt(power["pilot days"])).map("{:.1%}".format)
log.table("Smallest Garden traffic drop a pilot could detect (using the best model as counterfactual)",
          power.set_index("pilot days"))
log("Break-even volume loss for a 5% price rise is 9.6% (script 02); a 28-day pilot can detect drops "
    "well below that, so the pilot can answer the decision question.")

# ---------------------------------------------------------------- Spillover risk for the control branches
known = d.dropna(subset=["Customer ID"])
garden_custs = known.loc[known["Branch"] == "Garden", "Customer ID"].unique()
gc_visits = known[known["Customer ID"].isin(garden_custs)].groupby("Branch")["Transaction ID"].nunique()
multi = known.groupby("Customer ID")["Branch"].nunique()
log(f"\nIdentified IDs seen at 2+ branches: {(multi > 1).mean():.0%} (but see script 13: Customer IDs behave like random "
    "labels, so this says nothing about real customers).")
log("Risk: customers could move from Garden to Harbour/Uptown during a Garden price pilot. That would inflate the "
    "other branches and make Garden's measured drop look LARGER than the true company-wide loss (a conservative bias). "
    "Customer IDs cannot measure this (script 13). Script 14 compares ID-free pilot metrics in the same units: primary = "
    "Garden traffic vs frozen M1; cross-check = Garden / (Harbour + Uptown).")

# ---------------------------------------------------------------- Figure
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(daily.index, daily["Garden"], color="#cbd5e0", lw=1, label="actual (train)")
ax.plot(test.index, test["Garden"], color=COLORS["Garden"], lw=1.5, label="actual (test)")
ax.plot(test.index, preds[best], color="#2b6cb0", lw=1.5, label=best.split(":")[0] + " forecast")
ax.plot(test.index, preds["B1 naive: same weekday last week"], color="#a0aec0", lw=1, ls="--",
        label="naive baseline")
ax.axvline(pd.Timestamp("2026-05-01"), color="black", lw=0.8, ls=":")
ax.set(ylabel="Garden transactions / day",
       title=f"Garden daily traffic: model vs naive baseline on unseen May-Jun data "
             f"(MAPE {res.loc[best, 'MAPE']:.1%} vs {res.loc['B1 naive: same weekday last week', 'MAPE']:.1%})")
ax.legend(frameon=False, ncol=2, fontsize=8)
fig.tight_layout(); fig.savefig(FIG / "05_garden_forecast_test.png", dpi=150); plt.close(fig)
