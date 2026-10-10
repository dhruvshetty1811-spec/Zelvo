"""Freeze one district scenario for backend validation, outside evaluation counts."""
import argparse
from pathlib import Path
import shutil

from zelvo.campaign import connect, freeze, get_job, verify
from zelvo.campaign_io import save
from zelvo.config import load_scenario
from zelvo.simulation.smoke import sha256


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path('results/evaluation-v1'))
    parser.add_argument('--output',type=Path,default=Path('results/backend-checkpoint-v2'))
    args=parser.parse_args()
    header=verify(args.source)
    with connect(args.source) as database:
        row=database.execute("SELECT * FROM jobs WHERE seed=? AND demand=? AND od=0 AND family='standard_one' LIMIT 1",
            (header['seeds'][0],min(header['levels']))).fetchone()
        scenario=get_job(args.source,row['offset'])
    original=load_scenario(args.source/scenario['config'])
    root=args.output.resolve()
    if root.exists():raise ValueError('Use a new checkpoint directory')
    inputs=root/'inputs';inputs.mkdir(parents=True)
    assets={}
    def copy(path):
        target=inputs/path.name
        shutil.copyfile(path,target)
        assets[target.relative_to(root).as_posix()]=sha256(target)
        return str(target)
    config=original.model_dump(mode='json')
    config['network_file']=copy(original.network_file)
    config['route_files']=[copy(path) for path in original.route_files]
    target=inputs/'scenario.json';save(target,config)
    assets[target.relative_to(root).as_posix()]=sha256(target)
    selected={key:scenario[key] for key in ('scenario_id','seed','demand','od','family')}
    selected['config']=target.relative_to(root).as_posix()
    frozen=freeze(root,None,model=args.source/'models/predictor.joblib',seeds=[scenario['seed']],
        levels=[scenario['demand']],horizon=original.horizon_s,scenarios=[selected],assets=assets)
    print({'jobs':frozen['jobs'],'engine_sha256':frozen['engine_source_sha256'],'root':str(root)})


if __name__=='__main__':main()
