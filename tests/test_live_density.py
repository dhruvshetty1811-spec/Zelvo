"""Run fresh native workers at a non-preset percentage; no saved replay input."""
import asyncio

import pytest

from zelvo.live import DemoSettings, SessionManager


@pytest.mark.integration
def test_fresh_percentage_comparison_completes_with_measured_results(tmp_path,monkeypatch):
    monkeypatch.setenv('ZELVO_WORKER_MODE','sequential')
    async def compare():
        manager = SessionManager(tmp_path / 'live')
        try:
            session = manager.create(DemoSettings(corridor='reference', density_percent=37, seed=17))
            assert list(session.processes) == ['baseline']
            session.clients = 1
            await asyncio.wait_for(session.task, timeout=930)
            receipt = session.summary()
            assert receipt['status'] == 'complete', receipt['errors']
            assert receipt['execution_mode'] == 'sequential'
            assert receipt['inputs']['ordinary_vehicle_count'] == 111
            assert receipt['inputs']['settings']['density_percent'] == 37
            assert receipt['frames']['baseline'] > 0
            assert receipt['frames']['zelvo'] > 0
            for side in ('baseline', 'zelvo'):
                result = receipt['results'][side]
                journey = result['journeys'][0]
                assert journey['completed']
                assert journey['journey_time_s'] > 0
                assert journey['journey_time_s'] == pytest.approx(journey['arrival_s'] - journey['actual_departure_s'])
                assert receipt['inputs']['demand_sha256'] in result['input_hashes'].values()
                assert result['collision_events'] == 0
                assert result['teleport_events'] == 0
                assert result['metrics']['safety_audit_errors'] == 0
            b = receipt['results']['baseline']['journeys'][0]['journey_time_s']
            z = receipt['results']['zelvo']['journeys'][0]['journey_time_s']
            print(f'Fresh 37% comparison: without={b:.1f}s, with={z:.1f}s, reduction={100*(b-z)/b:.3f}%')
        finally:
            await manager.close()

    asyncio.run(compare())
