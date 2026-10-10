# ZELVO implementation plan

Status: engine Slices 1-7 implemented and verified as a simulation prototype, including actual local model training and matched closed-loop results. See [progress.md](progress.md), [checkpoint results](reports/checkpoint7.md) and the checkpoint ledger below. Frontend and the frozen evaluation campaign remain subsequent slices.

## 1. Product and constraints

ZELVO predicts emergency-vehicle progress and coordinates traffic signals across a route, preparing downstream space before releasing upstream traffic. The deliverable is a working, evidence-backed simulation, followed by a frontend showing the same emergency journey with and without ZELVO side by side.

- Use an inspected OpenStreetMap-derived district as the main demonstration network. Synthetic fixtures are for verification only.
- Preserve the complete core loop: observe, predict, coordinate, arbitrate, transition safely, confirm passage, recover, and measure.
- Include mixed traffic, pedestrians, incidents, alternate paths, and competing ambulances.
- Include genuine locally trained machine learning; measure its contribution separately from coordination and preemption.
- Target 20,000 scheduled evaluation executions locally. Report actual completions and failures, never prediction calls as simulation runs.
- Additional software/service budget: INR 0. Use the existing laptop, open-source dependencies, local CPU and disk, and free OSM data. No paid APIs, GPUs, cloud servers, card-required trials, domains, or hosted-map dependencies.
- Build the frontend after the engine, evidence collection, AI, and integration tests work.
- No physical signal controller or authority sandbox is available. Deliver a tested adapter boundary and emulator. Do not claim live deployment or device compatibility without testing the actual target.
- Simulation evidence does not establish real-world travel improvements, medical outcomes, or field safety certification.

Source product brief: [codex.md](codex.md). This file is the engineering plan; the product brief remains unchanged.

## 2. Definition of done

1. An OSM district runs with ordinary vehicles, pedestrians, and ambulance journeys.
2. Five controllers run against common inputs: fixed-time, actuated without preemption, local preemption, analytical ZELVO, and learned-prediction ZELVO.
3. ZELVO observes receiving lanes, prepares bottlenecks downstream, adapts to uncertainty, and safely recovers.
4. Conflicting and compatible emergency requests are handled explicitly.
5. Models are trained locally with held-out runs and a frozen model version for evaluation.
6. The benchmark runner supports the 20,000-execution manifest, checkpointing, failure accounting, and reproducible summaries.
7. Every required journey, junction, network, safety, and compute measurement is recorded or explicitly marked unavailable/censored.
8. Two real simulations are displayed on a shared simulation-time timeline, using identical intended inputs.
9. Submission claims are traceable to saved manifests, versions, measurements, and selected replay records.

## 3. Architecture

```text
Scenario configuration + OSM network + pregenerated demand
  -> independent SUMO worker per execution
  -> observation adapter and district state estimator
  -> analytical or learned arrival/queue predictor
  -> candidate route evaluator and rolling-horizon scheduler
  -> emergency request arbiter
  -> signal safety supervisor
  -> controller adapter
  -> SUMO (or a future documented vendor interface)

Simulation + controller + supervisor
  -> metrics and event recorder
  -> per-run results and experiment summaries
  -> live backend / saved replay
  -> React controls + Canvas renderer, built last
```

Use a modular Python application and separate worker processes, not a distributed service deployment. Each worker exclusively owns one simulation connection, controller state, simulation clock, and output directory. The browser never owns simulation stepping or directly accesses TraCI.

### Technology

| Layer | Choice |
| --- | --- |
| Simulator | Installed Eclipse SUMO 1.26.0; pin compatible Python interfaces |
| Interactive interface | TraCI |
| Batch interface | Evaluate libsumo after compatibility and throughput checks |
| Engine and experiment runner | Python |
| Contracts | Pydantic and JSON, explicit units and schema version |
| Learning | scikit-learn histogram gradient-boosted regressors |
| API, added later | FastAPI |
| Frontend, added last | React, TypeScript, Vite, Canvas |
| Evidence | JSON manifest/summary, CSV records, JSONL events; compressed replay where needed |
| Verification | pytest and headless SUMO integration runs |

### Proposed layout

```text
IMPLEMENTATION.md
README.md
pyproject.toml
src/zelvo/
  contracts.py
  config.py
  runtime.py
  simulation/
  controllers/
  coordination/
  safety/
  integration/
  learning/
  evaluation/
scenarios/
  smoke/                 # tiny verification fixture, not final demo
  district/              # original OSM extract, compilation, patches, demand
tests/
scripts/
backend/                 # introduced later
frontend/                # introduced last
results/                 # generated, ignored by source control
```

## 4. OSM topology pipeline

