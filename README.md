# ZELVO

Predictive emergency traffic-signal coordination. See [IMPLEMENTATION.md](IMPLEMENTATION.md) for the complete agreed plan, evidence requirements, AI design, and slice gates.

## Current checkpoint: engine and live web demo

The backend, evaluation infrastructure, landing page, and local live comparison are implemented. The UI runs two independent SUMO workers on identical demand and draws their actual vehicle positions on OSM geometry. [progress.md](progress.md) records current verification and limitations; [checkpoint results](reports/checkpoint7.md) retain earlier measured outcomes.

See [ENGINE.md](ENGINE.md) for district runs, training, comparisons, metrics and integration commands. The hospital district contains 43 controllers; the rebuilt stress network contains 282. The local model was trained from 9,027 measured observations across eight development seeds. The large evaluation remains paused; the landing page's **46.9%** result is one curated, reproduced comparison, not a population estimate.

### Open the web demo

After Windows setup and dependency sync:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/uv.ps1 sync
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-web.ps1
```

Open **http://127.0.0.1:8000**. The helper builds the React/TypeScript site and serves it with the API. On later starts, use `scripts/start-web.ps1 -NoBuild` to reuse the built UI. Keep the terminal running; Ctrl+C stops the server and its owned simulations. Fonts and vector roads are local; no map subscription, LLM API, cloud account, or paid hosting is required.

The default **curated rush-hour preset** runs a 2.44 km journey through 10 signal controllers: **474.7 s without ZELVO / 245.5 s with ZELVO (48.28% saved)**. It uses real OSM roads, a disclosed synthetic peak timing/demand profile, and a simulated hospital destination. Choose light/moderate/heavy traffic (280/560/1,120 ordinary vehicles), random seed, dispatch time, and optional sensor delay. The 6.15 km / 13-controller exploration route and original 913 m / 3-controller reference are also selectable. This preset was selected during development to meet the 45-55% demo target; it is not a general expected improvement. See [curated verification](reports/curated-demo-verification.json) and [selection history](reports/curated-development-index.json). Other settings generate fresh matched inputs and can produce different or worse results. Playback speed, pause, and replay affect presentation only. Stop cancels the actual workers; receipts and partial measurements remain under `results/live/<session-id>/`, separate from campaign counts.

For frontend development, run `npm.cmd ci` and `npm.cmd run dev` from `frontend`. Vite serves port 5173 and proxies `/api` and its WebSocket to the backend on 8000. Node 24 is required by the native TypeScript config loader. `npm.cmd run build` checks TypeScript and builds the site. `npm.cmd run test:e2e` uses installed Microsoft Edge through Playwright against the built site on port 8000; the live browser test executes actual SUMO episodes.

### Windows setup

Prerequisites: installed SUMO **1.26.0** (`sumo` and `netconvert`) and Node.js **24.12+** for the bootstrap downloader. Node is already present on the development machine. Setup uses a pinned uv download with checksum verification, Python **3.12.12** inside `.runtime`, and a project `.venv`. It does not register Python globally or change system PATH. Download access is required once.

From the repository root in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
.\.venv\Scripts\python.exe -m zelvo doctor
.\.venv\Scripts\python.exe -m zelvo smoke
.\.venv\Scripts\python.exe -m pytest -q
```

The execution-policy flag applies only to that process, not the machine policy. `uv.lock` records resolved dependency versions; subsequent setup uses the lock. For later dependency operations use `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/uv.ps1 <arguments>` to retain workspace-local download/cache paths. On a machine with a compatible Python/uv environment, the standard project dependencies can also be installed without the Windows bootstrap helper.

### Runtime discovery

`doctor` searches PATH and valid installation directories. An inherited `SUMO_HOME` naming an installer rather than a directory is ignored with a diagnostic. Explicit overrides are `ZELVO_SUMO_BINARY` and `ZELVO_NETCONVERT_BINARY`. Binary and TraCI/sumolib versions must match. Libsumo availability is reported; batch performance is not established in Slice 0.

### Smoke evidence

Each invocation writes a unique directory under `results/smoke/` containing:

