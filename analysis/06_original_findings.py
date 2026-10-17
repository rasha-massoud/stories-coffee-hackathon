"""Original findings: (1) the mid-month dip - size, shape and whether it looks like a payday cycle,
(2) who the extra Tuesday customers are, (3) the evening margin mix."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import chi2_contingency

from common import BRANCHES, COLORS, FIG, GP, PRICE, REV, Log, load

log = Log("06_original_findings")
d = load()
PROMO_DAYS = set(pd.date_range("2026-03-12", "2026-03-19")) | set(pd.date_range("2026-05-12", "2026-05-19"))
PHASES = ["d01-07", "d08-14", "d15-21", "d22-31"]
d["phase"] = pd.cut(d["dt"].dt.day, [0, 7, 14, 21, 31], labels=PHASES)
d["promo"] = d["dt"].isin(PROMO_DAYS)


def branch_days(frame, **aggs):
    """Daily per-branch aggregates with the controls every regression in this script uses."""
    bd = frame.groupby(["dt", "Branch"]).agg(**aggs).reset_index()
    bd["dow"] = bd["dt"].dt.day_name()
    bd["t"] = (bd["dt"] - d["dt"].min()).dt.days
    bd["phase"] = pd.Categorical(pd.cut(bd["dt"].dt.day, [0, 7, 14, 21, 31], labels=PHASES), PHASES)
    bd["promo"] = bd["dt"].isin(PROMO_DAYS)
    return bd


def phase_effects(bd, y, extra=""):
    """% effect of each month phase vs days 1-7, controlling for weekday, branch and growth trend."""
    fit = smf.ols(f"np.log({y}) ~ C(phase) + C(dow) + C(Branch) + t{extra}", data=bd).fit(cov_type="HC1")
    eff = np.expm1(fit.params.filter(like="phase"))
    p = fit.pvalues.filter(like="phase")
    eff.index = p.index = [i.split("T.")[1].rstrip("]") for i in eff.index]
    return eff, p


# ================================================================ 1. Mid-month dip
log("# 1. Mid-month dip")
bd = branch_days(d, txns=("Transaction ID", "nunique"), revenue=(REV, "sum"), gp=(GP, "sum"),
                 items=("Quantity", "sum"))
bd["basket"] = bd["revenue"] / bd["txns"]
bd["items_per_txn"] = bd["items"] / bd["txns"]
bd["price_per_item"] = bd["revenue"] / bd["items"]
clean = bd[~bd["promo"]]
log(f"Non-promo branch-days used: {len(clean)} (promo weeks excluded so discounts cannot create the pattern)")

rows = {}
for y in ["txns", "revenue", "gp", "basket", "items_per_txn", "price_per_item"]:
    eff, p = phase_effects(clean, y)
    rows[y] = {**{f"{k} effect": v for k, v in eff.items()}, **{f"{k} p": v for k, v in p.items()}}
eff_tbl = pd.DataFrame(rows).T
log.table("Effect vs days 1-7 (observed, controls: weekday, branch, trend; robust SEs)", eff_tbl.round(3))
log("Reading: if the dip is visits only, txns falls but basket/items/price per item stay flat.")

# Shape: average residual by day of month after removing weekday, branch and trend.
base = smf.ols("np.log(txns) ~ C(dow) + C(Branch) + t", data=clean).fit()
clean = clean.assign(resid=base.resid, dom=clean["dt"].dt.day)
shape = clean.groupby("dom")["resid"].mean().pipe(np.expm1)
log.table("Traffic vs normal by day of month (observed, % vs weekday/branch/trend expectation)",
          (shape * 100).round(1).to_frame("% vs expected"))

# ---- Alternative explanations
log("\n## Alternative explanations")
# (a) One month driving it?
per_month = {}
for m, g in clean.groupby(clean["dt"].dt.month):
    eff, _ = phase_effects(g.assign(t=0), "txns")
    per_month[m] = eff
per_month = pd.DataFrame(per_month).T
log.table("(a) Phase effect on txns, estimated separately for each month (observed)", per_month.round(3))
log(f"Months where days 15-21 are below days 1-7: {(per_month['d15-21'] < 0).sum()} of {len(per_month)}")

# (b) Is it a weekday-composition artifact? Weekday dummies are already in the model; also check raw mix.
mix = pd.crosstab(clean["phase"], clean["dow"], normalize="index").round(3)
log.table("(b) Weekday mix of each phase (non-promo days) - shares should be similar", mix)

# (c) Trend misspecification: a log-linear trend could leave a sawtooth if growth came in steps at month start.
step = smf.ols("np.log(txns) ~ C(phase) + C(dow) + C(Branch) + C(dt.dt.month)", data=clean).fit(cov_type="HC1")
step_eff = np.expm1(step.params.filter(like="phase")).round(3)
log(f"(c) With month fixed effects instead of a linear trend: {dict(zip(PHASES[1:], step_eff.values))}")

# (d) Same in every branch?
br_rows = {}
for b in BRANCHES:
    g = clean[clean["Branch"] == b]
    fit = smf.ols("np.log(txns) ~ C(phase) + C(dow) + t", data=g).fit(cov_type="HC1")
    br_rows[b] = np.expm1(fit.params.filter(like="phase")).values
by_branch = pd.DataFrame(br_rows, index=PHASES[1:]).T
log.table("(d) Phase effect on txns by branch (observed)", by_branch.round(3))

# (e) Stricter test. Branch-days on the same date are not independent, so cluster by date. Compare first week vs rest,
# per month (using all non-promo days, not only days 15-21), and against placebo 7-day windows.
clean["first_week"] = (clean["dom"] <= 7).astype(int)
clean["m"] = clean["dt"].dt.month
strict = []
for label, ctrl in [("linear trend", "C(dow) + C(Branch) + t"), ("month fixed effects + trend", "C(dow) + C(Branch) + C(m) + t")]:
    fit = smf.ols(f"np.log(txns) ~ first_week + {ctrl}", data=clean).fit(
        cov_type="cluster", cov_kwds={"groups": clean["dt"].dt.dayofyear})
    lo, hi = np.expm1(fit.conf_int().loc["first_week"])
    res = smf.ols(f"np.log(txns) ~ {ctrl}", data=clean).fit().resid
    monthly = clean.assign(r=res).groupby("m").apply(lambda g: g.loc[g.dom <= 7, "r"].mean() - g.loc[g.dom > 7, "r"].mean())
    placebo = pd.Series({s: res[clean["dom"].isin([((s - 1 + i) % 31) + 1 for i in range(7)])].mean()
                         - res[~clean["dom"].isin([((s - 1 + i) % 31) + 1 for i in range(7)])].mean() for s in range(1, 32)})
    strict.append({"controls": label, "first-week effect": np.expm1(fit.params["first_week"]), "95% CI low": lo,
                   "95% CI high": hi, "p (clustered by date)": fit.pvalues["first_week"],
                   **{f"month {m}": v for m, v in monthly.items()},
                   "busiest 7-day window starts on day": int(placebo.idxmax())})
strict = pd.DataFrame(strict).set_index("controls").T
log.table("(e) First week (days 1-7) vs rest of month: pooled, per month, and placebo windows (observed)", strict.round(3))
log("Reading: the first-week lift is significant overall (+5.7% to +6.8%), but it is concentrated in Feb-Apr "
    "(+5% to +11%) and roughly absent in Jan, May and Jun. The busiest 7-day window starts between day 26 and day 1, "
    "i.e. around the turn of the month. It is not a stable every-month rule.")
log("ASSUMPTION (not testable here): Feb-Apr roughly matches the university spring semester in session; Jan is "
    "break and May-Jun finals/summer. A month-end payday/allowance cycle among students would fit this pattern.")

# ---- Payday test: do expensive items / categories dip more?
log("\n## Payday test")
price_cut = d.groupby("Product")[PRICE].mean().median()
d["tier"] = np.where(d.groupby("Product")[PRICE].transform("mean") > price_cut, "premium", "cheap")
tier_rows = {}
for tier, g in d[~d["promo"]].groupby("tier"):
    eff, p = phase_effects(branch_days(g, units=("Quantity", "sum")), "units")
    tier_rows[tier] = eff
cat_rows = {}
for cat, g in d[~d["promo"]].groupby("Category"):
    eff, _ = phase_effects(branch_days(g, units=("Quantity", "sum")), "units")
    cat_rows[cat] = eff
known_rows = {}
for lab, g in d[~d["promo"]].groupby(d["Customer ID"].notna()):
    eff, _ = phase_effects(branch_days(g, txns=("Transaction ID", "nunique")), "txns")
    known_rows["identified" if lab else "anonymous"] = eff
log.table(f"Units effect by price tier (premium = product avg price > ${price_cut:.2f})", pd.DataFrame(tier_rows).T.round(3))
log.table("Units effect by category", pd.DataFrame(cat_rows).T.round(3).sort_values("d15-21"))
log.table("Txns effect: identified vs anonymous customers", pd.DataFrame(known_rows).T.round(3))
hour_rows = {}
d["band"] = pd.cut(d["hour"], [0, 11, 18, 24], labels=["morning 7-11", "day 12-18", "evening 19-23"])
for band, g in d[~d["promo"]].groupby("band", observed=True):
    eff, _ = phase_effects(branch_days(g, txns=("Transaction ID", "nunique")), "txns")
    hour_rows[band] = eff
log.table("Txns effect by time of day", pd.DataFrame(hour_rows).T.round(3))

# ---- $ size (ESTIMATE): what if days 8-31 kept first-week traffic, with the same basket?
eff_rev = eff_tbl.loc["revenue", [f"{p} effect" for p in PHASES[1:]]]
eff_gp = eff_tbl.loc["gp", [f"{p} effect" for p in PHASES[1:]]]
eff_rev.index = eff_gp.index = PHASES[1:]
lost = bd.assign(
    rev_gap=lambda x: x["revenue"] * (1 / (1 + x["phase"].astype(str).map(eff_rev).fillna(0)) - 1),
    gp_gap=lambda x: x["gp"] * (1 / (1 + x["phase"].astype(str).map(eff_gp).fillna(0)) - 1))
months = d["dt"].dt.to_period("M").nunique()
log(f"\nESTIMATE: if days 8-31 matched first-week traffic, revenue would be ${lost['rev_gap'].sum() / months:,.0f}/month "
    f"higher and gross profit ${lost['gp_gap'].sum() / months:,.0f}/month higher "
    f"(${lost['gp_gap'].sum() / months * 12:,.0f}/yr GP). This is an upper bound: nobody can make every day look like payday week.")
log(f"ESTIMATE: recovering a quarter of the gap = ${lost['gp_gap'].sum() / months * 12 / 4:,.0f}/yr GP.")
d15 = lost[lost["phase"] == "d15-21"]
log(f"Days 15-21 alone account for ${d15['gp_gap'].sum() / months:,.0f}/month of the GP gap.")
log("Practical value is less about recovering this $ and more about MEASUREMENT: the turn-of-month swing (~6%) is as "
    "large as the smallest traffic drop the Garden price pilot can detect in 28 days (6.0%, script 03). A pilot that "
    "starts on day 1 and is compared with mid-month days would be biased by the cycle. The pilot must cover a full "
    "calendar month or include the cycle in its counterfactual.")

fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(shape.index, shape * 100, color=["#2b6cb0" if v >= 0 else "#c05621" for v in shape])
for a, b in [(0.5, 7.5), (14.5, 21.5)]:
    ax.axvspan(a, b, color="#edf2f7", zorder=0)
ax.axhline(0, color="#4a5568", lw=0.8)
ax.set(xlabel="Day of month", ylabel="Traffic vs expected (%)",
       title="Traffic peaks around the turn of the month and is lowest on days 15-25")
fig.tight_layout(); fig.savefig(FIG / "10_mid_month_dip.png", dpi=150); plt.close(fig)


# ================================================================ 2. Tuesday
log("\n\n# 2. Tuesday: who are the extra customers, and when do they come?")
WEEKDAYS = ["Monday", "Wednesday", "Thursday", "Friday"]  # comparison days: other weekdays, not the weekend
d["is_tue"] = d["weekday"] == "Tuesday"
tx = d.groupby("Transaction ID").agg(dt=("dt", "first"), weekday=("weekday", "first"), Branch=("Branch", "first"),
                                     hour=("hour", "first"), cust=("Customer ID", "first"), revenue=(REV, "sum"),
                                     gp=(GP, "sum"), otype=("Order Type", "first"))
tx["is_tue"] = tx["weekday"] == "Tuesday"
wk = tx[tx["weekday"].isin(WEEKDAYS + ["Tuesday"])]

# ---- (a) Size and consistency
bdt = branch_days(d, txns=("Transaction ID", "nunique"), revenue=(REV, "sum"), gp=(GP, "sum"))
bdt = bdt[bdt["dow"].isin(WEEKDAYS + ["Tuesday"])].assign(tue=lambda x: (x["dow"] == "Tuesday").astype(int))
fit = smf.ols("np.log(txns) ~ tue + C(Branch) + t + C(phase) + promo", data=bdt).fit(
    cov_type="cluster", cov_kwds={"groups": bdt["dt"].dt.dayofyear})
lo, hi = np.expm1(fit.conf_int().loc["tue"])
log(f"Tuesday vs Mon/Wed/Thu/Fri (observed; controls: branch, trend, month phase, promo; clustered by date): "
    f"{np.expm1(fit.params['tue']):+.1%} transactions (95% CI {lo:+.1%} to {hi:+.1%})")
daily_tot = tx.groupby("dt").size()
tue_days = daily_tot[daily_tot.index.dayofweek == 1]
other_days = daily_tot[daily_tot.index.dayofweek.isin([0, 2, 3, 4])]
log(f"Tuesdays: {len(tue_days)}, mean {tue_days.mean():.0f} txns/day (min {tue_days.min()}); other weekdays mean "
    f"{other_days.mean():.0f} (max {other_days.max()}). Tuesdays below the other-weekday average: "
    f"{(tue_days < other_days.mean()).sum()} of {len(tue_days)}")
tue_month = tx.groupby([tx["dt"].dt.month, "is_tue"]).apply(lambda g: len(g) / g["dt"].nunique()).unstack()
tue_month = tue_month.join(
    tx[tx["weekday"].isin(WEEKDAYS)].groupby(tx["dt"].dt.month).apply(lambda g: len(g) / g["dt"].nunique()).rename("weekday avg"))
tue_month["Tuesday multiplier"] = tue_month[True] / tue_month["weekday avg"]
log.table("Tuesday multiplier by month (observed; Tuesday txns/day / other-weekday txns/day)",
          tue_month[["Tuesday multiplier"]].round(2))
by_dow = daily_tot.groupby(daily_tot.index.day_name()).mean().reindex(
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
log.table("Average transactions/day by weekday (observed)", by_dow.round(0).to_frame("txns/day"))
log("Alternative: Tuesday steals customers from Monday/Wednesday. Rejected if Mon/Wed are not lower than Thu/Fri "
    f"(Mon+Wed avg {by_dow[['Monday', 'Wednesday']].mean():.0f} vs Thu+Fri avg {by_dow[['Thursday', 'Friday']].mean():.0f}).")

# ---- (b) Who: same regulars more often, or a separate Tuesday crowd?
known = tx.dropna(subset=["cust"])
per_day = known.groupby("dt").agg(custs=("cust", "nunique"), visits=("cust", "size"))
per_day["tue"] = per_day.index.dayofweek == 1
per_day = per_day[per_day.index.dayofweek.isin([0, 1, 2, 3, 4])]
who = per_day.groupby("tue")[["custs", "visits"]].mean()
who["visits per customer that day"] = who["visits"] / who["custs"]
log.table("Identified customers per day: Tuesday vs other weekdays (observed)", who.round(2))

cust = known[known["weekday"].isin(WEEKDAYS + ["Tuesday"])].groupby("cust").agg(
    n=("is_tue", "size"), tue=("is_tue", "sum"))
p_tue = cust["tue"].sum() / cust["n"].sum()
cust["share"] = cust["tue"] / cust["n"]
rng = np.random.default_rng(0)
sims = rng.binomial(cust["n"].values[None, :].repeat(500, 0), p_tue)
sim_share = sims / cust["n"].values
obs = {"customers with >=1 Tuesday visit": (cust["tue"] > 0).mean(),
       "customers with >=50% of weekday visits on Tuesday": (cust["share"] >= 0.5).mean(),
       "customers who ONLY come on Tuesday (>=3 visits)": ((cust["share"] == 1) & (cust["n"] >= 3)).mean(),
       "variance of Tuesday share": cust["share"].var()}
exp = {"customers with >=1 Tuesday visit": (sims > 0).mean(),
       "customers with >=50% of weekday visits on Tuesday": (sim_share >= 0.5).mean(),
       "customers who ONLY come on Tuesday (>=3 visits)": ((sim_share == 1) & (cust["n"].values >= 3)).mean(),
       "variance of Tuesday share": sim_share.var(axis=1).mean()}
log.table(f"Is there a separate 'Tuesday crowd'? Observed vs expected if EVERY customer were equally Tuesday-prone "
          f"(p = {p_tue:.1%} of weekday visits on Tuesday; 500 simulations)",
          pd.DataFrame({"observed": obs, "expected if everyone the same": exp}).round(3))
log(f"Identified share of transactions: Tuesday {tx.loc[tx.is_tue, 'cust'].notna().mean():.1%} vs other weekdays "
    f"{tx.loc[tx.weekday.isin(WEEKDAYS), 'cust'].notna().mean():.1%}")

# ---- (c) When and what
def tue_mult(frame, col):
    days = frame.groupby("is_tue")["dt"].nunique()
    cnt = frame.groupby([col, "is_tue"], observed=True).size().unstack()
    return (cnt[True] / days[True]) / (cnt[False] / days[False])

wk_lines = d[d["weekday"].isin(WEEKDAYS + ["Tuesday"])]
hour_mult = tue_mult(wk, "hour")
log.table("Tuesday multiplier by hour (observed; per-day txns Tuesday / other weekdays)", hour_mult.round(2).to_frame("x"))
for col, label in [("Branch", "branch"), ("otype", "order type")]:
    log.table(f"Tuesday multiplier by {label}", tue_mult(wk, col).round(2).to_frame("x"))
log.table("Tuesday multiplier by category (units)", tue_mult(wk_lines, "Category").round(2).sort_values().to_frame("x"))
basket = wk.groupby("is_tue")[["revenue", "gp"]].mean()
log.table("Basket per transaction: Tuesday vs other weekdays (observed)", basket.round(2))

# ---- (d) Staffing: peak-hour load per branch
peak = wk[wk["hour"].between(19, 22)]
load = peak.groupby(["Branch", "is_tue"]).size() / peak.groupby(["Branch", "is_tue"])["dt"].nunique() / 4
load = load.unstack().rename(columns={False: "other weekdays", True: "Tuesday"})
load["extra txns/hour"] = load["Tuesday"] - load["other weekdays"]
log.table("Peak 19:00-23:00 load per branch, transactions per hour (observed)", load.round(1))
whole = wk.groupby(["Branch", "is_tue"]).size() / wk.groupby(["Branch", "is_tue"])["dt"].nunique()
whole = whole.unstack().rename(columns={False: "other weekdays", True: "Tuesday"})
log.table("Whole-day transactions per branch (observed)", whole.round(0))

# ---- (e) What Tuesday is worth (observed) and what is at risk
extra = wk.groupby("is_tue").agg(rev=("revenue", "sum"), gp=("gp", "sum"), days=("dt", "nunique"))
extra = extra[["rev", "gp"]].div(extra["days"], axis=0)
log(f"Tuesday brings ${extra.loc[True, 'rev'] - extra.loc[False, 'rev']:,.0f} more revenue and "
    f"${extra.loc[True, 'gp'] - extra.loc[False, 'gp']:,.0f} more gross profit than an average weekday "
    f"(observed) = ${(extra.loc[True, 'gp'] - extra.loc[False, 'gp']) * 52:,.0f}/yr of GP that depends on whatever "
    "drives Tuesdays (estimate, x52 weeks).")

fig, ax = plt.subplots(figsize=(8, 4))
ax.bar(hour_mult.index, hour_mult.values, color="#2b6cb0")
ax.axhline(1, color="#4a5568", lw=0.8)
ax.axhline(hour_mult.mean(), color="#c05621", lw=1, ls="--", label=f"average x{hour_mult.mean():.2f}")
ax.set(xlabel="Hour of day", ylabel="Tuesday / other weekdays",
       title="The Tuesday lift is the same at every hour of the day")
ax.set_xticks(hour_mult.index)
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "11_tuesday_by_hour.png", dpi=150); plt.close(fig)


# ================================================================ 3. Evening margin mix
log("\n\n# 3. Evening: lower margin %, but is it a problem?")
DRINKS = ["Hot Coffee", "Cold Coffee", "Matcha & Tea", "Cold Drinks"]
FOOD = ["Bakery", "Desserts", "Breakfast", "Sandwiches", "Meals"]
d["daypart"] = pd.cut(d["hour"], [0, 11, 18, 24], labels=["morning 7-11", "day 12-18", "evening 19-23"])
tx["daypart"] = pd.cut(tx["hour"], [0, 11, 18, 24], labels=["morning 7-11", "day 12-18", "evening 19-23"])

# ---- (a) Margin % vs margin $ per visit
dp = d.groupby("daypart", observed=True).agg(revenue=(REV, "sum"), gp=(GP, "sum"), lines=(REV, "size"))
dp["margin %"] = dp["gp"] / dp["revenue"]
dp["txns"] = tx.groupby("daypart", observed=True).size()
dp["share of txns"] = dp["txns"] / dp["txns"].sum()
dp["revenue / txn"] = dp["revenue"] / dp["txns"]
dp["GP $ / txn"] = dp["gp"] / dp["txns"]
dp["items / txn"] = d.groupby("daypart", observed=True)["Quantity"].sum() / dp["txns"]
log.table("Margin % vs gross profit $ per visit, by time of day (observed)", dp.round(3))

# ---- (b) Why: product mix (prices and costs are fixed per product/branch, so only mix, branch mix or discounts can move it)
mix = pd.crosstab(d["daypart"], d["Category"], values=d[REV], aggfunc="sum", normalize="index")
cat_margin = d.groupby("Category")[GP].sum() / d.groupby("Category")[REV].sum()
log.table("Revenue mix by category (observed)", mix.round(3))
log.table("Category gross margin (observed)", cat_margin.sort_values().round(3).to_frame("margin"))
eve, day = d[d["daypart"] == "evening 19-23"], d[d["daypart"] == "day 12-18"]
prod_margin = d.groupby(["Branch", "Product"])[GP].sum() / d.groupby(["Branch", "Product"])[REV].sum()
day_mix = day.groupby(["Branch", "Product"])[REV].sum() / day[REV].sum()
eve_mix = eve.groupby(["Branch", "Product"])[REV].sum() / eve[REV].sum()
log(f"Evening margin at its own mix: {(eve_mix * prod_margin).sum():.3%}; at the DAYTIME product+branch mix: "
    f"{(day_mix * prod_margin).sum():.3%}; daytime actual: {day[GP].sum() / day[REV].sum():.3%}")
log(f"Discount share of list revenue: evening {1 - eve[REV].sum() / eve['list_rev'].sum():.2%}, "
    f"day {1 - day[REV].sum() / day['list_rev'].sum():.2%} -> discounts are not the reason")

# ---- (c) What an evening basket looks like
tx_lines = d.groupby("Transaction ID").agg(
    daypart=("daypart", "first"),
    has_drink=("Category", lambda s: s.isin(DRINKS).any()),
    has_food=("Category", lambda s: s.isin(FOOD).any()),
    has_dessert=("Category", lambda s: (s == "Desserts").any()),
    revenue=(REV, "sum"), gp=(GP, "sum"))
tx_lines["type"] = np.select([tx_lines.has_drink & tx_lines.has_food, tx_lines.has_drink],
                             ["drink + food", "drink only"], "food only")
comp = pd.crosstab(tx_lines["daypart"], tx_lines["type"], normalize="index")
gp_by_type = tx_lines.groupby("type")[["revenue", "gp"]].mean()
log.table("Basket type share by time of day (observed)", comp.round(3))
log.table("Average revenue and GP $ per transaction by basket type (observed)", gp_by_type.round(2))
des = tx_lines[tx_lines["has_dessert"]]
des_att = des.groupby("daypart", observed=True)["has_drink"].mean()
log.table("Dessert transactions that also include a drink (observed)", des_att.round(3).to_frame("with drink"))
eve_des = des[des["daypart"] == "evening 19-23"]
log(f"Evening dessert transactions: {len(eve_des):,} ({len(eve_des) / (tx_lines.daypart == 'evening 19-23').sum():.1%} "
    f"of evening txns); without a drink: {(~eve_des.has_drink).sum():,}. GP/txn with drink "
    f"${eve_des.loc[eve_des.has_drink, 'gp'].mean():.2f} vs without ${eve_des.loc[~eve_des.has_drink, 'gp'].mean():.2f}")

# ---- (d) $ framing (ESTIMATES)
eve_rev = eve[REV].sum()
mix_gap = (day_mix * prod_margin).sum() - (eve_mix * prod_margin).sum()
months = d["dt"].dt.to_period("M").nunique()
log(f"\nESTIMATE A - 'fix the mix' (what evening revenue would earn at daytime margin): "
    f"${mix_gap * eve_rev / months * 12:,.0f}/yr -> effectively zero. The evening shift towards low-margin desserts is "
    "offset by a shift towards high-margin cold coffee and matcha. HYPOTHESIS REJECTED: there is no evening margin problem.")
drink_gp = d[d["Category"].isin(DRINKS) & (d["daypart"] == "evening 19-23")]
avg_drink_gp = (drink_gp[GP] / drink_gp["Quantity"]).mean()
no_drink = (~eve_des.has_drink).sum()
for attach in [0.10, 0.20, 0.30]:
    log(f"ESTIMATE B - dessert+drink bundle: if {attach:.0%} of evening dessert-only buyers add a drink at "
        f"${avg_drink_gp:.2f} avg GP (minus a $0.50 bundle discount): "
        f"${no_drink * attach * (avg_drink_gp - 0.5) / months * 12:,.0f}/yr GP")

fig, ax1 = plt.subplots(figsize=(8, 4))
x = np.arange(len(dp))
ax1.bar(x - 0.2, dp["margin %"] * 100, width=0.4, color="#a0aec0", label="gross margin %")
ax2 = ax1.twinx()
ax2.bar(x + 0.2, dp["GP $ / txn"], width=0.4, color="#2b6cb0", label="gross profit $ per visit")
ax1.set_xticks(x, dp.index)
ax1.set(ylabel="Gross margin (%)", ylim=(0, 80))
ax2.set(ylabel="Gross profit $ per visit", ylim=(0, 8))
ax1.set_title("Evening margin % is the same as daytime, and profit per visit is highest")
fig.legend(loc="upper left", bbox_to_anchor=(0.1, 0.88), frameon=False)
fig.tight_layout(); fig.savefig(FIG / "12_evening_margin.png", dpi=150); plt.close(fig)


# ================================================================ 4. Saturday
log("\n\n# 4. Saturday: weakest day - is it the student customers?")
SEMESTER = [2, 3, 4]  # ASSUMPTION: spring semester in session (Jan = break, May-Jun = finals/summer)
bds = branch_days(d, txns=("Transaction ID", "nunique"), revenue=(REV, "sum"), gp=(GP, "sum"))
bds["day"] = np.where(bds["dow"].isin(WEEKDAYS), "weekday", bds["dow"])
bds = bds[bds["day"].isin(["weekday", "Saturday", "Sunday"])]
bds["sat"] = (bds["day"] == "Saturday").astype(int)
bds["sun"] = (bds["day"] == "Sunday").astype(int)
bds["sem"] = bds["dt"].dt.month.isin(SEMESTER).astype(int)
fit = smf.ols("np.log(txns) ~ sat + sun + C(Branch) + t + C(phase) + promo", data=bds).fit(
    cov_type="cluster", cov_kwds={"groups": bds["dt"].dt.dayofyear})
for k in ["sat", "sun"]:
    lo, hi = np.expm1(fit.conf_int().loc[k])
    log(f"{'Saturday' if k == 'sat' else 'Sunday'} vs Mon/Wed/Thu/Fri (observed; controls: branch, trend, month phase, "
        f"promo; clustered): {np.expm1(fit.params[k]):+.1%} transactions (95% CI {lo:+.1%} to {hi:+.1%})")

# ---- (a) Fewer people or smaller baskets?
txs = tx.assign(day=np.where(tx["weekday"].isin(WEEKDAYS), "weekday", tx["weekday"]))
txs = txs[txs["day"].isin(["weekday", "Saturday", "Sunday"])]
log.table("(a) Basket per transaction (observed)", txs.groupby("day")[["revenue", "gp"]].mean().round(2))

# ---- (b) Who disappears? Identified regulars vs anonymous walk-ins
rows = {}
for lab, g in txs.groupby(txs["cust"].notna()):
    per = g.groupby("day").size() / g.groupby("day")["dt"].nunique()
    rows["identified" if lab else "anonymous"] = per / per["weekday"]
who_sat = pd.DataFrame(rows).T[["Saturday", "Sunday"]]
log.table("(b) Transactions/day relative to weekdays, identified vs anonymous (observed)", who_sat.round(3))
known_s = txs.dropna(subset=["cust"])
cs = known_s.groupby("cust").agg(n=("day", "size"), sat=("day", lambda s: (s == "Saturday").sum()))
p_sat = cs["sat"].sum() / cs["n"].sum()
sims = rng.binomial(cs["n"].values[None, :].repeat(500, 0), p_sat)
log(f"Customers who never come on Saturday: observed {(cs['sat'] == 0).mean():.1%} vs "
    f"{(sims == 0).mean():.1%} expected if everyone were equally likely to skip Saturday "
    f"(p = {p_sat:.1%}). Variance of Saturday share: observed {(cs['sat'] / cs['n']).var():.4f} vs "
    f"expected {(sims / cs['n'].values).var(axis=1).mean():.4f}")

# ---- (c) Semester vs non-semester months
fit2 = smf.ols("np.log(txns) ~ sat * sem + sun * sem + C(Branch) + t + C(phase) + promo", data=bds).fit(
    cov_type="cluster", cov_kwds={"groups": bds["dt"].dt.dayofyear})
log(f"(c) Saturday effect outside semester months (Jan, May, Jun): {np.expm1(fit2.params['sat']):+.1%}; "
    f"extra during semester (Feb-Apr): {fit2.params['sat:sem']:+.3f} log points (p = {fit2.pvalues['sat:sem']:.2f})")
sat_month = txs.groupby([txs["dt"].dt.month, "day"]).size() / txs.groupby([txs["dt"].dt.month, "day"])["dt"].nunique()
sat_month = sat_month.unstack()
log.table("Saturday and Sunday traffic relative to weekdays, by month (observed)",
          sat_month[["Saturday", "Sunday"]].div(sat_month["weekday"], axis=0).round(3))

# ---- (d) Where and when
def day_mult(frame, col, which="Saturday"):
    days = frame.groupby("day")["dt"].nunique()
    cnt = frame.groupby([col, "day"], observed=True).size().unstack()
    return (cnt[which] / days[which]) / (cnt["weekday"] / days["weekday"])

log.table("(d) Saturday vs weekday by branch", day_mult(txs, "Branch").round(3).to_frame("x"))
txs["daypart"] = pd.cut(txs["hour"], [0, 11, 18, 24], labels=["morning 7-11", "day 12-18", "evening 19-23"])
log.table("Saturday vs weekday by time of day", day_mult(txs, "daypart").round(3).to_frame("x"))
lines_s = d.assign(day=np.where(d["weekday"].isin(WEEKDAYS), "weekday", d["weekday"]))
lines_s = lines_s[lines_s["day"].isin(["weekday", "Saturday"])]
log.table("Saturday vs weekday by category (units)", day_mult(lines_s, "Category").round(3).sort_values().to_frame("x"))
log.table("Saturday vs weekday by order type", day_mult(txs, "otype").round(3).to_frame("x"))

# ---- (e) $ at stake
gp_day = txs.groupby("day").agg(gp=("gp", "sum"), days=("dt", "nunique"))
gp_day = gp_day["gp"] / gp_day["days"]
log(f"\n(e) Gross profit per day (observed): weekday ${gp_day['weekday']:,.0f}, Saturday ${gp_day['Saturday']:,.0f}, "
    f"Sunday ${gp_day['Sunday']:,.0f}. Saturday gap vs weekday = ${(gp_day['weekday'] - gp_day['Saturday']) * 52:,.0f}/yr "
    f"(estimate, x52); closing 10% of it = ${(gp_day['weekday'] - gp_day['Saturday']) * 52 * 0.1:,.0f}/yr.")

fig, ax = plt.subplots(figsize=(8, 4))
plot = sat_month[["Saturday", "Sunday"]].div(sat_month["weekday"], axis=0)
ax.plot(plot.index, plot["Saturday"], marker="o", color="#c05621", label="Saturday")
ax.plot(plot.index, plot["Sunday"], marker="o", color="#718096", label="Sunday")
ax.axhline(1, color="#4a5568", lw=0.8)
ax.axvspan(1.5, 4.5, color="#edf2f7", zorder=0, label="spring semester (assumed)")
ax.set_xticks(range(1, 7), ["Jan", "Feb", "Mar", "Apr", "May", "Jun"])
ax.set(ylabel="Traffic vs Mon/Wed/Thu/Fri", ylim=(0, 1.2), title="Saturday is ~30% below weekdays every month, semester or not")
ax.legend(frameon=False, loc="lower right")
fig.tight_layout(); fig.savefig(FIG / "12b_weekend.png", dpi=150); plt.close(fig)


# ================================================================ 5. Where does growth come from?
log("\n\n# 5. Growth: where does +52% come from?")
tx["month"] = tx["dt"].dt.month
mo = tx.groupby("month").agg(days=("dt", "nunique"), txns=("revenue", "size"), revenue=("revenue", "sum"),
                             gp=("gp", "sum"), id_txns=("cust", "count"), active=("cust", "nunique"))
mo["anon_txns"] = mo["txns"] - mo["id_txns"]
mo["revenue/day"] = mo["revenue"] / mo["days"]
mo["txns/day"] = mo["txns"] / mo["days"]
mo["basket $"] = mo["revenue"] / mo["txns"]
mo["margin"] = mo["gp"] / mo["revenue"]
mo["active share of ID pool"] = mo["active"] / tx["cust"].nunique()
mo["visits/active customer/day"] = mo["id_txns"] / mo["active"] / mo["days"]
mo["anon txns/day"] = mo["anon_txns"] / mo["days"]
log.table("Monthly drivers, per day so short months don't distort (observed)",
          mo[["revenue/day", "txns/day", "basket $", "margin", "active", "active share of ID pool",
              "visits/active customer/day", "anon txns/day"]].round(3))

# Decompose Jan -> Jun growth in revenue/day (log shares add up exactly).
j, n = mo.loc[1], mo.loc[6]
parts = pd.Series({
    "more visits (txns/day)": np.log(n["txns/day"] / j["txns/day"]),
    "bigger baskets ($/txn)": np.log(n["basket $"] / j["basket $"]),
})
log(f"\nRevenue/day Jan -> Jun: {n['revenue/day'] / j['revenue/day'] - 1:+.1%}. Share explained by: "
    + ", ".join(f"{k} {v / parts.sum():.0%}" for k, v in parts.items()))
id_parts = pd.Series({
    "more ID customers active": np.log(n["active"] / j["active"]),
    "each active customer visits more often": np.log((n["id_txns"] / n["active"]) / (j["id_txns"] / j["active"])),
})
log(f"Identified visits Jan -> Jun: {n['id_txns'] / j['id_txns'] - 1:+.1%} (raw monthly counts). Split: "
    + ", ".join(f"{k} {v / id_parts.sum():.0%}" for k, v in id_parts.items()))
log(f"Anonymous visits/day Jan -> Jun: {n['anon txns/day'] / j['anon txns/day'] - 1:+.1%}; identified visits/day: "
    f"{(n['id_txns'] / n['days']) / (j['id_txns'] / j['days']) - 1:+.1%} -> walk-ins grow as fast as regulars")

# Growth rate and whether it is slowing.
daily = tx.groupby("dt").agg(revenue=("revenue", "sum"))
daily["t"] = (daily.index - daily.index.min()).days
daily["dow"] = daily.index.day_name()
daily["half"] = (daily.index.month >= 4).astype(int)
g_fit = smf.ols("np.log(revenue) ~ t + C(dow)", data=daily).fit(cov_type="HC1")
monthly_rate = np.expm1(g_fit.params["t"] * 30.4)
lo, hi = np.expm1(g_fit.conf_int().loc["t"] * 30.4)
log(f"Underlying growth (log-linear on daily revenue, weekday-adjusted): {monthly_rate:+.1%}/month "
    f"(95% CI {lo:+.1%} to {hi:+.1%})")
g2 = smf.ols("np.log(revenue) ~ t + t:half + C(dow)", data=daily).fit(cov_type="HC1")
log(f"Is it slowing? Change in monthly growth rate in Apr-Jun vs Jan-Mar: {g2.params['t:half'] * 30.4:+.3f} log points/month "
    f"(p = {g2.pvalues['t:half']:.2f})")

# Which products / branches grow faster than the rest? (share shift Jan-Feb vs May-Jun, chi-square + per-product z)
early, late = d[d["month"] <= 2], d[d["month"] >= 5]
for col in ["Branch", "Category", "Product"]:
    tab = pd.DataFrame({"early": early.groupby(col)["Quantity"].sum(), "late": late.groupby(col)["Quantity"].sum()})
    chi2, p, *_ = chi2_contingency(tab.T.values)
    tab["growth"] = tab["late"] / tab["early"] - 1
    pe, pl = tab["early"] / tab["early"].sum(), tab["late"] / tab["late"].sum()
    pooled = (tab["early"] + tab["late"]) / (tab["early"].sum() + tab["late"].sum())
    tab["share z"] = (pl - pe) / np.sqrt(pooled * (1 - pooled) * (1 / tab["early"].sum() + 1 / tab["late"].sum()))
    log(f"\n{col}: do shares change Jan-Feb -> May-Jun? chi-square p = {p:.3g}")
    show = tab.sort_values("growth")
    if col == "Product":
        show = pd.concat([show.head(5), show.tail(5)])
    log(show.round(3).to_string())
log("Products with |z| > 3 changed share beyond noise; with 45 products, |z| ~2 is expected by chance for a couple.")

# Capacity: busiest hour today, and in 6 months if growth continues (ESTIMATE).
peak_now = tx[(tx["month"] == 6) & (tx["weekday"] == "Tuesday")]
peak_now = peak_now.groupby(["Branch", "hour"]).size() / peak_now["dt"].nunique()
busiest = peak_now.groupby("Branch").max()
proj = pd.DataFrame({"June Tuesday busiest hour (txns/hour)": busiest,
                     "December at current growth (estimate)": busiest * (1 + monthly_rate) ** 6,
                     "December at half the growth (estimate)": busiest * (1 + monthly_rate / 2) ** 6})
log.table("Capacity check: busiest hour, June Tuesdays (observed) and projected (estimate)", proj.round(1))

fig, ax = plt.subplots(figsize=(8, 4))
x = np.arange(1, 7)
ax.plot(x, mo["revenue/day"] / mo.loc[1, "revenue/day"], marker="o", color="#2b6cb0", label="revenue/day")
ax.plot(x, mo["txns/day"] / mo.loc[1, "txns/day"], marker="o", color="#2f855a", label="transactions/day")
ax.plot(x, mo["basket $"] / mo.loc[1, "basket $"], marker="o", color="#a0aec0", label="basket $/transaction")
ax.set_xticks(x, ["Jan", "Feb", "Mar", "Apr", "May", "Jun"])
ax.set(ylabel="Index (January = 1)", title="Growth comes from more visits; baskets are flat")
ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(FIG / "12c_growth.png", dpi=150); plt.close(fig)


# ================================================================ 6. Do discounts bring customers back?
log("\n\n# 6. Do discounts bring customers back later?")
vis = d.dropna(subset=["Customer ID"]).groupby("Transaction ID").agg(
    cust=("Customer ID", "first"), dt=("dt", "first"), time=("Time", "first"), Branch=("Branch", "first"),
    disc=("discounted", "max"), revenue=(REV, "sum"))
vis = vis.sort_values(["cust", "dt", "time"])
vis["next_dt"] = vis.groupby("cust")["dt"].shift(-1)
vis["gap"] = (vis["next_dt"] - vis["dt"]).dt.days
vis["promo"] = vis["dt"].isin(PROMO_DAYS)
end = d["dt"].max()

# ---- (a) Promo weeks: discounted vs non-discounted promo-week visitors, visits 30 days before vs after (diff-in-diff)
rows = []
for start, stop in [("2026-03-12", "2026-03-19"), ("2026-05-12", "2026-05-19")]:
    s, e = pd.Timestamp(start), pd.Timestamp(stop)
    wk_v = vis[(vis["dt"] >= s) & (vis["dt"] <= e)]
    treated = wk_v.groupby("cust")["disc"].max()
    for c, got in treated.items():
        cv = vis[vis["cust"] == c]
        rows.append({"window": start[:7], "cust": c, "got_discount": bool(got),
                     "before": ((cv["dt"] >= s - pd.Timedelta(days=30)) & (cv["dt"] < s)).sum(),
                     "after": ((cv["dt"] > e) & (cv["dt"] <= e + pd.Timedelta(days=30))).sum()})
pw = pd.DataFrame(rows)
pw["change"] = pw["after"] - pw["before"]
summ = pw.groupby(["window", "got_discount"])[["before", "after", "change"]].mean()
summ["customers"] = pw.groupby(["window", "got_discount"]).size()
log.table("(a) Visits in the 30 days before/after a promo week, per customer (observed)", summ.round(3))
did = smf.ols("change ~ got_discount + C(window)", data=pw).fit(cov_type="HC1")
lo, hi = did.conf_int().loc["got_discount[T.True]"]
log(f"Difference-in-differences (discounted minus not, change in visits per 30 days): "
    f"{did.params['got_discount[T.True]']:+.3f} visits (95% CI {lo:+.3f} to {hi:+.3f}, p = {did.pvalues['got_discount[T.True]']:.2f})")
pre = smf.ols("before ~ got_discount + C(window)", data=pw).fit(cov_type="HC1")
log(f"Balance check: before the promo, discounted customers made {pre.params['got_discount[T.True]']:+.3f} more visits "
    f"(p = {pre.pvalues['got_discount[T.True]']:.2f}) -> groups {'comparable' if pre.pvalues['got_discount[T.True]'] > 0.05 else 'NOT comparable'}")
# Regression to the mean: customers who were unusually quiet before tend to bounce back anyway. Control for 'before'.
anc = smf.ols("after ~ got_discount + before + C(window)", data=pw).fit(cov_type="HC1")
lo, hi = anc.conf_int().loc["got_discount[T.True]"]
log(f"Controlling for each customer's visits before (guards against regression to the mean): discounted customers make "
    f"{anc.params['got_discount[T.True]']:+.3f} more visits in the next 30 days (95% CI {lo:+.3f} to {hi:+.3f}, "
    f"p = {anc.pvalues['got_discount[T.True]']:.2f}); baseline after-visits for non-discounted = "
    f"{pw.loc[~pw.got_discount, 'after'].mean():.2f}")
for w, g in pw.groupby("window"):
    a = smf.ols("after ~ got_discount + before", data=g).fit(cov_type="HC1")
    log(f"  {w} only: {a.params['got_discount[T.True]']:+.3f} (p = {a.pvalues['got_discount[T.True]']:.2f})")
# Who got the discount? If it depends on what they bought, that is a possible confounder.
promo_lines = d[d["promo"] & d["Customer ID"].notna()]
log.table("Share of promo-week lines discounted, by category (observed) - discounts are not random across products",
          promo_lines.groupby("Category")["discounted"].mean().sort_values().round(3).to_frame("discounted share"))

# ---- (b) All year, within the same customer: is the next visit sooner after a discounted visit?
# Customer fixed effects via the within transformation (demean by customer), plus a time trend for growth.
gaps = vis.dropna(subset=["gap"])
gaps = gaps[gaps["next_dt"] <= end].copy()
gaps["y"] = np.log1p(gaps["gap"])
gaps["disc_i"] = gaps["disc"].astype(float)
gaps["promo_i"] = gaps["promo"].astype(float)
gaps["t"] = (gaps["dt"] - d["dt"].min()).dt.days.astype(float)
cols = ["y", "disc_i", "promo_i", "t"]
dm = gaps[cols] - gaps.groupby("cust")[cols].transform("mean")
fe = smf.ols("y ~ disc_i + promo_i + t - 1", data=dm).fit(cov_type="cluster", cov_kwds={"groups": gaps["cust"]})
coef, se = fe.params["disc_i"], fe.bse["disc_i"]
fe.pvalues = fe.pvalues.rename({"disc_i": "disc"})
log(f"\n(b) Days until the same customer's next visit, after a discounted vs normal visit (customer fixed effects, "
    f"{len(gaps):,} visit pairs, {gaps['disc'].sum():,} discounted): effect {np.expm1(coef):+.1%} "
    f"(95% CI {np.expm1(coef - 1.96 * se):+.1%} to {np.expm1(coef + 1.96 * se):+.1%}, p = {fe.pvalues['disc']:.2f}). "
    "Negative = comes back sooner.")
raw = gaps.groupby("disc")["gap"].agg(["mean", "median", "size"])
log.table("Raw days to next visit (observed)", raw.round(1))
cust_any = vis.groupby("cust").agg(n=("disc", "size"), any_disc=("disc", "max"))
log(f"Naive comparison (biased): customers who ever got a discount average {cust_any.loc[cust_any.any_disc, 'n'].mean():.1f} "
    f"visits vs {cust_any.loc[~cust_any.any_disc, 'n'].mean():.1f} for others - but frequent visitors simply have more chances "
    "to receive a discount, so this is selection, not an effect. The within-customer test above removes it.")

# ---- (c) Does the possible return effect pay back the discount? (ESTIMATE)
pl = d[d["promo"]]
given_all = (pl["list_rev"] - pl[REV]).sum()
given_id = (pl.loc[pl["Customer ID"].notna(), "list_rev"] - pl.loc[pl["Customer ID"].notna(), REV]).sum()
n_treated = pw["got_discount"].sum()
gp_per_visit = tx["gp"].mean()
lo, hi = anc.conf_int().loc["got_discount[T.True]"]
payback = pd.DataFrame({
    "extra visits per discounted customer (30 days)": [anc.params["got_discount[T.True]"], hi],
}, index=["point estimate", "upper 95% bound"])
payback["extra GP $ (all discounted ID customers)"] = payback.iloc[:, 0] * n_treated * gp_per_visit
payback["discount given to ID customers $"] = given_id
log.table(f"(c) Payback of the two promo weeks (ESTIMATE; {n_treated} discounted identified customers, "
          f"${gp_per_visit:.2f} GP per visit; total discount incl. anonymous ${given_all:,.0f})", payback.round(2))
pe_gp, hi_gp = payback.iloc[:, 1]
log(f"At the point estimate the later visits return ${pe_gp:,.0f} of GP against ${given_id:,.0f} of discount given to "
    f"identified customers ({pe_gp / given_id:.0%} payback). At the upper 95% bound it would be ${hi_gp:,.0f} "
    f"({hi_gp / given_id:.0%}), so break-even cannot be ruled out. The promo weeks (in practice Cold Coffee + Desserts "
    "promotions, ~50% of those lines discounted) most likely did not pay back: no lift during the week (README 8.1) "
    "and a small, uncertain return effect afterwards.")
