"""Small deterministic summaries; missing observations remain missing."""
import math


def distribution(values):
    ordered = sorted(float(v) for v in values if v is not None)
    if any(not math.isfinite(v) for v in ordered):
        raise ValueError('Non-finite measurement')
    if not ordered:
        return {'count': 0, 'mean': None, 'min': None, 'max': None,
                'p50': None, 'p90': None, 'p95': None, 'p99': None}
    def percentile(p):
        position = (len(ordered)-1)*p
        lo, hi = math.floor(position), math.ceil(position)
        return ordered[lo] + (ordered[hi]-ordered[lo])*(position-lo)
    return {'count': len(ordered), 'mean': sum(ordered)/len(ordered),
            'min': ordered[0], 'max': ordered[-1],
            **{name: percentile(p) for name,p in [('p50',.5),('p90',.9),('p95',.95),('p99',.99)]}}
