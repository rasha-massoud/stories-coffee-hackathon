"""Garden price pilot: how reliable is the keep/stop decision?

We backtest the pilot's actual measurement - the AGGREGATE change in Garden transactions over the pilot window vs a
forecast FROZEN at the start of the window - for 1-month and 2-month horizons from every possible origin. Then we compare
two keep rules under a normal approximation calibrated to those errors, with explicit bias sensitivity. With only six
months of history there are few independent windows, so these are approximations, not validated guarantees."""
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.linear_model import LinearRegression

from common import OUT, Log, load

log = Log("15_pilot_decision_rule")
d = load()
daily = d[d["Branch"] == "Garden"].groupby("dt")["Transaction ID"].nunique().to_frame("y")
daily["dow"] = daily.index.dayofweek
daily["t"] = np.arange(len(daily), dtype=float)


def X(df):
    out = pd.get_dummies(df["dow"], prefix="dow").astype(float).reindex(columns=[f"dow_{i}" for i in range(1, 7)], fill_value=0.0)
    out["t"] = df["t"]
    return out


# ================================================================ 1. Fixed-origin backtest of the pilot measurement
rows = []
for horizon in [1, 2]:
    for start in range(3, 8 - horizon):  # need >= 2 training months; windows must end by June
        tr = daily[daily.index.month < start]
        te = daily[(daily.index.month >= start) & (daily.index.month < start + horizon)]
        pred = np.exp(LinearRegression().fit(X(tr), np.log(tr["y"])).predict(X(te)))
        rows.append({"horizon (months)": horizon, "window": f"{start}-{start + horizon - 1}", "train months": start - 1,
                     "aggregate error (actual/forecast - 1)": te["y"].sum() / pred.sum() - 1})
bt = pd.DataFrame(rows)
log("# Garden price pilot: reliability of the keep/stop decision")
log.table("Fixed-origin backtest: aggregate Garden transactions vs a forecast frozen at the window start (observed)",
          bt.set_index(["horizon (months)", "window"]).round(4))
err = {h: g["aggregate error (actual/forecast - 1)"] for h, g in bt.groupby("horizon (months)")}
rms = {h: float(np.sqrt((e ** 2).mean())) for h, e in err.items()}
log(f"Root-mean-square aggregate error: 1 month {rms[1]:.1%} ({len(err[1])} windows), 2 months {rms[2]:.1%} "
    f"({len(err[2])} overlapping windows). The 2-month error is NOT smaller than the 1-month error: a frozen trend drifts, "
    "so a longer pilot does not automatically measure more precisely.")
# Calibrated measurement error. With so few windows the empirical RMS can come out BELOW what day-to-day noise alone
# implies, so floor it at the pure-noise level (within-window daily sd of log errors / sqrt(days)).
resid = []
for start in range(3, 7):
    tr, te = daily[daily.index.month < start], daily[daily.index.month == start]
    resid.append(np.log(te["y"]) - LinearRegression().fit(X(tr), np.log(tr["y"])).predict(X(te)))
daily_sd = float(np.mean([r.std() for r in resid]))
noise = {h: daily_sd / np.sqrt(30 * h) for h in [1, 2]}
s = {h: max(rms[1], rms[h], noise[h]) for h in [1, 2]}
log(f"Pure daily-noise floor: {noise[1]:.1%} (1 month), {noise[2]:.1%} (2 months), from a daily sd of {daily_sd:.3f}.")
log(f"Measurement error used below = max(empirical RMS, noise floor): {s[1]:.1%} (1 month), {s[2]:.1%} (2 months). "
    "Few windows -> treat as approximate.")
log(f"Smallest drop detectable with 80% power (5% test): ~{2.8 * s[1]:.1%} in 1 month, ~{2.8 * s[2]:.1%} in 2 months. "
    "This supersedes script 14's ~8% figure, which added daily noise on top of monthly errors that already contain it.")

# Same method for the cross-check metric: Garden / (Harbour + Uptown) transactions, 1-month fixed-origin windows.
allb = d.groupby(["dt", "Branch"])["Transaction ID"].nunique().unstack()
ratio = (allb["Garden"] / (allb["Harbour"] + allb["Uptown"])).to_frame("y")
ratio["dow"] = ratio.index.dayofweek
ratio["t"] = np.arange(len(ratio), dtype=float)
r_err, r_res = [], []
for start in range(3, 7):
    tr, te = ratio[ratio.index.month < start], ratio[ratio.index.month == start]
    mdl = LinearRegression().fit(X(tr), np.log(tr["y"]))
    pred = np.exp(mdl.predict(X(te)))
    w = allb.loc[te.index, ["Harbour", "Uptown"]].sum(axis=1)  # weight days by the denominator, as the monthly ratio does
    r_err.append((te["y"] * w).sum() / (pred * w).sum() - 1)
    r_res.append(np.log(te["y"]) - mdl.predict(X(te)))
