import importlib.util
from pathlib import Path


def test_reverse_route_distances_are_shortest_connected_and_do_not_loop():
    spec=importlib.util.spec_from_file_location('corridor_inventory',Path('scripts/inventory-long-corridors.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    costs,next_edge=module.distances('hospital',{'hospital':{'direct','detour'},
        'direct':{'origin'},'detour':{'origin','cycle'},'cycle':{'detour'}},
        {'hospital':10,'direct':100,'detour':200,'origin':50,'cycle':30})
    assert costs['origin']==160
    assert next_edge['origin']=='direct'
    route=['cycle']
    while route[-1]!='hospital':route.append(next_edge[route[-1]])
    assert len(route)==len(set(route))
    assert route==['cycle','detour','hospital']
