"""(1) Decode the exact price/cost rules between branches. (2) Expected value of the cost audit. (3) The always-on
discount. (4) Promo weeks as a natural price experiment: an upper bound on price sensitivity. (5) An ID-free pilot
metric: Garden's share of company traffic, backtested month by month."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from common import COST, FIG, GP, OUT, PRICE, REV, Log, load

log = Log("14_rules_value_pilot")
d = load()
months = d["dt"].dt.to_period("M").nunique()
PROMO_DAYS = set(pd.date_range("2026-03-12", "2026-03-19")) | set(pd.date_range("2026-05-12", "2026-05-19"))
d["promo"] = d["dt"].isin(PROMO_DAYS)

# ================================================================ 1. The exact rules
log("# 1. The rules behind branch prices and costs (observed)")
u = d.groupby(["Product", "Branch"]).agg(cost=(COST, "first"), price=(PRICE, "first")).unstack()
H_c, H_p = u["cost"]["Harbour"], u["price"]["Harbour"]
rules = {
    "Garden cost = round(Harbour cost x 1.43, 2)": (np.round(H_c * 1.43, 2) == u["cost"]["Garden"]).sum(),
    "Uptown cost = round(Harbour cost x 0.96, 2)": (np.round(H_c * 0.96, 2) == u["cost"]["Uptown"]).sum(),
    "Garden price = round(Harbour price / 1.05, 2)": (np.round(H_p / 1.05, 2) == u["price"]["Garden"]).sum(),
    "Uptown price within 1 cent of Harbour price x 0.915": ((H_p * 0.915 - u["price"]["Uptown"]).abs() <= 0.01 + 1e-9).sum(),
    "Uptown price within 1.1 cents of Harbour price x 0.915": ((H_p * 0.915 - u["price"]["Uptown"]).abs() <= 0.011).sum(),
    "Uptown price = round(GARDEN price x 0.96, 2)": (np.round(u["price"]["Garden"] * 0.96, 2) == u["price"]["Uptown"]).sum(),
}
for k, v in rules.items():
    log(f"{k}: {v} of 45 products")
log(f"Reverse directions also match: Garden price = round(Uptown price / 0.96, 2): "
    f"{(np.round(u['price']['Uptown'] / 0.96, 2) == u['price']['Garden']).sum()} of 45; Harbour price = round(Garden price x "
    f"1.05, 2): {(np.round(u['price']['Garden'] * 1.05, 2) == H_p).sum()} of 45.")
log("Reading: four exact rules. Uptown's prices are NOT a fixed share of Harbour's (only approximately x0.915); they equal "
    "Garden's rounded prices x 0.96. The rules are consistent with coordinated price lists, but the data cannot show "
    "which list was the source (the reverse relationships match too). Garden's recorded prices are ~4.8% below "
    "Harbour's while its recorded unit costs follow the 43% uplift rule. Whether either was intended is not visible in "
    "transactions; whoever owns the cost sheet and the price list can say why.")
target_price = u["cost"]["Garden"] / (1 - (1 - H_c / H_p))
log(f"Price Garden would need to earn Harbour's margin at its current costs: on average "
    f"{(target_price / u['price']['Garden'] - 1).mean():+.0%} vs today (i.e. ~{(target_price / H_p - 1).mean():+.0%} above "
    "Harbour) - not realistic, which is why the cost side must be fixed first.")

# ================================================================ 2. Expected value of the audit
log("\n# 2. Expected value of the cost audit (ESTIMATE)")
gap_yr = (d.loc[d["Branch"] == "Garden", "cogs"].sum()
          - (d.loc[d["Branch"] == "Garden", "Quantity"] * d.loc[d["Branch"] == "Garden", "Product"].map(H_c)).sum()) * 12 / months
rows = []
for p_real in [0.1, 0.25, 0.5, 0.75]:
    for closure in [0.5, 1.0]:
        rows.append({"P(uplift is a real purchase premium)": p_real, "share of gap closed if real": closure,
                     "expected value $/yr": p_real * closure * gap_yr})
ev = pd.DataFrame(rows).pivot(index="P(uplift is a real purchase premium)", columns="share of gap closed if real",
                              values="expected value $/yr")
log.table(f"Expected annual value of acting on the audit (gap if real = ${gap_yr:,.0f}/yr)", ev.round(0))
AUDIT_COST = 400  # ASSUMPTION: ~16 hours of finance/procurement time at ~$25/hour
log(f"ASSUMPTION: the audit costs ~${AUDIT_COST} (about 16 staff hours). It pays for itself in year one if the chance that "
    f"the uplift is real is above {AUDIT_COST / (0.5 * gap_yr):.1%} (half the gap recovered, no implementation cost). Below "
    "that it is a small net cost; see the net-benefit lines in section 4b.")

# ================================================================ 3. The always-on discount
log("\n# 3. The always-on discount (outside the two promo weeks)")
d["disc_$"] = d["list_rev"] - d[REV]
non = d[~d["promo"]]
log(f"Discounts given: total ${d['disc_$'].sum():,.0f} in 6 months; promo weeks ${d.loc[d.promo, 'disc_$'].sum():,.0f}; "
    f"outside promo weeks ${non['disc_$'].sum():,.0f} (= ${non['disc_$'].sum() * 12 / months:,.0f}/yr) on "
    f"{non['discounted'].mean():.1%} of lines, at rates {sorted(non.loc[non.discounted, 'Discount Rate'].unique())}")
uni = pd.concat({
    "branch": non.groupby("Branch")["discounted"].mean(),
    "category": non.groupby("Category")["discounted"].mean(),
    "order type": non.groupby("Order Type")["discounted"].mean(),
    "has Customer ID": non.groupby(non["Customer ID"].notna())["discounted"].mean(),
}).round(3)
log.table("Share of lines discounted outside promo weeks, by segment (observed)", uni.to_frame("discounted share"))
hr = non.groupby("hour")["discounted"].mean()
log(f"By hour: {hr.min():.1%} to {hr.max():.1%}. The discount is spread evenly everywhere - it is not targeted at slow "
    "hours, slow branches, loyalty members or any product. Together with finding 8.1 (no traffic lift in promo weeks) and "
    "the uniform pattern, it looks like a giveaway rather than a lever.")
log(f"ESTIMATE: stopping it saves up to ${non['disc_$'].sum() * 12 / months:,.0f}/yr if no visits are lost - but see the "
    "stress test (4b): it breaks even at under 1% of visits lost, which no one-month test can detect. Recommendation: "
    "retarget it to the weakest hours rather than remove it blindly.")

# ================================================================ 4. Promo weeks as a price experiment
log("\n# 4. Promo weeks as a natural price experiment (Cold Coffee + Desserts)")
PROMO_CATS = ["Cold Coffee", "Desserts"]
d["promo_cat"] = d["Category"].isin(PROMO_CATS)
day = d.groupby(["dt", "promo_cat"])["Quantity"].sum().unstack()
day.columns = ["other", "promo_cats"]
day["share"] = day["promo_cats"] / (day["promo_cats"] + day["other"])
day["promo"] = day.index.isin(PROMO_DAYS).astype(int)
day["dow"] = day.index.day_name()
day["t"] = np.arange(len(day))
cut = d[d["promo"] & d["promo_cat"]]
eff_cut = 1 - cut[REV].sum() / cut["list_rev"].sum()
fit = smf.ols("np.log(share / (1 - share)) ~ promo + C(dow) + t", data=day).fit(cov_type="HC1")
b, (lo, hi) = fit.params["promo"], fit.conf_int().loc["promo"]
base_share = day.loc[day.promo == 0, "share"].mean()
to_share = lambda x: base_share * np.exp(x) / (1 - base_share + base_share * np.exp(x)) / base_share - 1
log(f"Average effective price cut on Cold Coffee + Desserts during promo weeks: {eff_cut:.1%} (observed)")
log(f"Their share of units: {day.loc[day.promo == 1, 'share'].mean():.1%} on promo days vs {base_share:.1%} otherwise. "
    f"Change in their relative units (vs other categories, controls: weekday, trend): {to_share(b):+.1%} "
    f"(95% CI {to_share(lo):+.1%} to {to_share(hi):+.1%})")
# (No elasticity is derived here: this is a change in category SHARE, not in demand - see the limit stated below.)
# Challenge: both promo weeks sit on days 12-19, the mid-month dip, and these two categories dip MORE than average
# mid-month (script 06). Control for month phase, and compare with a placebo: days 12-19 of the non-promo months.
day["phase"] = pd.cut(day.index.day, [0, 7, 14, 21, 31], labels=["d01-07", "d08-14", "d15-21", "d22-31"])
day["d12_19"] = ((day.index.day >= 12) & (day.index.day <= 19)).astype(int)
day["lr"] = np.log(day["share"] / (1 - day["share"]))
checks = {}
for label, formula in [("weekday + trend (first result)", "lr ~ promo + C(dow) + t"),
                       ("+ month phase", "lr ~ promo + C(dow) + t + C(phase)"),
                       ("placebo: days 12-19 in NON-promo months", "lr ~ d12_19 + C(dow) + t")]:
    data = day if "placebo" not in label else day[day["promo"] == 0]
    key = "d12_19" if "placebo" in label else "promo"
    f2 = smf.ols(formula, data=data).fit(cov_type="HC1")
    checks[label] = {"effect": to_share(f2.params[key]), "95% low": to_share(f2.conf_int().loc[key, 0]),
                     "95% high": to_share(f2.conf_int().loc[key, 1]), "p": f2.pvalues[key]}
did = smf.ols("lr ~ promo + d12_19 + C(dow) + t", data=day).fit(cov_type="HC1")
checks["difference-in-differences: promo vs same days of other months"] = {
    "effect": to_share(did.params["promo"]), "95% low": to_share(did.conf_int().loc["promo", 0]),
    "95% high": to_share(did.conf_int().loc["promo", 1]), "p": did.pvalues["promo"]}
log.table("Challenge: relative units of Cold Coffee + Desserts under different controls (observed)",
          pd.DataFrame(checks).T.round(3))
hi_did = checks["difference-in-differences: promo vs same days of other months"]["95% high"]
log(f"Preferred (difference-in-differences vs days 12-19 of other months): "
    f"{checks['difference-in-differences: promo vs same days of other months']['effect']:+.1%} change in category share "
    f"(95% CI up to {hi_did:+.1%}) while those lines were {eff_cut:.1%} below list price. The first specification was "
    "confounded by the mid-month dip.")
log("LIMIT: this is the promoted categories' SHARE of units, not their absolute demand - other categories can move too, "
    "the 7.8% is the cut vs list price (not vs ordinary days), and who got the discount and whether it was advertised are "
    "unknown. No price elasticity is derived from it. It is weak supporting evidence only; the price decision rests on "
    "the pilot (script 15).")

# ================================================================ 4b. Stress test: what could flip each recommendation?
log("\n# 4b. Stress test: which assumptions could flip each recommendation? (ESTIMATE)")
gp_g = d.loc[d["Branch"] == "Garden", GP].sum() * 12 / months
rev_g = d.loc[d["Branch"] == "Garden", REV].sum() * 12 / months
cogs_fix = (d.loc[d["Branch"] == "Garden", "Quantity"] * d.loc[d["Branch"] == "Garden", "Product"].map(H_c)).sum() * 12 / months
x = 0.05
rows = []
for closure in [0.0, 0.25, 0.5, 1.0]:
    cogs_now = d.loc[d["Branch"] == "Garden", "cogs"].sum() * 12 / months
    cogs = cogs_now - closure * (cogs_now - cogs_fix)
    for e in [0, -0.5, -1.0, -1.5, -2.0]:
        price_gain = (1 + e * x) * (rev_g * (1 + x) - cogs) - (rev_g - cogs)
        rows.append({"cost gap closed": closure, "elasticity": e, "+5% price gain $/yr": price_gain})
st = pd.DataFrame(rows).pivot(index="elasticity", columns="cost gap closed", values="+5% price gain $/yr")
log.table("Recommendation 2 (+5% Garden price): annual GP gain by cost-fix closure (columns) and elasticity (rows)", st.round(0))
non_rev = non[REV].sum() * 12 / months
non_gp = non[GP].sum() * 12 / months
disc_yr = non["disc_$"].sum() * 12 / months
rows = []
for loss in [0, 0.005, 0.01, 0.02, 0.03]:
    rows.append({"visits lost when the 10% discount is removed": loss,
                 "net GP change $/yr": disc_yr - loss * (non_gp + disc_yr)})
st3 = pd.DataFrame(rows).set_index("visits lost when the 10% discount is removed")
log.table("Recommendation 3 (stop the always-on discount): net GP change if some visits are lost", st3.round(0))
be3 = disc_yr / (non_gp + disc_yr)
m_now = 1 - d.loc[d["Branch"] == "Garden", "cogs"].sum() * 12 / months / rev_g
m_fix = 1 - cogs_fix / rev_g
log(f"Recommendation 3 breaks even if removing the discount loses {be3:.1%} of all visits. Recommendation 2 stays positive "
    f"at elasticity -1 for any cost closure; its break-even elasticity (= -1 / (margin + price rise)) is about "
    f"{-1 / (m_now + x):+.2f} with today's costs and about {-1 / (m_fix + x):+.2f} after a full cost fix.")
for p in [0.0, 0.025, 0.25, 0.5]:
    log(f"Audit, first-year expected net benefit at P(real premium) = {p:.1%}, 50% of the gap recovered: "
        f"${p * 0.5 * gap_yr - AUDIT_COST:+,.0f} (before any implementation cost; the value of corrected reporting is not monetised)")
DELAY_MONTHS = 3  # ASSUMPTION: audit + renegotiation take ~3 months before savings start
for p in [0.025, 0.25, 0.5]:
    log(f"With a {DELAY_MONTHS}-month implementation delay, first-year expected net benefit at P = {p:.1%}: "
        f"${p * 0.5 * gap_yr * (12 - DELAY_MONTHS) / 12 - AUDIT_COST:+,.0f} (switching/contract costs not included)")
log(f"Break-even probability with the {DELAY_MONTHS}-month delay: "
    f"{AUDIT_COST / (0.5 * gap_yr * (12 - DELAY_MONTHS) / 12):.1%} (vs {AUDIT_COST / (0.5 * gap_yr):.1%} with no delay)")
log("So the audit is NOT positive in every scenario: at a zero chance of a real premium it costs ~$400. It breaks even at "
    "about 2.5% under these assumptions (50% recovery, one year, no further costs). Growth: all values use H1 x 2 volume.")

# ================================================================ 5. ID-free pilot metric: Garden's share of company traffic
log("\n# 5. ID-free pilot metric: Garden's share of company transactions")
txd = d.groupby(["dt", "Branch"])["Transaction ID"].nunique().unstack()
txd["share"] = txd["Garden"] / txd.sum(axis=1)
txd["dow"] = txd.index.dayofweek
txd["t"] = np.arange(len(txd))
rows = []
for m in [3, 4, 5, 6]:
    tr, te = txd[txd.index.month < m], txd[txd.index.month == m]
    f = smf.ols("share ~ C(dow) + t", data=tr).fit()
    pred_share = f.predict(te).mean()
    # M1 monthly-total bias for comparison: Garden txns, log-linear weekday + trend
    g = smf.ols("np.log(Garden) ~ C(dow) + t", data=tr).fit()
    m1_bias = te["Garden"].sum() / np.exp(g.predict(te)).sum() - 1
    rows.append({"test month": m, "share actual": te["share"].mean(), "share predicted": pred_share,
                 "share error (relative)": te["share"].mean() / pred_share - 1,
                 "M1 Garden-txns monthly error": m1_bias})
bt = pd.DataFrame(rows).set_index("test month")
log.table("Monthly backtest: Garden share of company traffic vs M1 Garden traffic (relative error of the monthly total)",
          bt.round(4))
sd_daily = (txd["share"] - smf.ols("share ~ C(dow) + t", data=txd).fit().fittedvalues).std() / txd["share"].mean()
mde_share = 2.8 * np.sqrt(sd_daily ** 2 / 30 + bt["share error (relative)"].std() ** 2)
mde_m1 = 2.8 * np.sqrt(0.113 ** 2 / 30 + bt["M1 Garden-txns monthly error"].std() ** 2) + abs(bt["M1 Garden-txns monthly error"].mean())
log(f"Garden's share is stable: {txd['share'].resample('M').mean().min():.1%} to {txd['share'].resample('M').mean().max():.1%} by month.")
log(f"One-month detectable change, including month-level error (ESTIMATE): Garden share metric ~{mde_share:.1%}; "
    f"M1 traffic metric ~{mde_m1:.1%}. M1's monthly-total errors range {bt['M1 Garden-txns monthly error'].min():+.1%} to "
    f"{bt['M1 Garden-txns monthly error'].max():+.1%} (mean {bt['M1 Garden-txns monthly error'].mean():+.1%}); daily-noise-only "
    "power calculations (script 03: ~6%) understate this month-level error.")
# Same units as the break-even: a Garden traffic drop of x moves Garden/others by x, but Garden's SHARE only by ~x*(1-share).
txd["ratio"] = txd["Garden"] / (txd["Harbour"] + txd["Uptown"])
rows = []
for m in [3, 4, 5, 6]:
    tr, te = txd[txd.index.month < m], txd[txd.index.month == m]
    f = smf.ols("np.log(ratio) ~ C(dow) + t", data=tr).fit()
    rows.append({"test month": m, "ratio monthly error": te["ratio"].mean() / np.exp(f.predict(te)).mean() - 1})
rbt = pd.DataFrame(rows).set_index("test month")
sd_ratio = np.log(txd["ratio"]).sub(smf.ols("np.log(ratio) ~ C(dow) + t", data=txd).fit().fittedvalues).std()
mde_ratio = 2.8 * np.sqrt(sd_ratio ** 2 / 30 + rbt["ratio monthly error"].std() ** 2)
log.table("Monthly backtest of Garden / (Harbour + Uptown) transactions", rbt.round(4))
log("NOTE: the absolute detectable-drop figures in this section double-count noise (monthly errors already include daily "
    "noise) and are superseded by script 15's fixed-origin backtest. Use them only to RANK the metrics against each other.")
log(f"In Garden-traffic units: Garden-share metric detects ~{mde_share / (1 - txd['share'].mean()):.1%} "
    f"(a {mde_share:.1%} share change = that much Garden traffic); Garden/others ratio ~{mde_ratio:.1%}; "
    f"M1 traffic vs forecast ~{mde_m1:.1%}. Break-even Garden volume loss for +5%: 9.6%.")
log("Recommendation: primary pilot metric = Garden traffic vs the frozen M1 forecast (most sensitive, below break-even). "
    "Robustness check = Garden relative to Harbour + Uptown, which cancels company-wide shocks (holiday, slowdown) but is "
    "noisier. Neither needs Customer IDs. If the two disagree, the result is inconclusive (see README section 6 for the "
    "final protocol).")

fig, ax = plt.subplots(figsize=(8, 3.8))
ax.plot(txd.index, txd["share"].rolling(7, center=True).mean() * 100, color="#c05621")
ax.set(ylabel="Garden share of company transactions (%)", ylim=(25, 40),
       title="Garden's share of traffic is stable - a pilot metric that cancels company-wide shocks")
fig.tight_layout(); fig.savefig(FIG / "18_garden_share.png", dpi=150); plt.close(fig)

# ================================================================ 6. Implementation costs (ASSUMPTIONS)
log("\n# 6. Net annual value after implementation costs (ESTIMATE; implementation costs are assumptions, not data)")
IMPL = "one-off implementation cost $ (audit, menu/POS changes, monitoring, supplier switching)"
rows = []
for impl in [0, 1000, 3000]:
    rows.append({IMPL: impl,
                 "real premium, 50% recovered, e=-1": 0.5 * gap_yr + st.loc[-1.0, 0.5] - impl,
                 "real premium, 100% recovered, e=0": gap_yr + st.loc[0.0, 1.0] - impl,
                 "allocation (no cash saving), e=-1": st.loc[-1.0, 1.0] - impl,
                 "allocation (no cash saving), e=0": st.loc[0.0, 1.0] - impl})
log.table("Full 12 months of post-implementation benefits minus one-off implementation costs, $ (implementation-year value is "
          "lower because of delays and can be negative in the allocation case)",
          pd.DataFrame(rows).set_index(IMPL).round(0))
log("Reading: even a $3,000 one-off cost leaves the real-premium cases clearly positive; in the allocation case the price "
    "rise alone can be close to break-even in year one at elasticity -1.")
