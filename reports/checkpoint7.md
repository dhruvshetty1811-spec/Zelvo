# Engine checkpoint: slices 1–7

The engine runs actual SUMO traffic on saved Bengaluru OSM roads. The hospital district has 43 traffic-light controllers and 226 controlled movements. The separate 282-controller stress network loads, but retains detector warnings and needs further validation.

## Matched hospital example

Seed 42, 300 ordinary vehicles, two ambulances, fixed hospital routes, 100 ms physics and a common 700-second horizon. All variants share the same network, demand, engine and embedded SUMO 1.26.0 backend. Every variant uses the common corridor occupancy guard; the actuated baseline makes no priority requests. No pedestrians are present in this particular matched example.

| Controller | Ambulance 0 journey | Ambulance 1 journey | Ordinary arrivals | Whole-run status |
|---|---:|---:|---:|---|
| Fixed time | 346.0 s | 245.7 s | 288/300 | Incomplete |
| Actuated baseline | 223.3 s | 175.1 s | 300/300 | Completed |
| Local preemption | 214.8 s | 159.7 s | 300/300 | Completed |
| Analytical ZELVO | 214.7 s | 159.7 s | 300/300 | Completed |
| Learned ZELVO | 214.8 s | 159.7 s | 300/300 | Completed |

All five runs recorded zero collisions, teleports and phase-audit errors. This does not establish field safety or the correctness of inferred signal plans.

Against the actuated baseline, learned ZELVO saved 8.5 and 15.4 seconds in the two journeys. Stops fell from 5/3 to 4/2. Mean signal response across the ten recorded approaches fell from 12.04 to 8.23 seconds. Response starts at the common 150 m approach zone and ends at first movement-permitted green; it does not measure dispatch response or guarantee immediate passage.

Ordinary accumulated time loss increased from 12,003.42 to 12,119.40 seconds, a 115.98-second total increase across 300 trips. Outcomes and tradeoffs must remain together. This one matched instance is not a population benchmark.

Sources: [actuated versus AI](actuated-vs-ai.json), [analytical versus AI](analytical-vs-ai.json), [local baseline comparison](actuated-vs-local.json), [complete checkpoint summary](checkpoint7.json).

## Genuine local AI

Four scikit-learn gradient boosting estimators predict ETA residuals, lower/upper ETA quantiles and receiving-lane queues ten seconds ahead. The frozen development dataset contains 9,027 labelled observations from 24 runs across eight seeds and three controller policies. All ambulance journeys completed; only six whole-network runs drained, while eighteen retained ordinary traffic and remain incomplete. All records share one engine version and have zero recorded collision or phase-audit failures.

Whole-seed partitions retain every controller variant together:

- Train: 1000, 1002, 1004, 1006.
- Validation: 1003, 1007.
- Test: 1001, 1005.

| Test measurement | Baseline | Learned |
|---|---:|---:|
| ETA mean absolute error | 40.49 s | 7.43 s |
| Receiving-queue mean absolute error | 0.0344 vehicles | 0.0276 vehicles |

Test arrival-interval coverage is 72.3%, below the nominal 80%; these intervals are not calibrated guarantees. Queue labels are mostly zero, so this dataset provides limited evidence for congested queues. Validation queue prediction is slightly worse than persistence. Seed holdout does not establish unseen-route/city generalization or causal policy effects.

In the actual AI episode, 461 learned forecasts were applied with no support fallbacks. Replaying the same observations found seven planning ticks with different request sets. Ambulance journeys were 0.1 seconds slower/equal versus analytical ZELVO. There is no demonstrated extra journey-time benefit from ML in this example, despite improved held-out ETA prediction.

The AI run advanced 700 simulated seconds in 85.05 wall seconds on this machine. Planning mean/max latency was 21.48/303.48 ms across 350 ticks, including ticks after ambulances finished. This is one episode measurement, not a large-campaign runtime projection.

Sources: [model manifest](../models/predictor.json), [decision replay audit](model-decision-audit.json), [full summary](checkpoint7.json). Models, inputs and raw results carry hashes.

## Verification and remaining scope

The full suite passed [61 tests](checkpoint7-tests.txt), followed by a separate passing [creeping-queue regression](creeping-queue-test.txt). Tests include actual SUMO runs, socket/embedded parity, following/conflicting ambulances, stale-data fallback and a temporary lane blockage.

A separate hospital scenario with 60 synthetic walkers completed, with all people observed, zero collisions or phase-audit errors and maximum observed continuous pedestrian wait of 3.7 seconds. This validates execution and recording, not calibrated pedestrian outcomes or a matched pedestrian improvement.

The authority adapter is a tested deterministic emulator. No physical signal controller is connected. Inferred OSM geometry/timings, partial corridor occupancy coverage and uncalibrated traffic remain material limitations.

The 20,000-run evaluation campaign has **not started**. These development runs, prediction calls and the five-controller checkpoint are separate. Benchmark profiling/freezing and the frontend remain subsequent slices. Reproduction commands are in [ENGINE.md](../ENGINE.md).