r_rms = float(np.sqrt(np.mean(np.square(r_err))))
r_noise = float(np.mean([r.std() for r in r_res])) / np.sqrt(30)
r_s = max(r_rms, r_noise)
log(f"Cross-check metric, same method: monthly errors {', '.join(f'{e:+.1%}' for e in r_err)}; RMS {r_rms:.1%}; noise floor "
    f"{r_noise:.1%}; measurement error {r_s:.1%} vs {s[1]:.1%} for the primary ({r_s / s[1]:.1f}x).")

# ================================================================ 2. Keep probabilities under each rule
# Break-even volume loss depends on which costs are avoidable:
CASES = {"real premium NOT yet recovered (avoidable cost = Garden's)": 0.096,
         "cost fixed, OR 1.43 is an allocation (avoidable cost = Harbour's)": 0.074}
rows = []
for months in [1, 2]:
    for case, be in CASES.items():
        for bias in [-0.02, 0.0, 0.02]:  # forecast bias: + means the forecast under-predicts (loss looks smaller)
            for L in [0.0, 0.02, 0.05, 0.074, 0.096, 0.12, 0.15]:
                mu = L - bias  # measured loss
                rows.append({"months": months, "case": case, "forecast bias": bias, "true loss": L,
                             "naive: keep if measured loss < break-even": norm.cdf((be - mu) / s[months]),
                             "one-sided: keep if measured loss < break-even - 1.645 x error": norm.cdf((be - 1.645 * s[months] - mu) / s[months]),
                             "profit if kept": "gain" if L < be else ("zero (boundary)" if L == be else "LOSS")})
res = pd.DataFrame(rows)
res.to_csv(OUT / "pilot_decision_rule.csv", index=False)
for (months, case), g in res[res["forecast bias"] == 0].groupby(["months", "case"]):
    log.table(f"P(keep), {months}-month fixed-horizon pilot, {case}, zero bias (normal approximation)",
              g.set_index("true loss")[["naive: keep if measured loss < break-even",
                                        "one-sided: keep if measured loss < break-even - 1.645 x error", "profit if kept"]].round(3))
sens = res[res["true loss"].isin([0.0, 0.12])].pivot_table(
    index=["months", "case", "true loss"], columns="forecast bias",
    values="one-sided: keep if measured loss < break-even - 1.645 x error").round(3)
log.table("Bias sensitivity of the one-sided rule: P(keep) for a harmless (0%) and a harmful (12%) loss", sens)

for months in [1, 2]:
    for case, be in CASES.items():
        log(f"{months}-month pilot, {case}: keep only if measured loss < {be - 1.645 * s[months]:.1%}")
sens_err = pd.DataFrame({f"keep threshold, {case.split(' (')[0]}": {f"{e:.1%}": be - 1.645 * e for e in [s[1], 0.03, 0.04]}
                         for case, be in CASES.items()})
sens_err.index.name = "assumed monthly measurement error"
log.table("Sensitivity of the 1-month keep threshold to the assumed measurement error (planning table)",
          sens_err.apply(lambda col: col.map(lambda v: f"{v:.1%}")))
log("The 2.1% error is a planning convention from four windows, not a validated bound. Recalibrate it on recent "
    "pre-pilot POS data before running the pilot; a larger error makes the keep threshold much stricter.")

# Basket guardrail: how much do Garden's units and GP per transaction normally move month to month?
gt = d[d["Branch"] == "Garden"].groupby("Transaction ID").agg(m=("month", "first"), units=("Quantity", "sum"),
                                                              gp=("Line Gross Profit (USD)", "sum"))
bm = gt.groupby("m")[["units", "gp"]].mean()
log.table("Garden basket by month (observed): units and GP per transaction", bm.round(3))
log(f"Normal month-to-month range: units/txn {bm['units'].max() / bm['units'].min() - 1:.1%}, GP/txn "
    f"{bm['gp'].max() / bm['gp'].min() - 1:.1%}. Guardrail: if pilot-month units/txn falls more than 3% below the pre-pilot "
    "average, the transaction metric no longer reflects profit, so the result is classed inconclusive (revert).")

log("\nReading (zero bias, normal approximation): at the zero-profit boundary the naive rule keeps the rise ~50% of the "
    "time and the one-sided rule ~5% - by construction, not a validated error rate. What matters commercially: the one-sided "
    "rule rarely keeps a clearly harmful rise (12% loss), but it also often rejects profitable ones, especially when the "
    "break-even is 7.4% (after a cost fix, or if the 1.43 is an allocation). A 2-month pilot is not more precise than a "
    "1-month pilot here, because the frozen trend drifts; it mainly averages the turn-of-month cycle.")
log("Protocol this supports: ONE calendar month, fixed horizon, one-sided rule with the threshold for the applicable cost "
    "case. Anything else - inconclusive range, failed basket guardrail, or cross-check disagreeing - means revert prices. "
    "A day-14 safety stop (traffic down > 15%) is an override whose effect on these probabilities is not estimated. The "
    "probabilities above describe ONLY the simplified one-month traffic rule. Limits: 4 one-month and 3 overlapping "
    "two-month windows; tail risks cannot be validated.")
