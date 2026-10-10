"""Sample raw execution archives and verify ambulance timing against SUMO tripinfo."""
import gzip
import hashlib
from pathlib import Path
import random
import xml.etree.ElementTree as ET
from zelvo.campaign_io import read,save


def audit(root):
    from zelvo.campaign import connect,verify
    root=Path(root).resolve();header=verify(root)
    with connect(root) as database:
        rows=[dict(r) for r in database.execute('SELECT * FROM attempts WHERE result IS NOT NULL ORDER BY started')]
    sample=random.Random(2026).sample(rows,min(20,len(rows)))
    paired=root/'paired-outcomes.json'
    if paired.exists():
        outcomes=[p for p in read(paired) if p['status']=='paired_complete']
        worst=sorted(outcomes,key=lambda p:p['without_s']-p['with_s'])[:5]
        ids={p['scenario_id'] for p in worst}
        with connect(root) as database:
            for row in database.execute('SELECT attempts.*,jobs.scenario_id FROM attempts JOIN jobs USING(job_id) WHERE result IS NOT NULL'):
                if row['scenario_id'] in ids and not any(s['attempt_id']==row['attempt_id'] for s in sample):sample.append(dict(row))
    checks=[]
    for row in sample:
        result=read(row['result']);errors=[]
        if result['input_hashes']['engine_source_sha256']!=header['engine_source_sha256']:errors.append('engine mismatch')
        for key,integrity in result.get('archive_integrity',{}).items():
            digest=hashlib.sha256()
            with gzip.open(result['artifacts'][key],'rb') as stream:
                while block:=stream.read(1024*1024):digest.update(block)
            if digest.hexdigest()!=integrity['uncompressed_sha256']:errors.append('archive '+key)
        tripfile=result['artifacts'].get('tripinfo')
        reconciled=0
        if tripfile and Path(tripfile).exists():
            opener=gzip.open if str(tripfile).endswith('.gz') else open
            with opener(tripfile,'rb') as stream:trips={t.get('id'):t for t in ET.parse(stream).getroot().findall('tripinfo')}
            for journey in result['journeys']:
                if not journey['completed']:continue
                trip=trips.get(journey['vehicle_id'])
                if trip is None or float(trip.get('arrival'))<0:errors.append('missing completed tripinfo')
                elif abs(float(trip.get('arrival'))-float(trip.get('depart'))-journey['journey_time_s'])>1e-6:
                    errors.append('journey duration mismatch')
                else:reconciled+=1
        elif any(j['completed'] for j in result['journeys']):errors.append('missing tripinfo')
        checks.append({'attempt_id':row['attempt_id'],'status':row['status'],'completed_journeys_reconciled':reconciled,'errors':errors})
    data={'sampled_attempts':len(checks),'selection':'Seed-2026 sample up to 20 plus five worst paired scenarios',
        'all_checks_passed':all(not check['errors'] for check in checks),'checks':checks}
    save(root/'raw-evidence-audit.json',data)
    return {'sampled_attempts':len(checks),'all_checks_passed':data['all_checks_passed']}