1. Select a district with several emergency paths, complex junctions, asymmetric links, bottlenecks, and hospital access points. Include a boundary buffer.
2. Download and preserve the original OSM extract, acquisition date, geographic bounds, attribution, and hash.
3. Use osmWebWizard for exploration where helpful. Freeze a repeatable netconvert configuration for the actual build.
4. Inspect the generated topology in SUMO/netedit and apply explicit, versioned corrections.
5. Verify driving side, one-way restrictions, permitted vehicle classes, turn lanes/connections, hospital entrances, and pedestrian access.
6. Review inferred signals and joined controllers. Signal count follows the reviewed geography, rather than adding fictitious signals to meet a numerical target. Aim for a useful district with roughly 30-60 controllers if the selected topology supports it.
7. Preserve all generated warnings and document their resolution.
8. Freeze the compiled network and movement registry before final evaluation.

### Compilation settings and qualifications

| Setting | Requirement |
| --- | --- |
| `--tls.guess true` | Infer candidate signals; inspect results. The documented guessing threshold uses incoming lane speeds. Inference is not evidence of real signal locations. |
| `--tls.join true` | Cluster appropriate controlled nodes; review join distance and exclusions. This is not indiscriminate physical junction merging. |
| `--tls.default-type actuated` | Use actuated ordinary operation; verify resulting program types, min/max durations, and usable detectors. |
| `--tls.allred.time <seconds>` | Generate explicit red-clearance phases. Select documented simulation timings and review wide/complex junctions. A timed all-red does not prove the box is empty. |

SUMO `.net.xml` is a documented XML format. Real geometry does not establish calibrated demand, timings, capacities, or driver behaviour. Mark inferred and synthetic attributes explicitly.

Import OSM geometry once and render exported geometry locally. Do not scrape public map tiles for offline use. Include OSM attribution and applicable data licence notices.

## 5. Traffic and scenarios

Cars, buses with stops, motorcycles using the configured lane model, pedestrians, and one to three simultaneous ambulances form the main scenario. Do not claim that motorcycle lane filtering or other local behaviours are calibrated without evidence.

Pregenerate intended trips using OD zones and time-varying demand. Record scheduled and actual departures, blocked insertion, and unfinished trips. Keep ambulance driving settings identical across comparisons; do not activate red-light-ignoring behaviour in the primary signal-control experiment.

### Ten scenario families

1. Ordinary district operation with minimal disruption.
2. Rush-hour demand concentrated on an arterial.
3. Heavy cross traffic competing with an emergency corridor.
4. Cascading downstream spillback across several links.
5. Temporary lane obstruction on a connector.
6. Unexpected ambulance slowdown.
7. Ambulances requesting conflicting junction movements.
8. Ambulances sharing a corridor or following one another.
9. Active pedestrian clearance on an approaching emergency movement.
10. Delayed/missing observations or controller responses.

Combine each family with four demand levels, five ambulance OD configurations, and twenty seeds. Validate each combination; do not suppress difficult or failed cases. Future incident schedules are known to the scenario engine, not leaked into controller features.

Use a common, specified evaluation horizon (initial target: approximately 30 simulated minutes including warm-up, emergency operation, and recovery). Tune the horizon before freezing the experiment. A journey unfinished at the horizon is censored/unfinished, not a zero-time success. Longer stress scenarios can be separate, clearly identified experiments.

## 6. Control and observation contracts

All times use seconds. Distances use metres; speeds use metres/second. Distinguish absolute simulation timestamps, durations, and wall-clock times.

Each observation includes a timestamp/freshness indicator. Missing data is unknown, never an empty lane. Support a full-observation evaluation mode and a later sensor-limited mode with documented visibility, delay, and loss.

Map route edge pairs to feasible lane connections, signal indices, permitted phases, and receiving lanes using `trafficlight.getControlledLinks()`. One signal can control multiple connections; one joined controller can span multiple junction nodes. `getControlledLanes()` alone does not identify outgoing movements.

Track queue vehicle count, queue spatial extent, vehicles ahead of the ambulance, usable downstream entrance space, inflow, and discharge separately. `lane.getLastStepHaltingNumber()` is a count, not queue length. Detect creeping queues and spillback reaching upstream junctions.

### Initial timing targets, subject to profiling

| Operation | Target |
| --- | --- |
| Simulation step | 0.1 seconds |
| Safety supervision | Each step |
| State aggregation | 1 second |
| Corridor replanning | 2 seconds and significant events |
| Route reconsideration | 10 seconds and incident triggers |
| Planning horizon | 120 seconds |
| Detailed planning | Next 4-6 junctions per active ambulance, informed by downstream dependencies |

