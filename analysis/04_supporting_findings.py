"""Supporting findings: (1) discount weeks did not raise traffic, (2) the 'falling new customers'
trend is a data artifact, (3) Tuesday traffic is ~1.65x all other days (~1.5x other weekdays) with unchanged baskets."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from common import FIG, GP, REV, Log, load

log = Log("04_supporting_findings")
d = load()

# ---------------------------------------------------------------- 1. Discount weeks
day = d.groupby("dt").agg(disc_share=("discounted", "mean"))
day["promo"] = day["disc_share"] > 0.12
log("# 1. Discount weeks")
runs = day.index[day["promo"]]
log(f"Days where >12% of lines are discounted (normal ~6%): {len(runs)} -> "
    f"{runs.min().date()}..{runs[runs < '2026-04-01'].max().date()} and "
    f"{runs[runs > '2026-04-01'].min().date()}..{runs.max().date()}")
promo_days = set(pd.date_range("2026-03-12", "2026-03-19")) | set(pd.date_range("2026-05-12", "2026-05-19"))
log(f"Defined promo windows: 2026-03-12..19 and 2026-05-12..19 ({len(promo_days)} days)")

bd = d.groupby(["dt", "Branch"]).agg(txns=("Transaction ID", "nunique"), revenue=(REV, "sum"), gp=(GP, "sum"),
                                     discount_given=("list_rev", "sum")).reset_index()
bd["discount_given"] -= bd["revenue"]
bd["promo"] = bd["dt"].isin(promo_days).astype(int)
bd["dow"] = bd["dt"].dt.day_name()
bd["t"] = (bd["dt"] - bd["dt"].min()).dt.days
bd["phase"] = pd.cut(bd["dt"].dt.day, [0, 7, 14, 21, 31], labels=["d01-07", "d08-14", "d15-21", "d22-31"])

# Monthly cycle, estimated on NON-promo days only so promos cannot create it.
cyc = smf.ols("np.log(txns) ~ C(phase) + C(dow) + C(Branch) + t", data=bd[bd["promo"] == 0]).fit(cov_type="HC1")
cycle = pd.DataFrame({"effect vs days 1-7": np.expm1(cyc.params.filter(like="phase")),
                      "p-value": cyc.pvalues.filter(like="phase")})
log.table("Within-month traffic cycle on non-promo days (controls: weekday, branch, trend)", cycle.round(3))
log("Traffic peaks in the first week of each month and dips mid-month (consistent with a payday cycle - "
    "an assumption, the data has no income information). Both promo weeks (12th-19th) sit in the dip.")

rows = []
for label, extra in [("naive: weekday+branch+trend", ""), ("+ within-month cycle (preferred)", " + C(phase)")]:
    for y in ["txns", "revenue", "gp"]:
        fit = smf.ols(f"np.log({y}) ~ promo + C(dow) + C(Branch) + t{extra}", data=bd).fit(cov_type="HC1")
        lo, hi = fit.conf_int().loc["promo"]
        rows.append({"model": label, "outcome": y, "promo effect": np.expm1(fit.params["promo"]),
                     "95% CI low": np.expm1(lo), "95% CI high": np.expm1(hi), "p-value": fit.pvalues["promo"]})
eff = pd.DataFrame(rows).set_index(["model", "outcome"])
log.table("Promo-week effect (OLS on log daily values, 3 branches x 181 days, robust SEs)", eff.round(3))

promo = bd[bd["promo"] == 1]
pref = eff.loc["+ within-month cycle (preferred)"]
log(f"Discount given in promo windows: ${promo['discount_given'].sum():,.0f}; "
    f"all year-to-date discounts: ${bd['discount_given'].sum():,.0f}")
log("First explanation (naive model): promos cut gross profit by ~4% (p=0.03). Challenged: once the mid-month "
    f"dip is controlled, the traffic effect is {pref.loc['txns', 'promo effect']:+.1%} "
    f"(95% CI {pref.loc['txns', '95% CI low']:+.1%} to {pref.loc['txns', '95% CI high']:+.1%}) and the profit "
    "effect is no longer significant. Conclusion: no evidence the discounts brought extra customers; "
    "most of the apparent loss was the normal mid-month dip.")
log("Remaining caveat: events (exams, holidays) in those weeks could still hide a positive effect. "
    "Stories should check its own calendar for these dates.")

# ---------------------------------------------------------------- 2. New-customer artifact
log("\n# 2. 'New customers are collapsing' is an artifact")
known = d.dropna(subset=["Customer ID"])
first = known.groupby("Customer ID")["month"].min()
monthly = pd.DataFrame({
    "first-seen customers": first.value_counts().sort_index(),
    "active identified customers": known.groupby("month")["Customer ID"].nunique(),
    "identified txns": known.groupby("month")["Transaction ID"].nunique(),
    "anonymous txns": d[d["Customer ID"].isna()].groupby("month")["Transaction ID"].nunique(),
})
monthly["visits per active customer"] = monthly["identified txns"] / monthly["active identified customers"]
log.table("Monthly customer metrics (observed)", monthly.round(2))
log(f"Total identified customers: {known['Customer ID'].nunique():,}. The ID pool is closed (no ID beyond "
    f"{known['Customer ID'].max()}), and 57% of all IDs appear already in January.")
log("A naive reading says acquisition fell 99% (1,979 -> 20). But a customer can only be 'new' once; "
    "with a fixed pool of frequent visitors (avg gap between visits ~24 days), first sightings must "
    "front-load. Active customers actually GREW 28% and visits per customer grew 21%; anonymous traffic "
    "grew 49%. Using 'first-seen' as an acquisition KPI on this data would trigger a wrong decision.")

# ---------------------------------------------------------------- 3. Tuesday
log("\n# 3. Tuesday effect")
tx = d.groupby("Transaction ID").agg(dt=("dt", "first"), revenue=(REV, "sum"), items=("Quantity", "sum"),
                                     disc=("discounted", "max"), known=("Customer ID", lambda s: s.notna().any()))
tx["tuesday"] = tx["dt"].dt.dayofweek == 1
per_day = tx.groupby("dt").size()
dow_avg = per_day.groupby(per_day.index.day_name()).mean().reindex(
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
log.table("Average transactions per day by weekday (all branches)", dow_avg.round(0).to_frame("txns/day"))
log.table("Basket and customer mix: Tuesday vs other days",
          tx.groupby("tuesday")[["revenue", "items", "disc", "known"]].mean().round(3))
tue_by_branch = bd.assign(tue=bd["dt"].dt.dayofweek == 1).groupby(["Branch", "tue"])["txns"].mean().unstack()
log.table("Tuesday multiplier by branch", (tue_by_branch[True] / tue_by_branch[False]).round(2).to_frame("x"))
log("Tuesday's extra revenue comes entirely from more visits, not bigger baskets or discounts, at every "
    "branch. The multipliers above compare Tuesday with ALL other days incl. the weekend (~1.65x); against "
    "Mon/Wed/Thu/Fri only it is ~1.5x (+53%, script 06). Staff and stock to ~1.5x vs a normal weekday; "
    "Stories should identify the driver before trying to copy it.")

# ---------------------------------------------------------------- Figures
fig, ax = plt.subplots(figsize=(7, 4))
ax.bar(monthly.index - 0.2, monthly["first-seen customers"], width=0.4, color="#a0aec0", label="'new' (first-seen) customers")
ax.bar(monthly.index + 0.2, monthly["active identified customers"], width=0.4, color="#2b6cb0", label="active customers")
ax.set_xticks(range(1, 7), ["Jan", "Feb", "Mar", "Apr", "May", "Jun"])
ax.set(ylabel="Customers", title="'New customers' collapse while active customers grow")
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "06_new_customer_artifact.png", dpi=150); plt.close(fig)

tot = bd.groupby("dt")[["txns"]].sum()
tot["disc_share"] = day["disc_share"]
fig, ax = plt.subplots(figsize=(9, 4))
ax.plot(tot.index, tot["txns"].rolling(7, center=True).mean(), color="#2b6cb0", label="transactions/day (7-day avg)")
for a, b in [("2026-03-12", "2026-03-19"), ("2026-05-12", "2026-05-19")]:
    ax.axvspan(pd.Timestamp(a), pd.Timestamp(b), color="#f6ad55", alpha=0.35)
ax.set(ylabel="Transactions / day", title="Discount weeks (shaded) show no traffic lift")
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "07_promo_weeks.png", dpi=150); plt.close(fig)
