# Earlier ZELVO demonstration corridor (v1)

The current selected preset is documented in [the 46.9% demo report](demo-target.md). This earlier preset and its measurements are preserved as development evidence.

The selected matched SUMO demonstration achieved **zero ambulance stops and zero stopped-on-red seconds with learned ZELVO**, compared with **one stop and 28.5 stopped-on-red seconds under ordinary actuated signals**.

| Measurement | Ordinary actuated signals | Learned ZELVO |
|---|---:|---:|
| Ambulance journey | 153.6 s | 119.5 s |
| Stopped on red | 28.5 s | 0.0 s |
| Stops after first movement | 1 | 0 |
| Ordinary trips completed | 300 / 300 | 300 / 300 |
| Collisions / teleports / phase audit errors | 0 / 0 / 0 | 0 / 0 / 0 |

Journey saving: **34.1 seconds, 22.2%**. The 0.1 s total stopped-time reading in the ZELVO run is its initial stationary simulation step; it has no later stop event. Zero waiting here means no stopped-on-red time, not instantaneous signal response: at the main junction the ambulance enters the 150 m observation zone 7.5 s before green, continues moving, and crosses after 9.0 s. Ordinary signals take 39.3 s to green and 40.1 s to crossing from zone entry.

## Corridor and demand

- Hospital-bound asymmetric OSM road geometry in the 43-controller Bengaluru hospital district; three controlled junctions, not an isolated synthetic intersection.
- The main intervention is controller `cluster_10839396276_14127615263_14127615264_14127615265_#2more`, ambulance movement 11 from `373574994#6_0` to `373574994#8_0`. Receiving length: **184.35 m**. Other corridor receiving lengths: **76.2 m** and **13.22 m**.
- Exactly 300 ordinary vehicles and one ambulance. Sixty saved ordinary trips are explicitly reassigned to opposing left-turn traffic, departing every 1.5 s from simulation second 60. The ambulance departs at second 20. Other ordinary trips retain saved demand. All assignments and departure times are identical across policies.
- The ordinary baseline issues no ZELVO signal writes. ZELVO accelerates legal phase succession and holds permitted greens, preserving minimum service, yellows, all-reds and receiving-space checks.
- Both episodes continue to a common 700 s horizon after the ambulance arrives. Input hashes and engine version are matched; raw evidence is retained.

This is a **curated, tuned demonstration**, not an unbiased evaluation sample or a guarantee for arbitrary traffic intensity. Earlier unsuccessful candidates remain recorded: the original long-link trial, a 20-car corridor cohort, and cross traffic with a later ambulance departure. No failed candidate is counted as a successful demo.

## Ordinary traffic and AI contribution

Ordinary accumulated in-network time loss fell from 10,355.38 to 10,173.31 s, but insertion delay increased from 2,722.7 to 3,131.3 s. Their combined burden therefore **increased by 226.53 vehicle-seconds**. Mean ordinary waiting fell from 7.42 to 6.93 s while maximum waiting increased from 112.6 to 138.4 s. The ambulance benefit does not imply every other road user benefits.

The loaded gradient-boosting model performed 118 forecasts with no support fallbacks. Replaying the observed trajectory produces different learned versus analytical request sets at nine of 50 planning ticks. This confirms active learned inference; it does not establish how much of the travel-time saving uniquely requires ML. See [model audit](demo-model-audit.json).

## Reproduction

```powershell
.\.venv\Scripts\python.exe scripts/prepare-demo.py --cross-traffic 60 --depart 20
.\.venv\Scripts\python.exe -m zelvo run --config scenarios/bengaluru-hospital/demo-long-links-cross-60-depart-20.json --controller actuated --output results/demo-long-links-cross-60-depart-20
.\.venv\Scripts\python.exe -m zelvo run --config scenarios/bengaluru-hospital/demo-long-links-cross-60-depart-20.json --controller zelvo_ai --model models/predictor.joblib --output results/demo-long-links-cross-60-depart-20
.\.venv\Scripts\python.exe scripts/report-demo.py --name demo-long-links-cross-60-depart-20 --require-target
```

The reporting command rejects mismatched inputs and exits unsuccessfully if the measured demo target fails. Actual paired evidence: [selected run comparison](demo-long-links-cross-60-depart-20.json). Independent replay: [replay comparison](demo-replay.json).

## Longer-journey evaluation

The next evaluation should use a geographically longer hospital-bound route with more signalized junctions. A roughly 20-minute *measured baseline journey* is a useful target; setting the simulation horizon to 20 minutes does not create a 20-minute journey. Select origins and valid routes from geometry before inspecting treatment outcomes; avoid artificial loops or extra traffic lights. Record actual distance, signal count, per-junction red stops and crossing delays, total journey time, insertion delays, safety and ordinary traffic effects.

More signal delays create more opportunities for absolute savings. Signal-free distance alone does not. Results must come from matched executions across seeds and traffic levels; this short demo's 22.2% saving cannot be extrapolated to a 20-minute route. The 282-controller stress map remains a candidate, with import warnings and short serial-link handling still requiring validation before larger benchmark claims.