Freeze simulation step for the primary comparison. Any change in fidelity is a separately identified configuration with validation, not an undisclosed throughput shortcut.

## 7. Analytical scheduling and safety

### Prediction

Estimate ETA along remaining route geometry, including queue and signal delays. Use arrival windows, not exact guarantees; stationary vehicles require a queue/travel model rather than division by near-zero speed.

An initial queue service estimate is startup lost time plus vehicles ahead multiplied by measured saturation headway. Startup lost time and per-vehicle discharge headway are distinct. LWR wave speed `w = (q2-q1)/(k2-k1)` can inform queue-boundary propagation when units are consistent; wave arrival at the queue tail is not complete queue discharge. Calibrate predictions against observed outcomes and avoid double-counting travel and discharge effects.

### Downstream dependencies

Identify the blocked receiving path, find a feasible downstream discharge opportunity, prepare it, observe discharge, then release upstream traffic. A requested/accepted downstream green is not confirmed available capacity. Include the platoon admitted ahead of the ambulance and other inflows competing for space. Detect cyclic dependencies and infeasible corridors; use bounded fallback or route reconsideration rather than endlessly propagating requests.

### Rolling-horizon control

Evaluate bounded candidate service windows against predicted emergency delay, ordinary traffic delay, spillback, excessive waiting, and plan churn. Safety and clearance are hard constraints. Execute the immediate legal action, observe, and replan. Describe this as a rolling-horizon heuristic unless a formal optimisation implementation supports a stronger claim.

### Supervisor

Enforce approved movement combinations, minimum service, yellow/all-red, pedestrian clearance, bounded priority, passage confirmation, expiry, and legal recovery. `setRedYellowGreenState()` does not automatically enforce transitions. Even `setPhase()` requires selection of a validated successor. Use explicit phase graphs and confirmed state.

At a planned trigger, account for remaining minimum green and pedestrian obligations as well as yellow/red and uncertainty. Distinguish an already-green movement from a transition request. Do not promise exact queue flushing at the ambulance's arrival.

Monitor ordinary-traffic waiting targets; physical blockage can make them infeasible. Stale observations stop new speculative intervention. A crashed worker is a failed run, not successful fallback.

### Multiple ambulances and routing

Combine compatible requests and sequence conflicting ones deterministically using configured priority, approach timing, and waiting age. Honour committed transitions. Priority classes are scenario inputs, not inferred medical diagnoses.

Track independent request IDs and route versions. One ambulance's passage must not cancel another's service. Reconsider up to three feasible routes with hysteresis, lane reachability checks, and cancellation of obsolete future requests.

Primary coordination experiment: identical fixed ambulance routes across controllers. Dynamic routing: separately labelled experiment, with routing policies documented and coordination-only results preserved.

## 8. Genuine AI component

Use locally trained scikit-learn histogram gradient-boosted trees for:

1. Arrival-time correction relative to the analytical predictor, with quantile estimates assessed on validation data.
2. Downstream queue prediction over selected planning horizons, conditional on current observations and proposed signal service.

Training features may include route distance, recent speed history, queue state, vehicles ahead, phase/elapsed time, recent inflow/discharge, receiving conditions, geometry, and proposed effective green. Never use future measured outcomes or hidden incident schedules as features.

Collect labels from varied legal control actions and traffic conditions. Treat censored outcomes explicitly. Split entire episodes and selected scenario/route groups, not neighbouring snapshots. Compare MAE and quantile coverage with analytical forecasts; evaluate closed-loop effects after integration. Do not assume better prediction implies better journeys.

Freeze preprocessing, feature schema, model parameters, seed, training manifest, and model hash before final evaluation. Expose invalid/out-of-support inputs and fall back to analytical prediction. Keep the scheduler and supervisor the same for analytical-versus-AI comparison where possible.

Defensible pitch: ZELVO learns how congestion evolves along an ambulance route, then uses those forecasts to coordinate signals through an explicit safety-constrained controller. No LLM, reinforcement learning, guaranteed benefit, or GPU claim is implied.

## 9. Real-controller integration boundary

Define an adapter supporting capabilities, confirmed status, service submission, cancellation, request status, and health/freshness. Requests carry request ID, junction/movement, journey/route version, arrival window, priority, and expiry.

Lifecycle: requested, accepted, active, completed; rejected, expired, cancelled, or unknown. A communications timeout does not establish whether a command was accepted. Reconcile ambiguous outcomes before unsafe retries; respect documented target idempotency semantics.

The emulator must test delay, rejection, unsupported requests, duplicates, restart, disconnection after acceptance, expiry, cancellation, and stale state. A future NTCIP/vendor driver requires actual interface documentation, phase mappings, network access, permissions, and target testing. No generic API key or asserted universal compatibility.

