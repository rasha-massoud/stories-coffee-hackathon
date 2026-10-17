"""Are the three 'Dog' menu items (low popularity, low GP per unit) dead weight, or do they come with profitable baskets?
For each item: how often it is bought alone, and the gross profit of the OTHER items in baskets that contain it, compared
with the average basket. Co-purchase is not proof that the item attracts the visit, so this only informs a removal test."""
import pandas as pd

from common import GP, Log, load

log = Log("18_menu_anchor_check")
d = load()
DOGS = ["Espresso", "Mint Tea", "English Breakfast Tea"]
tx = d.groupby("Transaction ID").agg(gp=(GP, "sum"), items=("Quantity", "sum"))
avg_basket_gp = tx["gp"].mean()

rows = []
for p in DOGS:
    ids = d.loc[d["Product"] == p, "Transaction ID"].unique()
    sub = d[d["Transaction ID"].isin(ids)]
    own = sub[sub["Product"] == p].groupby("Transaction ID")[GP].sum()
    other = sub[sub["Product"] != p].groupby("Transaction ID")[GP].sum().reindex(ids, fill_value=0)
    rows.append({"item": p, "baskets/yr": len(ids) * 2, "bought alone": (other == 0).mean(),
                 "own GP per basket": own.mean(), "GP of other items in its baskets": other.mean(),
                 "total basket GP": (own + other).mean(), "average basket GP (all)": avg_basket_gp,
                 "GP/yr of whole baskets containing it": (own + other).sum() * 2})
res = pd.DataFrame(rows).set_index("item")
log("# Menu 'Dogs': dead weight or traffic anchors?")
log.table("Baskets containing each low-performing item (observed; per year = H1 x 2)", res.round(2))
log(f"Upper bound at risk if the item were removed AND every one of its baskets were lost: "
    f"{', '.join(f'{i} ${v:,.0f}/yr' for i, v in res['GP/yr of whole baskets containing it'].items())}. "
    f"Lower bound if every buyer simply switched to another item: about $0 (or a gain if they switch to a higher-GP item).")
log("Reading: compare 'total basket GP' with the average basket. Items whose baskets are as valuable as average, and are "
    "rarely bought alone, may be part of larger orders; removing them risks more than their own small GP. The data can't "
    "tell whether customers would switch or leave, so the action is a one-branch removal test, not a menu decision.")
