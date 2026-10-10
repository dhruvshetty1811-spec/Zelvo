"""Local supervised prediction with whole-seed splits and bounded fallback."""
from pathlib import Path
import json
import math
import time
import hashlib
import os
os.environ.setdefault('OMP_NUM_THREADS','1')

from zelvo.planning import FEATURES, analytical_eta


def train(input_files: list[Path], output: Path) -> dict:
    import numpy as np
    import joblib
    import sklearn
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.metrics import mean_absolute_error
    rows = []
    excluded_unsafe=0
    excluded_censored=0
    source_hashes = {}
    for source in sorted(input_files):
        if any((parent/'RETIRED.md').exists() for parent in source.parents):
            raise ValueError('Retired development data cannot train a model: '+str(source))
        source_hashes[str(source.resolve())] = hashlib.sha256(source.read_bytes()).hexdigest()
        for line in source.read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row.get('collision_records',0)>0 or row.get('safety_audit_errors',0) or row.get('episode_status','completed') not in ('completed','incomplete'):
                excluded_unsafe+=1
                continue
            if row['eta_residual'] is not None and row['queue_10s'] is not None and not row['censored']:
                if all(math.isfinite(v) for v in row['features']): rows.append(row)
            else:excluded_censored+=1
    if len({r['seed'] for r in rows})<6 or len(rows)<60:
        raise ValueError('Need at least six independent seeds and 60 uncensored observations')
    engine_hashes={r['engine_hash'] for r in rows if r.get('engine_hash')}
    if len(engine_hashes)>1:
        raise ValueError('Training data mixes engine versions; collect a frozen development dataset')
    x = np.asarray([r['features'] for r in rows],dtype=float)
    y_eta = np.asarray([r['eta_residual'] for r in rows])
    y_queue = np.asarray([r['queue_10s'] for r in rows])
    groups = np.asarray([r['seed'] for r in rows])
    trainval,test = next(GroupShuffleSplit(n_splits=1,test_size=.2,random_state=42).split(x,groups=groups))
    a,b = next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=43).split(x[trainval],groups=groups[trainval]))
    train_ids,validation = trainval[a],trainval[b]
    if any(set(groups[a])&set(groups[b]) for a,b in [(train_ids,validation),(train_ids,test),(validation,test)]):
        raise RuntimeError('Group leakage')
    params = dict(max_iter=100,max_leaf_nodes=15,min_samples_leaf=8,learning_rate=.08,
                  l2_regularization=1,early_stopping=False,random_state=42)
    started = time.perf_counter()
    models = {}
    for name,target,loss,quantile in [('eta',y_eta,'squared_error',None),
        ('eta_lower',y_eta,'quantile',.1),('eta_upper',y_eta,'quantile',.9),
        ('queue',y_queue,'poisson',None)]:
        model = HistGradientBoostingRegressor(**params,loss=loss,quantile=quantile)
        # Poisson requires positive total counts. Zero-only training data is not useful evidence.
        if name=='queue' and float(target[train_ids].sum())<=0:
            model = HistGradientBoostingRegressor(**params)
        model.fit(x[train_ids],target[train_ids])
        models[name] = model
    report = {'schema_version':'1.0','features':FEATURES,'sklearn_version':sklearn.__version__,
              'rows':len(rows),'groups':{},'metrics':{},'source_hashes':source_hashes,
              'training_wall_s':time.perf_counter()-started,
              'engine_hashes':sorted(engine_hashes),
              'excluded_unsafe_rows':excluded_unsafe,'excluded_censored_rows':excluded_censored,
              'action_definition':'current priority request/hold indicator; future policy remains observational',
              'limitations':['Observational policy data does not identify causal action effects',
                             'Bounds fallback checks feature ranges, not all distribution shifts',
                             'Seed holdout does not establish unseen-city or unseen-route generalization',
                             'Prediction improvement alone does not establish faster ambulance journeys']}
    for name,indices in [('train',train_ids),('validation',validation),('test',test)]:
        report['groups'][name] = sorted(set(int(s) for s in groups[indices]))
        pred = models['eta'].predict(x[indices])
        lower = models['eta_lower'].predict(x[indices])
        upper = models['eta_upper'].predict(x[indices])
        low,high = np.minimum(lower,upper),np.maximum(lower,upper)
        report['metrics'][name] = {'rows':len(indices),
            'eta_analytical_mae_s':float(np.mean(np.abs(y_eta[indices]))),
            'eta_learned_mae_s':float(mean_absolute_error(y_eta[indices],pred)),
            'queue_persistence_mae_vehicles':float(mean_absolute_error(y_queue[indices],x[indices,FEATURES.index('downstream_queue')])),
            'queue_learned_mae_vehicles':float(mean_absolute_error(y_queue[indices],models['queue'].predict(x[indices]))),
            'eta_interval_coverage':float(np.mean((y_eta[indices]>=low)&(y_eta[indices]<=high)))}
    bundle = {'schema_version':'1.0','features':FEATURES,'models':models,
              'minimum':x[train_ids].min(axis=0),'maximum':x[train_ids].max(axis=0),
              'categorical_values':{name:sorted(set(x[train_ids,FEATURES.index(name)].tolist())) for name in ('green','action_hold')},
              'report':report}
    output.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump(bundle,output)
    report['model_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


class Predictor:
    def __init__(self,path: Path):
        import joblib
        import sklearn
        manifest = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        if sklearn.__version__!=manifest['sklearn_version']:
            raise ValueError('Model scikit-learn version differs from the installed runtime')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['model_sha256']:
            raise ValueError('Model hash differs from frozen manifest')
        self.bundle = joblib.load(path)
        if tuple(self.bundle['features'])!=FEATURES:
            raise ValueError('Model feature schema mismatch')
        self.calls = self.fallbacks = 0
        self.last_interval = None

    def predict(self,observation):
        import numpy as np
        self.calls += 1
        values = np.asarray(observation.features())
        if any(getattr(observation,name) not in allowed for name,allowed in self.bundle['categorical_values'].items()):
            self.fallbacks += 1
            return None
        lower,upper = self.bundle['minimum'],self.bundle['maximum']
        tolerance = np.maximum(1,(upper-lower)*.1)
        if not np.all(np.isfinite(values)) or np.any(values<lower-tolerance) or np.any(values>upper+tolerance):
            self.fallbacks += 1
            return None
        models = self.bundle['models']
        baseline = analytical_eta(observation)
        eta = max(0,baseline+float(models['eta'].predict([values])[0]))
        queue = max(0,float(models['queue'].predict([values])[0]))
        limits = [max(0,baseline+float(models[name].predict([values])[0])) for name in ('eta_lower','eta_upper')]
        self.last_interval = sorted(limits)
        return eta,queue