## 10. Measurements and evidence

### Journey and junction definitions

- Journey time: destination arrival minus actual departure.
- Departure delay: actual departure minus scheduled departure.
- Scheduled-start-to-arrival: retain alongside journey time so insertion delays remain visible.
- Stops: define speed threshold, duration, and rearming hysteresis before benchmarking.
- Junction detection: common approach-zone event observed for every controller, including baselines.
- Signal response: first qualifying route green at/after detection minus detection time; zero if qualifying green is already present.
- Passage wait: confirmed junction crossing minus detection time. Green is not equivalent to useful passage.
- A missing green/crossing/arrival has an explicit missing/censored status, never a fabricated zero.
- Dispatch and mobilisation are not simulated; do not describe these results as full dispatch-to-hospital response times.

### Required record groups

| Group | Required data |
| --- | --- |
| Identity | Run/scenario IDs, seed, controller/model version, schema version, input hashes |
| Journeys | Scheduled/actual departure, arrival, completion, waiting/stopped time, stops, route history |
| Junctions | Detection, qualifying green, crossing, response and passage wait, activation/release, recovery |
| Network | Delay distribution, throughput, blocked insertion, unfinished trips, pedestrian waiting |
| Congestion | Queue maxima, spillback duration, blocked-junction duration |
| Safety | Illegal transitions, clearance/conflict violations, collisions, teleports |
| Reliability | Stale data, fallback, errors, timeouts, failure and completion status |
| Compute | Wall duration, simulated duration, planning latency distribution, throughput |
| Decisions | Requests, reasons, acceptance/rejection, arbitration, confirmed outcomes |

Record ordinary-traffic accumulated delay for unfinished as well as completed trips; do not rely only on arrived vehicles. A common evaluation horizon covers recovery. Future aggregate averages cannot omit stalled journeys without reporting their exclusion and completion rate.

Time saved is the paired difference between baseline and ZELVO journey time. Percentage reduction uses the matched baseline as denominator. Report median/tail performance, paired variation and interval estimates grouped by scenario instance, regressions, and failures. Multiple vehicles within one run are not independent simulation replications.

Training observations, short training rollouts, complete evaluation episodes, matched scenario instances, and prediction calls are separately counted.

## 11. Batch runner and 20,000-execution campaign

Manifest: 10 families x 4 demand levels x 5 OD configurations x 20 seeds x 5 controllers = 20,000 scheduled executions. All five controllers share intended inputs within each of 4,000 matched instances.

- Training runs are additional and use disjoint evaluation inputs.
- Freeze the manifest/model/config before the final campaign.
- Benchmark headless TraCI/libsumo compatibility and throughput first.
- Begin at two workers; increase only when measured aggregate throughput and memory allow. Current observed machine: Ryzen 7 3700U, eight logical CPUs, about 14 GiB usable RAM, around 2 GiB free when inspected. These observations can change.
- One independent simulation per process; cap numerical-library threading to avoid oversubscription.
- Avoid frontend telemetry and full per-step vehicle recording in the batch. Keep compact decision/event records, metrics, failures, and selected replay.
- Resume from completed per-run artifacts; use atomic completion records and unique output directories. Record attempts separately from logical run IDs.
- Preserve failed/timed-out runs and invalid matched sets. Do not quietly rerun until only successes remain.
- Save representative and problematic full recordings, not every graphical frame from every run.

Wall-clock feasibility is empirical. 20,000 30-minute runs represent 10,000 simulated hours. At one aggregate execution per second, 20,000 executions take about 5.6 hours; at 0.1/second, about 55.6 hours. Report actual measured throughput and actual completed count. Do not silently shorten episodes or swap simulators to achieve a count before submission.

## 12. Frontend: side-by-side live comparison

Left: ordinary actuated signals, no preemption. Right: ZELVO AI. Run two actual simulations from equivalent conditions. Each worker has independent traffic evolution after intervention.

Before Run Comparison, judges choose traffic intensity, disruption preset, and one/competing ambulances. Seed is optional advanced input; hospital/journey can be reviewed presets. Hide low-level technical parameters from the main flow.

Use identical geography, intended demand, departure schedules, incidents, pedestrians, vehicle settings, and seed. Fix the route in the main demo; label dynamic rerouting as a separate mode.

Synchronise panels by simulation time, not worker computation speed. Buffer the faster worker; apply playback speed equally. If one ambulance arrives, preserve its measured arrival while the other continues. Both simulations continue through the common evaluation/recovery horizon.

