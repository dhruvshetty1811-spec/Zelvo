# Bengaluru hospital district

Road data © OpenStreetMap contributors, [ODbL 1.0](https://www.openstreetmap.org/copyright).

This is a bounded district derived from the original, saved Bengaluru OSM extract. Bounding box: west 77.568, south 12.957, east 77.587, north 12.976. The source spans a larger area; full-city assets remain in `../bengaluru`.

```powershell
.\.venv\Scripts\python.exe -m zelvo district --directory scenarios/bengaluru-hospital --source scenarios/bengaluru/district.osm.xml --bbox 77.568 12.957 77.587 12.976
.\.venv\Scripts\python.exe -m zelvo scenario --directory scenarios/bengaluru-hospital --seed 42 --demand 300 --emergencies 2 --horizon 700
```

Compilation currently yields 43 controllers, 226 controlled movements, 6,543 external edges and 22,653 lanes, including pedestrian roads. Actual generated mixed traffic and exact controlled movements are recorded in each scenario's `.metadata.json` file. `hospital-access.json` is a convenience copy for the most recently generated scenario.

Bus demand uses main-road paths. Where a requested bus path cannot be found, a valid car trip preserves the requested total; actual type counts remain explicit. Signal inference, junction geometry, road access, baseline timings and traffic demand are modelling assumptions. No calibrated pedestrian demand or field-verified signal plans are claimed. All conversion warnings and narrow repairs are retained in the build artifacts.
