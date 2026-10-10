# Bengaluru district

Road data © OpenStreetMap contributors, available under the [Open Database License](https://www.openstreetmap.org/copyright).

`source.json` records download URLs, the source hash, tile hashes and processing. `district.osm.xml` retains the downloaded road ways, their nodes and applicable turn restrictions. Original map API tiles are local download intermediates and excluded from source control.

Reproduction:

```powershell
node --use-system-ca scripts/fetch-osm.mjs
.\.venv\Scripts\python.exe scripts/merge-osm.py
.\.venv\Scripts\python.exe -m zelvo district
.\.venv\Scripts\python.exe -m zelvo scenario --seed 42 --demand 600 --emergencies 2
```

Compilation uses left-hand driving. Signal inference, junction joins, lane connections, speeds and pedestrian crossings remain modelling assumptions. `netconvert.log` preserves warnings, including ignored restrictions and ambiguous turns. `topology-refinements.json` records excluded oversized signal joins. These assets are suitable for engineering experiments after route/runtime validation, not validated deployment plans.

The destination is a road near Victoria Hospital. The simulator does not model hospital intake, dispatch operations or patient outcomes. Bus and motorcycle traffic are generated vehicles, not calibrated public-transport timetables or measured demand. Pedestrian demand must be supplied/calibrated separately; zero simulated pedestrians is not evidence of zero pedestrian impact.