Display elapsed journey time, distance remaining, stopped time, stops, and junctions crossed. Reveal measured time saved after comparable journeys complete; live ETAs are labelled predictions. Show ordinary-traffic effects and actual outcomes, even if ZELVO loses.

### Rendering

- React owns controls and panels; Canvas owns vehicle rendering.
- Separate simulation tick, telemetry publication, and browser repaint rates.
- Use requestAnimationFrame timestamps and a bounded snapshot history.
- At normal speed, begin with approximately 150-250 ms presentation delay, tuned to measured jitter.
- Find snapshots bracketing displayed simulation time and interpolate positions. Follow lane/internal connection geometry where available so turning vehicles do not cut corners.
- Align vehicles, signals, incidents, and overlays to the same displayed time. Signals change discretely.
- Handle spawn, removal, teleport, pause, seek, speed change, reset, and reconnect explicitly.
- If the buffer is exhausted, hold supported state and indicate delay; do not indefinitely extrapolate through junctions.
- Messages contain run ID, sequence, simulation time, playback status/rate, updates/removals, and timestamped events. Resynchronise using a full snapshot after connection loss.
- Keep animation buffers out of per-frame React component state. Measure frame times on the full district; 60 fps is a target, not a guarantee.

## 13. Detailed implementation slices

Each slice ends with artifacts, verification, a report, and review before moving on. Tests are added for meaningful control, data-integrity, and failure behaviour. Do not expand into the frontend early.

### Slice 0: Runtime, structure, and contracts

Deliver: project-local Python environment if needed; compatible dependencies; SUMO discovery independent of the incorrect inherited SUMO_HOME; typed/validated scenario, observation, request, event, and result contracts; explicit units/clocks; a tiny headless fixture and smoke CLI; README commands; ignored generated artifacts.

Verify: runtime/tool discovery; invalid config diagnostics; unique output and valid result; an actual SUMO vehicle journey; meaningful tests for validation and failure handling. Record runtime versions and input hashes. This fixture is not the district demonstration.

Gate: one documented command runs the smoke simulation and produces measured evidence. No coordination, learning, API, or frontend required yet.

### Slice 1: OSM district and movement registry

Deliver: source extract, build configuration, corrections, attribution, compiled district, junction/movement registry, OD zones, mixed traffic, pedestrians, hospital routes.

Verify: route/lane reachability, junction groupings, phase mappings, detector suitability, crossing configuration, unexplained import/runtime warnings, baseline progression, measured runtime.

Gate: district runs in SUMO; geometry and configured behaviour are inspected, with synthetic/inferred properties identified.

### Slice 2: Experiment runner and metric recorder

Deliver: worker lifecycle, deterministic inputs, common detection zones, stop/journey/passage tracking, network and pedestrian metrics, congestion observations, events, incremental outputs, timeouts/errors, repeatable command line.

Verify: departure delay, unfinished journey, green-without-passage, a failed worker, repeatability, and independent reconstruction of metrics from events. Distinguish unavailable from zero.

Gate: meaningful ordinary-operation numbers can be obtained without animation.

### Slice 3: Safety supervisor and ordinary baselines

Deliver: validated phase graph, min service, yellow/red, pedestrian obligations, request expiry, confirmed passage/recovery, fixed-time and actuated controller modes, receiving-space contract.

Verify: rejected illegal transitions; elapsed clearance constraints; pedestrian protection; stale-request expiry; legal recovery; no bypass via arbitrary state-setting.

Gate: emergency logic can only request permitted service through the supervisor.

### Slice 4: Local emergency preemption

Deliver: next-junction detection, useful service requests, legal transition, passage confirmation, release/recovery, response metrics.

Verify: detection during target green/conflicting green/clearance; slowdown; lost tracking; release without stuck priority; common-input comparison with no preemption.

Gate: first complete normal-versus-preemption comparison with recorded measurements.

### Slice 5: Analytical ZELVO

Deliver: arrival windows, measured discharge estimates, receiving-space forecast, downstream dependency graph, bounded scheduling, replanning, explainable decisions, recovery and ordinary-service monitoring.

Verify: cascading queue; slow-creeping queue; accepted downstream request without actual discharge; blocked sink; inaccurate ETA; wide junction; district-wide operation.

Gate: downstream conditions change upstream decisions and infeasible corridors are explicit.

### Slice 6: Learned prediction

Deliver: diverse legal-action training generation, feature/label extraction, grouped splits, trained ETA correction and queue predictors, evaluation metrics, fallback, frozen model artifacts.

Verify: no future leakage; no within-episode split leakage; censored targets treated explicitly; inference latency; invalid inputs; forecasts actually change scheduling; analytical-versus-AI closed-loop comparison.