- `config.json`: effective scenario and input paths.
- `result.json`: schema-validated status, versions, input hashes, actual departure/arrival/journey times, error information, and explicitly unavailable later-slice metrics.
- `events.jsonl`: ordered start, departure, arrival, error, and completion events.
- `tripinfo.xml`: raw SUMO measurements, including unfinished trips.
- Generated network and build/process/simulator logs.

Non-success outcomes return a nonzero exit code. Output directories are isolated; repeats are not overwritten. The smoke executes ordinary actuated signals, obeys red lights, and disables automatic teleport recovery. It does not report placeholder zero improvements or unimplemented safety checks as passing.

### Tests

The suite includes contract and configuration checks, a real SUMO journey, repeatability, a censored journey, timeout reporting, and preservation of evidence after a real network-build failure. Integration tests require the matching installed simulator. To run validation tests without SUMO: `python -m pytest -q -m "not integration"`.

### Cost and scope

No paid service is required. Saved OSM assets include attribution and licence notices. Smoke evidence is neither an AI result nor an emergency-preemption improvement claim. No public traffic signals are connected.

### Evaluation campaign

The evaluation consists of **10,000 matched scenarios, each run without and with ZELVO: 20,000 executions total**. It uses the 43-controller Bengaluru district, frozen inputs/model/source, a resumable execution ledger and real timing receipts. The 45–55% savings target is checked against measured results. The separately tuned demo achieved 46.9%; broader campaign performance is not established by that demo.

See [ENGINE.md](ENGINE.md) for profiling, execution, stop/resume and evidence commands, and [progress.md](progress.md) for recorded verification. Campaign output includes paired means, completion/failure counts, seed-cluster uncertainty, every execution's timestamps and hashes, and a readable sample of twenty actual execution receipts. Training runs, separate policy ablations, and interactive demo runs are excluded from the 20,000 count.

Historical backend delivery: **86 tests passed**, corrected worker/cache storage, exact batch/CLI parity, and a fresh reproduced **46.9% curated demo**. The [backend bundle](dist/zelvo-backend-v2.zip) retains that frozen source, model, road/demand inputs, raw evidence and checksums; it predates the UI and is unchanged. The large/fast evaluation remains deferred, with four original campaign attempts. See `reports/backend-portability.json` for the bundle's extracted-path verification and scope.
# Expanded live comparison

The demo now defaults to a 6.15 km Bengaluru journey through 13 signalized controllers, with 300/600/1,200 ordinary vehicles. Choose **Original verified corridor** to replay the conditions behind the landing page's 46.9% reference result. Each live comparison runs two real SUMO workers with identical inputs; outcomes vary by route and settings.

The maps fill the viewport. Use **Follow ambulance**, **Entire route**, zoom buttons or drag to inspect each journey. The inset shows the whole corridor; playback supports up to 32x. Playback speed changes presentation only; simulation physics remains 0.1 seconds.

The expanded moderate/seed42 validation measured 917.2s without ZELVO and 887.6s with ZELVO (3.23% saved), with all 600 ordinary trips completed in both worlds and no recorded collisions, teleports or signal-audit errors. It is separate from the short reference result. See `reports/expanded-demo-verification.json`; timestamped raw evidence is under `results/expanded-validation/`. Signal import warnings and synthetic demand remain limitations.

Rebuild the larger scenario with `.venv\Scripts\python.exe scripts\prepare-expanded-demo.py` when no simulations are active. The source district and geometry inventory must already be present. Start the built application with `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-web.ps1`.



### Separate driver app preview

Open **http://127.0.0.1:8000/driver.html** after the normal web startup, or **http://127.0.0.1:8037/driver.html** on the current preview server. The driver app is a separate Vite entry with isolated styles, presented inside an iPhone outline on a white canvas. It supports hospital search, custom destination names, route preview, start, pause/resume, route overview, end-trip confirmation and arrival. Demo speed controls let you try a full trip quickly.

This is the user-authorized interactive prototype: location, navigation, ETA and signal status are simulated, and every destination shares an illustrative local OSM route. It does not start SUMO or send real signal requests. It needs no backend API, geolocation permission, geocoder, paid service or new dependencies. For development, open `http://127.0.0.1:5173/driver.html`; the same `npm.cmd run build` builds both app entries. Browser verification: `npm.cmd run test:e2e -- driver.spec.ts`.
