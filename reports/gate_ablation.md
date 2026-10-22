# Quality-gate ablation

The gate has exactly five checks: contact, rail_hi, rail_lo, flat, jump. They are defined in `firmware/src/main.cpp`: contact = either leads-off pin, high rail = average >=4090 or >=5 of 20 raw ADC samples at >=4090, low rail = average <=50, flat = sample SD of last 60 logged averages <2, jump = absolute change >1200 from previous cycle. Historical main CSV contains leads-off and average only, with no n_sat/min/max, so high-rail evaluation uses average >=4090 and may miss mixed saturated cycles.

`gate_ablation.csv` reports each check alone and full gate; `gate_ablation_combinations.csv` also reports leave-one-out. Rail-valued rows are the only directly known fault label. All other rows are called non-rail proxy and must not be interpreted as complete good labels; they may include undetected corruption. Overlap is preserved through OR composition. The baseline replay uses the available logged values and firmware-like ring, but does not prove deployed fault causality.

No check should be removed based on this single dataset. Check redundancy is dataset-specific: identical rejection masks are observable overlap, not evidence of functional equivalence on unrecorded failure modes.