Gate: genuine local ML is integrated, its measured contribution is available, and safety remains independent.

### Slice 7: Multiple emergencies, routes, and integration emulator

Deliver: compatible/conflicting arbitration, route-version invalidation, feasible alternate routes with hysteresis, controller contract, emulator fault injection.

Verify: following ambulances, perpendicular approaches, disappearing vehicle, route change, duplicate/ambiguous request, disconnect/restart, stale status, cancellation, expiry.

Gate: no premature release for remaining emergencies; no request acknowledgement mistaken for physical service.

### Slice 8: Freeze and profile the benchmark

Deliver: final scenario manifest, frozen parameters/model, pilot batches, throughput/memory profile, worker selection, resumable output audit, parity between batch and interactive controller behaviour.

Verify: all required metrics; matched inputs; persistent failures; no duplicate completion; grouped comparisons; faithful runtime projections; versioned fidelity settings.

Gate: a fair frozen experiment and measured execution budget exist before a large campaign starts.

### Slice 9: Local evaluation campaign

Deliver: execute the 20,000-job manifest to the feasible completion count; progress and failure records; paired summaries, distributions, uncertainty, prediction quality, ablations, selected replay, exact counters.

Verify: audit input/model hashes, inspect random and worst outcomes, preserve incomplete/failed results, label unmatched comparisons, and keep changed-version runs separate.

Gate: evidence is reproducible and claims match actually completed runs. The runner supports resumption if full execution extends beyond submission.

### Slice 10: Frontend last

Deliver: judge controls, two live workers, shared presentation time, district geometry, smooth buffered playback, metrics, junction inspection, explanations, evidence and replay views.

Verify: matched startup, unequal worker speeds, turns, signal/event alignment, pauses/speed changes, spawn/removal/teleport, jitter/disconnect, actual result parity, district rendering performance.

Gate: a complete real simulation comparison rather than a scripted animation. Slice 9 may continue in the background only using frozen versions and within measured local resource limits.

### Slice 11: Submission and reproduction

Deliver: verified startup instructions, dependency/version record, reproducible selected experiment, results tables/charts, demo recording, model description and split, exact counts/durations, assumptions, limitations, integration status.

Verify: clean documented run, selected result reconstruction, no unsupported improvement or lives-saved claim, clear OSM attribution, no paid dependency.

Gate: a reviewer can reproduce the demo and trace headline numbers to evidence.

## 14. Execution policy and timing

The original submission window is approximately 10-12 hours. Expanded district, ML, and 20,000 executions increase work and compute requirements. Treat time allocations as planning targets, not guarantees. Prioritise a working end-to-end engine and meaningful evidence before graphical polish. Profile early and run the frozen batch independently of frontend work when resources permit.

At each checkpoint report what changed, how it was verified, material limitations, and exact reproduction commands. The latest user authorization supersedes the earlier permission gate: continue through Slices 1–7, maintain progress.md, and report evidence at each checkpoint.

Current checkpoint: Slices 1–7 authorized for continuous implementation; see progress.md for current evidence. Frontend and the frozen evaluation campaign are subsequent slices.

## 15. References

- https://sumo.dlr.de/docs/Networks/Import/OpenStreetMap.html
- https://sumo.dlr.de/docs/netconvert.html
- https://sumo.dlr.de/docs/Simulation/Traffic_Lights.html
- https://sumo.dlr.de/docs/TraCI/Traffic_Lights_Value_Retrieval.html
- https://sumo.dlr.de/docs/TraCI/Lane_Value_Retrieval.html
- https://sumo.dlr.de/docs/TraCI/Change_Traffic_Lights_State.html
- https://sumo.dlr.de/docs/Libsumo.html
- https://sumo.dlr.de/docs/Simulation/Randomness.html
- https://sumo.dlr.de/docs/Simulation/SaveAndLoad.html
- https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html
- https://ops.fhwa.dot.gov/publications/fhwahop08024/chapter3.htm
- https://www.openstreetmap.org/copyright
- https://download.geofabrik.de/
- https://www.ntcip.org/signal-control-and-prioritization/
- https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame
- https://react.dev/reference/react/useRef

## 16. Checkpoint ledger

### Current frontend authorization — 10 October 2026

The user explicitly authorized the landing page and live side-by-side comparison, superseding all earlier UI exclusions below. The large evaluation and proposed fast simulator remain paused/deferred. Implemented React/TypeScript/Vite UI, bundled variable fonts, local OSM/Canvas maps, scenario controls and real paired SUMO workers through FastAPI/WebSockets. The UI shows actual measured travel and stopped-on-red time, plus downloadable receipts. Presentation uses buffered interpolation and a shared clock, never a prescribed ambulance trajectory. The landing page uses the verified **46.9%** curated reduction, not unsupported 48.6%. See current `progress.md`, `ENGINE.md`, and `frontend/DESIGN.md` for verification, protocol and design decisions. Historical checkpoints below retain their original authorization and evidence scope.

