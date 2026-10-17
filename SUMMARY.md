# Stories Coffee: one-page summary

**Team:** Abdallah Makke, Racha Massoud, Christia Daoud · EECE490, AUB

**The finding.** Garden earns **46.9%** gross margin; Harbour earns **65.0%** on the same menu. For all 45 items, **Garden's recorded unit cost =
Harbour's × 1.43 and Garden's price = Harbour's ÷ 1.05** (~4.8% lower), exactly after rounding to cents. Uptown's prices in turn equal
Garden's × 0.96, consistent with coordinated price lists (which list is the source can't be seen in the data). The observed differences in mix,
discounts, basket and timing don't explain the gap. The 1.43 is a rule someone set: a supplier contract, delivery surcharge, overhead allocation, or cost-sheet error.

**The money (annual gross profit, estimates).**

| Action | If the 1.43× is real cost | If it is an accounting allocation |
|---|---|---|
| 1. Audit, then fix Garden's cost (~$400 of staff time) | +$15.9k (50% closed) to +$31.8k (100%) | $0 cash; corrected P&L |
| 2. +5% Garden prices, after a 1-month pilot | +$3.2–10.0k | +$3.2–10.0k (avoidable cost ≈ Harbour's) |
| **Combined** (50% recovery + elasticity −1 → 100% recovery + no volume loss) | **≈ $20–42k/yr** | **≈ $3–10k/yr** |

The audit's first-year expected net benefit (3-month implementation delay, 50% recovery) is −$400 at a 0% chance the premium is real and +$2.6k at 25%. Lower-confidence extras:
buying at Uptown's (cheapest) costs everywhere, +$7.2k beyond the Garden fix; reviewing an always-on 10% discount with no observed targeting ($3.1k/yr, but
dropping it breaks even at 0.9% of visits lost, so check its eligibility rules before testing a retarget).

**Why we trust it.**
- The rules match **45 of 45** items, and the gap is robust to every data-cleaning choice (< 1%).
- The forecast model beats a naive and a stronger baseline, plus gradient boosting and random forest, on **4 of 4** unseen months
  (9.3% vs 10.0–14.3% MAPE).
- **A backtested pilot rule:** frozen forecasts missed monthly Garden traffic by ~2% (fixed-origin backtest). The pilot runs one calendar month and keeps
  the rise only if the measured loss is below 6.1% (3.9% once costs are fixed or if the 1.43 is an allocation). For the traffic-threshold component alone,
  under a normal approximation, it keeps a harmless rise 82–100% of the time and a harmful 12%-loss rise at most ~3%, across ±2% forecast bias. These are
  approximations from few windows, not guarantees for the full protocol.
- **Stress test:** the price rise stays positive at elasticity −1 whatever the cost fix; break-even is −1.93 today and −1.47 after a full fix.
- **What we withdrew:** promo weeks measure category *share*, not demand, so they are not used as elasticity evidence.

**The assumption that could change it.** If the 1.43× is rent or overhead booked into cost of goods, action 1 saves no cash. That's why the audit comes first.

**Also found.**
- **Customer IDs show no detectable persistence:** 6 of 6 consistency tests sit inside the range of 100 random shuffles (an illustrative check suggests a
  modest branch habit would have shown). Validate ID assignment before any loyalty or CRM decision.
- **14 candidate product pairings beat a popularity-preserving shuffle and replicate on unseen months:** matcha & tea drinks with sweet bakery
  (1.6–2.4×) and savoury food with water (1.6–2.9×), giving two specific, no-discount barista prompts to test.
- Promo weeks showed no detectable traffic lift.
- Tuesday ×1.5 and Saturday ×0.7, broadly similar in every segment.
- Traffic is +6.8% at the turn of the month, so pilots should run full calendar months (or control for the calendar).
- Growth is +8.5%/month, all from more visits; check Harbour's evening capacity.

Full report: [README.md](README.md) · Appendix: [APPENDIX.md](APPENDIX.md)
