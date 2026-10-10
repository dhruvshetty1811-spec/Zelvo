# Selected demo: 46.9% shorter ambulance journey

The selected demonstration meets the current acceptance criteria: **45–55% shorter complete ambulance journey** and **at most 2 seconds stopped waiting**, with identical inputs for ordinary actuated signals and learned ZELVO. Two independent matched pairs reproduced the same measurements.

| Measured outcome | Ordinary actuation | Learned ZELVO |
|---|---:|---:|
| Ambulance journey | 144.2 s | 76.6 s |
| Stopped on red | 58.7 s | 0.0 s |
| Stops after first movement | 2 | 0 |
| Ordinary trips completed | 300 / 300 | 300 / 300 |
| Collisions / teleports / phase audit errors | 0 / 0 / 0 | 0 / 0 / 0 |

Savings: **67.6 s / 144.2 s = 46.8793%**. Both ambulances depart at the scheduled second 60, so insertion delay does not create the ambulance benefit. ZELVO's recorded 0.1 s total stopped time is its initial stationary step, with no later stop event.

## Exact scenario

Selected configuration: `scenarios/bengaluru-hospital/demo-long-links-cross-60-start-3-second-60-second-at-120.json`. The manifest `scenarios/demo-selection.json` records input/model hashes and evidence paths. The earlier 22.2% selection remains in `scenarios/demo-selection-v1.json`.

The ambulance follows **913.35 m of external road edges** toward Victoria Hospital through three OSM-derived signal controllers, within the existing **43-controller district**. The main two priority opportunities have receiving lanes **184.35 m** and **13.22 m** long. The preceding approach includes a 150 m road segment. These are actual imported link lengths; the network has not been stretched. This is a focused corridor demonstration, not a 30-minute journey.

There are **300 ordinary vehicles: 239 cars, 52 motorcycles and nine buses**, plus one ambulance. From the saved original demand, 60 trips are reassigned to the first opposing left turn, departing every 1.5 s from second 60; another 60 become cars on the second opposing left turn, departing every 1.5 s from second 120. The other 180 ordinary trips retain their original routes, types and departures. The ambulance starts at route index 3 of the original hospital route, at second 60. Both policies receive byte-identical route files and driving parameters.

These cross-traffic cohorts create sustained conflicting demand. Ordinary actuation serves that demand through its existing programs. ZELVO prepares legal phase succession before ambulance arrival and protects the arriving movement. There are no extra red intervals, forced ambulance stops, policy-specific traffic changes or overridden ambulance driving rules. Both runs use 100 ms dynamics and continue to the common 700 s horizon.

## Evidence and limitations

- [Original matched pair](demo-long-links-cross-60-start-3-second-60-second-at-120.json)
- [Independent matched replay](demo-target-replay.json)
- [Active learned-model audit](demo-target-model-audit.json): 54 forecasts, no support fallbacks; learned versus analytical request sets differ at seven of 28 replayed ticks. This establishes active ML use, not a causal estimate of its incremental travel-time contribution over analytical control.
- `reports/demo-target-tests.txt`: 25 focused tests passed, including controller, planner, measurement, preserved-demand and route-selection checks. The prior full engine suite passed 66 tests; engine source was unchanged during this demo refinement.

The scenario was **curated and tuned using development trials** to demonstrate the requested conditions. It does not establish a 46.9% average improvement, a guarantee at other traffic intensities, or real-road performance. Earlier unsuccessful candidates and their raw results are retained. The old 22.2% example is explicitly rejected by the new acceptance gate.

Ordinary accumulated in-network time loss decreases **8498.28 → 8357.52 vehicle-seconds**, but insertion delay increases **4799.20 → 5338.00 vehicle-seconds**. Their combined burden therefore increases **398.04 vehicle-seconds**. Mean ordinary waiting decreases **5.766 → 5.429 s**, while maximum waiting increases **91.4 → 92.6 s**. This tradeoff remains part of the result.

The larger-map 30-minute calibration pilot was interrupted after the requirement changed. It remains a failed/partial record at `results/long-corridor-calibration/run-6f38702be0a04712a6c9834b1ae04662`, at 481.5 simulated seconds, before ambulance departure. It provides no completed journey or treatment comparison. The saved 14-controller longer-route geometry remains available for subsequent evaluation. The 20,000-run evaluation has not started.

## Reproduction

```powershell
.\.venv\Scripts\python.exe scripts/prepare-demo.py --cross-traffic 60 --route-start 3 --second-cross-traffic 60 --second-cross-start 120
.\.venv\Scripts\python.exe -m zelvo run --config scenarios/bengaluru-hospital/demo-long-links-cross-60-start-3-second-60-second-at-120.json --controller actuated --output results/demo-long-links-cross-60-start-3-second-60-second-at-120
.\.venv\Scripts\python.exe -m zelvo run --config scenarios/bengaluru-hospital/demo-long-links-cross-60-start-3-second-60-second-at-120.json --controller zelvo_ai --model models/predictor.joblib --output results/demo-long-links-cross-60-start-3-second-60-second-at-120
.\.venv\Scripts\python.exe scripts/report-demo.py --name demo-long-links-cross-60-start-3-second-60-second-at-120 --min-saved-percent 45 --max-saved-percent 55 --max-wait-s 2 --require-target
```

Use a fresh output directory for the independent replay, then pass it to the reporter with `--results` and `--report reports/demo-target-replay.json`. `scripts/select-demo.py` requires both completed comparisons to satisfy the thresholds, verifies distinct execution IDs and equal replay measurements, checks current input/model hashes and writes the selected manifest. The report command exits unsuccessfully when measurements fail acceptance; target values never replace measured values.