### Slice 0 — completed, 10 October 2026

Implemented project-local Python 3.12.12, a locked dependency environment, SUMO discovery with compatible 1.26.0 interfaces, validated configuration/control/event/result contracts, a headless smoke CLI, evidence persistence, and Windows setup helpers. The inherited incorrect SUMO_HOME is ignored during discovery and corrected only for child launches; the parent environment is restored. Setup suppresses Python registry registration.

Verification:

- `python -m pytest -q`: **20 passed** (45.88 seconds in the recorded verification run).
- Re-running the bootstrap: success; Python already installed and fourteen packages audited.
- `python -m zelvo doctor`: Python 3.12.12; SUMO/netconvert/TraCI/sumolib all 1.26.0; Pydantic 2.14.0. Libsumo is not yet installed or benchmarked.
- CLI output parses as JSON. Smoke run `smoke-4f2dd2f1584b45278a8f4dc5537dbc4b`: completed; ambulance departure 0.0 s, arrival 32.4 s, journey 32.4 s; all fixture traffic cleared by 40.8 simulated seconds; wall duration 6.875 s; zero observed collisions/teleports.
- Tests include invalid requests, non-finite inputs, unknown versus empty observations, completed versus censored journeys, input path resolution, parent environment restoration, a real repeated SUMO journey, unfinished background traffic, timeout evidence, and an actual network-build failure.

Evidence: [recorded smoke result](results/smoke/smoke-4f2dd2f1584b45278a8f4dc5537dbc4b/result.json). Generated output stays local and is excluded from source control.

Limitations: this is runtime verification on a tiny fixture, not a district benchmark, AI demonstration, improvement result, signal-safety audit, or full metric recorder. Later-slice metrics are explicitly unavailable. No real signal controller is connected. No training or 20,000-run evaluation has started.

### Engine checkpoint — Slices 1–7, 10 October 2026

The latest authorization advances continuously through Slice 7. The following implementation supersedes the historical Slice-0-only status above; [progress.md](progress.md) and [ENGINE.md](ENGINE.md) contain current evidence and reproduction commands.

| Slice | Delivered implementation |
|---|---|
| 1 | Frozen Bengaluru OSM source, reproducible left-hand network compilation, exact lane/connection registry, topology refinement ledger, hospital-bound mixed demand and separate synthetic walking-demand generator |
| 2 | Fixed-horizon SUMO runner, socket/embedded backends, immutable input copies, raw events/tripinfo, journey/response/stop/ordinary/pedestrian/congestion metrics, explicit failure and censoring |
| 3 | Independently validated signal programs, legal phase progression, minimum service, pedestrian protection, receiving-space recheck, observed corridor occupancy guard and priority/recovery budgets |
| 4 | Nearest-intersection preemption baseline using the same supervisor; strictly matched baseline comparison command |
| 5 | Six-intersection rolling observations, slow-creeping queue proxy, observed discharge rates, downstream-first capacity dependencies, arrival windows, pending blocked requests and stale-data fallback |
| 6 | Genuine CPU-trained gradient boosting for ETA residuals/quantiles and receiving queues, whole-seed partitions, model/data hashes, support fallback, recorded inference and closed-loop comparison |
| 7 | Shared/conflicting emergency arbitration, individual passage release, route version invalidation, optional live rerouting with hysteresis, lost-ACK/stale/disconnected/restart authority emulator |

The main district has **43 controllers and 226 controlled movements**. The **282-controller** stress network is retained separately; successful loading does not establish complete stress-network validation. Both are asymmetric OSM-derived networks. Inferred timing, uncalibrated traffic demand and unresolved import warnings remain explicit.

Implementation choices that refine the original proposal:

- Signal control changes eligible phase duration and preserves the installed program's legal succession. It does not directly force arbitrary red/yellow/green masks.
- Queue extent uses slow-vehicle positions, while receiving capacity uses space at the actual link entrance. Neither halted counts nor total vacant lane length alone establishes usable receiving space.
- Queue clearing uses startup lost time and bounded observed discharge headway. This prototype does not claim field-calibrated LWR shockwave parameters or an exact just-in-time guarantee.
- The actuated comparison baseline makes no priority requests but shares the corridor occupancy guard used by all variants. It is not unmodified SUMO actuation.
- A blocked following ambulance remains a pending owner while signal changes are withheld. Its request is not mistaken for confirmed physical service or early completion.
- Training uses observational simulator data. Whole-seed holdouts prevent within-seed leakage across policies, but do not prove generalization to new routes or cities, causal action effects, or field travel-time improvements.
- Walking demand can be generated and has been executed, but it is synthetic. Full intersection-box coverage, calibrated contiguous queues and physical-controller measurements remain unavailable.

