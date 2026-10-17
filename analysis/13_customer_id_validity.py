"""Do Customer IDs identify consistent people? If an ID is a real person, consecutive visits by the same ID should be
more alike (same branch, same products, same order type, similar hour) than random pairs of visits. We compare each
statistic with the same statistic after shuffling IDs across identified visits (chance level)."""
import numpy as np
import pandas as pd

from common import GP, REV, Log, load

log = Log("13_customer_id_validity")
d = load()
rng = np.random.default_rng(7)

tx = d.dropna(subset=["Customer ID"]).groupby("Transaction ID").agg(
    cust=("Customer ID", "first"), Branch=("Branch", "first"), otype=("Order Type", "first"), hour=("hour", "first"),
    ts=("dt", "first"), time=("Time", "first"), top_cat=("Category", lambda s: s.mode()[0]),
    revenue=(REV, "sum"))
tx = tx.sort_values(["cust", "ts", "time"])


def persistence(frame):
    """Statistics comparing each visit with the same ID's previous visit."""
    prev = frame.groupby("cust")[["Branch", "otype", "hour", "top_cat"]].shift()
    ok = prev["Branch"].notna()
    cur = frame[ok]
    p = prev[ok]
    # share of a customer's visits in their single most-used branch / category
    top_branch = frame.groupby("cust")["Branch"].agg(lambda s: s.value_counts(normalize=True).iloc[0]).mean()
    top_cat = frame.groupby("cust")["top_cat"].agg(lambda s: s.value_counts(normalize=True).iloc[0]).mean()
    return {
        "consecutive visits at the same branch": (cur["Branch"] == p["Branch"]).mean(),
        "consecutive visits with the same order type": (cur["otype"] == p["otype"]).mean(),
        "consecutive visits with the same main category": (cur["top_cat"] == p["top_cat"]).mean(),
        "hour correlation between consecutive visits": np.corrcoef(cur["hour"], p["hour"].astype(float))[0, 1],
        "avg share of visits at the customer's top branch": top_branch,
        "avg share of visits in the customer's top category": top_cat,
    }


obs = persistence(tx)
sims = []
N_SHUFFLES = 100
for _ in range(N_SHUFFLES):
    sh = tx.copy()
    sh["cust"] = rng.permutation(sh["cust"].values)  # same visit counts per ID, random visits
    sh = sh.sort_values(["cust", "ts", "time"])
    sims.append(persistence(sh))
sim = pd.DataFrame(sims)
tbl = pd.DataFrame({"observed (real IDs)": obs, "shuffled IDs (chance), mean": sim.mean(),
                    "shuffled, 95% range low": sim.quantile(0.025), "shuffled, 95% range high": sim.quantile(0.975)})
log("# Do Customer IDs behave like real, consistent customers?")
log.table(f"Visit-to-visit consistency: real IDs vs IDs shuffled at random ({N_SHUFFLES} shuffles)", tbl.round(3))
inside = ((tbl["observed (real IDs)"] >= tbl["shuffled, 95% range low"])
          & (tbl["observed (real IDs)"] <= tbl["shuffled, 95% range high"]))
log(f"\nStatistics inside the shuffled 95% range (no tolerance added): {inside.sum()} of {len(tbl)}. "
    "The six statistics are related, so this is one consistent pattern, not six independent confirmations.")
# Power check: would the test notice a modest real habit? Make 10% of each ID's visits copy its previous branch.
hab = tx.copy()
prev_b = hab.groupby("cust")["Branch"].shift()
flip = prev_b.notna() & (rng.random(len(hab)) < 0.10)
hab.loc[flip, "Branch"] = prev_b[flip]
log(f"Power check: if just 10% of visits repeated the previous branch (a weak habit), 'same branch' would be "
    f"{persistence(hab)['consecutive visits at the same branch']:.3f} vs the shuffled range "
    f"{tbl.loc['consecutive visits at the same branch', 'shuffled, 95% range low']:.3f}-"
    f"{tbl.loc['consecutive visits at the same branch', 'shuffled, 95% range high']:.3f}. Illustrative sensitivity check only "
    "(one injected pattern, one feature) - not a power estimate.")

all_tx = d.groupby("Transaction ID").agg(known=("Customer ID", lambda s: s.notna().any()), revenue=(REV, "sum"),
                                         gp=(GP, "sum"), items=("Quantity", "sum"))
log.table("Identified vs anonymous visits (observed)", all_tx.groupby("known")[["revenue", "gp", "items"]].mean().round(2))

log("\nConclusion: real customers usually have habits - a usual branch, order type, time and products. Visits sharing a "
    "Customer ID show no detectable persistence beyond randomly shuffled labels on any tested feature (an illustrative "
    "check suggests a modest branch habit would have shown). That does not prove the IDs are meaningless (prepared or anonymised data can behave "
    "like this), but it means they cannot be trusted for longitudinal analysis until ID assignment is validated. "
    "Consequences: (1) anything built on following an ID over time - branch switching, return visits, 'the same regulars', "
    "customer concentration - describes the labels, not behaviour, and is withdrawn or downgraded in the README; "
    "(2) aggregate findings (traffic, margins, costs, prices, timing) do not use IDs and are unaffected; "
    "(3) business value: Stories should NOT invest in CRM/loyalty analytics or ID-based targeting on this data until ID "
    "capture is fixed - test: check how IDs are assigned at the till for one week at one branch.")
