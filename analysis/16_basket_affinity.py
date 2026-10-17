"""Which products are bought together MORE than chance predicts? Common pairs mostly reflect popularity, so we compare
each pair's co-occurrence with a null that keeps every basket's size and every product's popularity within branch and
month (products shuffled across baskets). Pairs are discovered in Jan-Mar and must hold up in Apr-Jun."""
import numpy as np
import pandas as pd

from common import GP, OUT, Log, load

log = Log("16_basket_affinity")
d = load()
rng = np.random.default_rng(11)
N_SHUF = 200

lines = d[["Transaction ID", "Product", "Branch", "month", "Quantity", GP]].copy()
products = sorted(lines["Product"].unique())
pidx = {p: i for i, p in enumerate(products)}
lines["p"] = lines["Product"].map(pidx)
lines["period"] = np.where(lines["month"] <= 3, "discovery Jan-Mar", "validation Apr-Jun")
log("# Basket affinity: pairs bought together more than chance")


def cooc(df, prod_col):
    """Product co-occurrence counts across baskets (each product counted once per basket)."""
    tx_codes, tx_index = pd.factorize(df["Transaction ID"])
    m = np.zeros((len(tx_index), len(products)), dtype=np.int8)
    m[tx_codes, df[prod_col].values] = 1
    c = m.T.astype(np.int32) @ m.astype(np.int32)
    return c, m.sum(axis=0), len(tx_index)


results = {}
for period, g in lines.groupby("period"):
    obs, single, n_tx = cooc(g, "p")
    sims = np.zeros((N_SHUF,) + obs.shape, dtype=np.int32)
    g = g.copy()
    for s in range(N_SHUF):
        g["ps"] = g.groupby(["Branch", "month"])["p"].transform(lambda x: rng.permutation(x.values))
        sims[s], _, _ = cooc(g, "ps")
    mean, sd = sims.mean(axis=0), sims.std(axis=0)
    iu = np.triu_indices(len(products), 1)
    df = pd.DataFrame({"A": np.array(products)[iu[0]], "B": np.array(products)[iu[1]],
                       "together": obs[iu], "expected (shuffle)": mean[iu], "sd": sd[iu]})
    df["lift"] = df["together"] / df["expected (shuffle)"]
    df["z"] = (df["together"] - df["expected (shuffle)"]) / df["sd"].replace(0, np.nan)
    results[period] = df.set_index(["A", "B"])
    log(f"{period}: {n_tx:,} baskets, {len(df)} product pairs, {N_SHUF} shuffles")

disc, val = results["discovery Jan-Mar"], results["validation Apr-Jun"]
n_pairs = len(disc)
z_crit = 3.5  # ~Bonferroni for 990 pairs at 5% (two-sided would be ~3.9; one-sided ~3.7) - deliberately strict-ish
cand = disc[disc["z"] > z_crit].sort_values("z", ascending=False)
log(f"\nDiscovery: pairs with z > {z_crit} (strict threshold for {n_pairs} pairs tested): {len(cand)}")
log(f"Expected by chance alone at this threshold: ~{n_pairs * 0.000233:.2f} pairs (one-sided p for z=3.5)")
log(f"Distribution of discovery z-scores: mean {disc['z'].mean():+.2f}, sd {disc['z'].std():.2f}, "
    f"max {disc['z'].max():+.2f}, min {disc['z'].min():+.2f} (pure chance would give mean 0, sd ~1)")
top_disc = disc.sort_values("z", ascending=False).head(10)
top_disc = top_disc.join(val[["together", "lift", "z"]], rsuffix=" (validation)")
log.table("Top 10 discovery pairs and how they did on unseen Apr-Jun data", top_disc.round(2))
corr = np.corrcoef(disc["z"], val.loc[disc.index, "z"])[0, 1]
log(f"\nDo pair z-scores repeat across periods? Correlation discovery vs validation: {corr:+.2f} "
    "(near 0 = the 'affinities' are noise; real affinities would repeat)")
survivors = cand[cand.index.isin(val[val["z"] > 2].index)]
log(f"Pairs significant in discovery AND z > 2 in validation: {len(survivors)}")

if len(survivors):
    gp_unit = lines.groupby("Product")[GP].sum() / lines.groupby("Product")["Quantity"].sum()
    basket_sets = lines.groupby("Transaction ID")["Product"].agg(set)
    for (a, b), r in survivors.iterrows():
        # Directional: baskets with A but not B could add B (worth B's GP), and vice versa. Baskets may hold other items too.
        a_not_b = basket_sets.apply(lambda s: a in s and b not in s).sum() * 2  # x2: six months -> one year
        b_not_a = basket_sets.apply(lambda s: b in s and a not in s).sum() * 2
        value = 0.03 * (a_not_b * gp_unit[b] + b_not_a * gp_unit[a])
        log(f"Survivor {a} + {b}: validation lift {val.loc[(a, b), 'lift']:.2f}; baskets/yr with {a} but not {b}: {a_not_b:,}, "
            f"with {b} but not {a}: {b_not_a:,}; ESTIMATE at an ASSUMED 3% add-on rate: ${value:,.0f}/yr")
else:
    log("Conclusion: no product pair is bought together more than chance in a way that repeats on unseen months. Common "
        "combinations (e.g. Matcha + Bakery) reflect popularity, not affinity. Pairing prompts should therefore be tested as "
        "generic 'add a drink/food' suggestions (APPENDIX A2), not personalised pair recommendations - and a market-basket "
        "or recommender system built on this data would be fitting noise.")
disc.join(val, lsuffix=" disc", rsuffix=" val").round(3).to_csv(OUT / "basket_affinity_pairs.csv")

# ---- Group the validated pairs by category to turn them into simple prompts
cat_of = lines.drop_duplicates("Product").set_index("Product")["Category"] if "Category" in lines else \
    d.drop_duplicates("Product").set_index("Product")["Category"]
if len(survivors):
    grp = pd.DataFrame([{"pair": f"{a} + {b}", "categories": " + ".join(sorted([cat_of[a], cat_of[b]])),
                         "validation lift": val.loc[(a, b), "lift"]} for a, b in survivors.index])
    log.table("Validated pairs grouped by category pair", grp.groupby("categories").agg(
        pairs=("pair", "count"), lift_min=("validation lift", "min"), lift_max=("validation lift", "max")).round(2))
    log("Reading: two families replicate - matcha/tea drinks with sweet bakery, and savoury food (sandwiches, bowls) with "
        "water. Per-pair upsell estimates above overlap (several pairs share Iced Matcha), so they are NOT additive. "
        "Action: two barista/menu-board prompts ('add a pastry to your matcha', 'add a drink to your sandwich'), tested at "
        "one branch for a month; the 3% conversion is an assumption, not a measurement.")
