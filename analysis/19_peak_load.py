"""Peak load in 15-minute slots. Hourly averages hide queues: staffing and counter capacity have to cope with the busiest
15 minutes, not the average hour. We measure how bursty demand is and what the busiest slots look like now and if
growth continues (projection = ESTIMATE)."""
import numpy as np
import pandas as pd

from common import BRANCHES, Log, load

log = Log("19_peak_load")
d = load()
tx = d.groupby("Transaction ID").agg(Branch=("Branch", "first"), dt=("dt", "first"), time=("Time", "first"))
tx["ts"] = pd.to_datetime(tx["dt"].dt.strftime("%Y-%m-%d") + " " + tx["time"])
tx["slot"] = tx["ts"].dt.floor("15min")
tx["month"] = tx["dt"].dt.month
tx["weekday"] = tx["dt"].dt.day_name()

log("# Peak load in 15-minute slots")
rows = []
for b in BRANCHES:
    j = tx[(tx["Branch"] == b) & (tx["month"] == 6)]
    per_slot = j.groupby("slot").size()
    hours = j.groupby(j["ts"].dt.floor("h")).size()
    tue = j[j["weekday"] == "Tuesday"]
    tue_slots = tue.groupby("slot").size()
    rows.append({"branch": b,
                 "busiest 15 min in June (orders)": int(per_slot.max()),
                 "95th pct 15-min slot (orders)": per_slot.quantile(0.95),
                 "busiest hour in June / 4 (orders per 15 min, if spread evenly)": hours.max() / 4,
                 "June Tuesdays: avg of each day's busiest 15 min": tue_slots.groupby(tue_slots.index.date).max().mean()})
res = pd.DataFrame(rows).set_index("branch")
res["peak 15 min vs even spread"] = res["busiest 15 min in June (orders)"] / res[
    "busiest hour in June / 4 (orders per 15 min, if spread evenly)"]
log.table("June peak loads by branch (observed)", res.round(2))
growth = 0.085  # monthly growth from script 06 (ESTIMATE if it continues)
proj = res["June Tuesdays: avg of each day's busiest 15 min"] * (1 + growth) ** 6
log.table("Typical Tuesday peak 15 min: June (observed) and December if +8.5%/month continues (ESTIMATE)",
          pd.DataFrame({"June": res["June Tuesdays: avg of each day's busiest 15 min"], "December (projection)": proj}).round(1))
log("Reading: the busiest 15 minutes carry noticeably more than a quarter of the busiest hour, so staffing to hourly "
    "averages understates peak load. Stories should compare these peak-15-minute counts with how many orders one barista "
    "and one till can actually serve in 15 minutes (not in this data) - that comparison, not the hourly average, says when "
    "queues start. The December figures assume growth continues, which is not established.")