Verification: **61 tests passed** in the full recorded suite, followed by a separate passing slow-creeping/receiving-capacity regression check. Actual following and conflicting emergencies, stale observations, a temporary blocked lane and socket/embedded parity are included. The separate hospital walking pilot completed with all 60 people observed and zero collision or phase-audit errors.

Clean same-input district runs exist for actuated, local preemption, analytical ZELVO and learned ZELVO. The fixed-time run completed both ambulance journeys but retained ordinary traffic at the horizon. Final learned-model evidence and the measured AI contribution are recorded in [reports/checkpoint7.json](reports/checkpoint7.json), [model manifest](models/predictor.json) and matched comparison reports. Learned forecasts changed requests on seven replayed planning ticks. In this one example, the learned controller's ambulance arrivals were essentially equal to the analytical controller's; no additional ML travel-time benefit is claimed.

Frontend and submission packaging remain subsequent work. Development/training runs are never counted as the evaluation campaign. The frozen runner and evidence workflow are described in the current Slice 8–9 addendum below. No public traffic signals are connected.

### Current authorization and selected demo

Latest demo requirement supersedes the earlier duration target: **45–55% shorter complete ambulance journey and very little stopped waiting**, with a 2 s operational wait threshold; a 30-minute baseline is optional. Current selected preset achieves **46.8793% savings (144.2 → 76.6 s)** and **58.7 → 0 s stopped on red**, reproduced by an independent pair. This is a tuned three-junction corridor within the 43-controller district, not a claim about average city performance. Exact inputs, acceptance checks, model use, prior candidates and ordinary-traffic impacts are recorded in `reports/demo-target.md` and `scenarios/demo-selection.json`. UI remains untouched. Campaign execution status is recorded separately in `progress.md` and the campaign ledger.

Earlier checkpoint decisions below remain as historical context:

Implementation through Slice 9 is authorized, with no UI changes. Slice 8 is in progress; Slice 9's frozen campaign is pending. Current work corrects the ordinary baseline to issue no ZELVO signal holds, calculates actual legal phase-preparation lead, and separates preparation timeout from green-service budget. Historical checkpoint evidence remains unchanged.

The selected curated three-junction corridor achieves **28.5 s stopped on red under ordinary actuation versus zero with learned ZELVO**, with **34.1 s journey savings (22.2%)**. Independent replay reproduced the result. Demand interventions are identical in both runs; unsuccessful candidates are retained. See `reports/demo-corridor.md` for exact input configuration, model activity, tradeoffs and reproduction.

Longer-route evaluation should target realistic hospital-bound journeys with more controlled intersections and roughly 20-minute measured baseline travel time. Geometry and demand rules must be declared before treatment outcomes; avoid artificial loops or lights. Record per-junction delays and complete-trip savings separately. Bigger-map import warnings and unsupported short serial receiving links require validation before interpreting those runs. A longer journey does not by itself guarantee greater percentage savings.


### Current Slice 8–9 evaluation implementation

The primary count is now exactly **10,000 scenarios × two policies = 20,000 executions**, split into 10,000 ordinary actuated and 10,000 learned ZELVO runs. Freeze 50 development-disjoint seeds, four demand levels, five hospital OD routes and ten scenario families before execution. Use 100 ms physics and a 900 s horizon on the actual 43-controller OSM district. Compare identical inputs; retain failures, incomplete journeys and regressions. The selected tuned demo remains separate.

Slice 8 delivers actual low/high-load profiling, shared input storage, lossless verified raw archives and resource-limited isolated workers. Slice 9 delivers immutable source/model/input manifests, a durable resumable SQLite ledger, execution receipts with UTC timestamps and real wall/simulated time, paired means and seed-cluster uncertainty, stratified ordinary-traffic/safety/model metrics, a twenty-execution timing sample and raw tripinfo reconciliation. Separate headless CLI replays and five-policy pilot ablations stay outside the 20,000-run count. See ENGINE.md for commands and evidence definitions.

The 45–55% target is an acceptance check on measured reduction in mean journey time. It cannot be guaranteed in advance across the broader population. Report mean seconds saved, reduction in the means, mean individual percentage separately, and the denominator of complete pairs alongside all censoring. Infrastructure completion does not mean 20,000 executions have finished; live progress, resource projections and measured outcomes are kept in the campaign files. UI remains excluded.
