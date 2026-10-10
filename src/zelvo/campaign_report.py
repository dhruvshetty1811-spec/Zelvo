"""Matched campaign evidence with clustered uncertainty and explicit missing outcomes."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json
from pathlib import Path
import random
import statistics

from zelvo.campaign_io import read,save
from zelvo.evaluation import compare
from zelvo.metrics import distribution


def clustered_estimate(pairs,*,repetitions=2000):
    """Scenario-equal means, resampling entire seeds to retain within-seed dependence."""
    if not pairs:return {'matched_complete_scenarios':0,'mean_saved_s':None,'percent_reduction_in_mean':None,'cluster_bootstrap_95_percent':None}
    baseline=statistics.mean(p['without_s'] for p in pairs)
    treated=statistics.mean(p['with_s'] for p in pairs)
    groups=defaultdict(list)
    for pair in pairs:groups[pair['seed']].append(pair)
    summaries=[(sum(p['without_s'] for p in group),sum(p['with_s'] for p in group),len(group)) for group in groups.values()]
    intervals=[]
    if len(summaries)>=2:
        rng=random.Random(7919)
        for _ in range(repetitions):
            chosen=rng.choices(summaries,k=len(summaries))
            left=sum(p[0] for p in chosen);right=sum(p[1] for p in chosen)
            if left>0:intervals.append(100*(left-right)/left)
    interval=distribution(intervals)
    return {'matched_complete_scenarios':len(pairs),'seed_clusters':len(groups),
        'mean_without_s':baseline,'mean_with_s':treated,'mean_saved_s':baseline-treated,
        'percent_reduction_in_mean':100*(baseline-treated)/baseline if baseline else None,
        'mean_individual_percent_saved':statistics.mean(100*(p['without_s']-p['with_s'])/p['without_s'] for p in pairs),
        'saved_s_distribution':distribution(p['without_s']-p['with_s'] for p in pairs),
        'regressed_scenarios':sum(p['with_s']>p['without_s'] for p in pairs),
        'cluster_bootstrap_95_percent':None if not intervals else [interval['p50'] if len(intervals)==1 else percentile(intervals,.025),percentile(intervals,.975)],
        'uncertainty_note':'Entire-seed bootstrap, conditional on matched complete scenarios; small cluster counts are exploratory'}


def percentile(values,q):
    values=sorted(values);index=(len(values)-1)*q;low=int(index)
    return values[low]+(values[min(low+1,len(values)-1)]-values[low])*(index-low)


def iso(value):
    return None if value is None else datetime.fromtimestamp(value,timezone.utc).isoformat()


def report(root):
    from zelvo.campaign import connect,TERMINAL,verify
    root=Path(root).resolve();header=verify(root,all_assets=False)
    with connect(root) as database:
        jobs=[dict(row) for row in database.execute('SELECT * FROM jobs ORDER BY rowid')]
        attempts=[dict(row) for row in database.execute('SELECT * FROM attempts ORDER BY started')]
    executions=[];results={};job_index={j['job_id']:j for j in jobs}
    for attempt in attempts:
        job=job_index[attempt['job_id']]
        result=read(attempt['result']) if attempt['result'] and Path(attempt['result']).exists() else None
        executions.append({'job_id':job['job_id'],'scenario_id':job['scenario_id'],'controller':job['controller'],
            'attempt_id':attempt['attempt_id'],'status':attempt['status'],'started_utc':iso(attempt['started']),
            'ended_utc':iso(attempt['ended']),'worker_wall_s':attempt['wall_s'],
            'simulation_duration_s':None if result is None else result['simulated_duration_s'],
            'run_id':None if result is None else result['run_id'],'result':attempt['result'],
            'engine_sha256':None if result is None else result['input_hashes']['engine_source_sha256'],
            'input_hashes':None if result is None else result['input_hashes'],
            'peak_rss_bytes':attempt['peak_rss_bytes'],'bytes':attempt['bytes'],'error':attempt['error']})
        if result is not None and attempt['attempt_id']==job['attempt_id']:results[job['job_id']]=result
    groups=defaultdict(dict)
    policies={}
    for job in jobs:groups[job['scenario_id']][job['controller']]=job
    for policy in header['controllers']:
        policy_jobs=[j for j in jobs if j['controller']==policy]
        observed=[results[j['job_id']] for j in policy_jobs if j['job_id'] in results]
        journeys=[journey for result in observed for journey in result['journeys']]
        ordinary=[r['metrics']['ordinary'] for r in observed if 'ordinary' in r['metrics']]
        approaches=[a for r in observed for a in r['metrics'].get('approaches',[])]
        quality=Counter()
        for r in observed:
            for key,value in r['metrics'].get('evaluation_prediction_quality',{}).items():
                if isinstance(value,(int,float)):quality[key]+=value
        eta_count=quality['labelled_eta_count'];queue_count=quality['labelled_queue_count']
        policies[policy]={'planned_executions':len(policy_jobs),'status_counts':dict(Counter(j['status'] for j in policy_jobs)),
            'results_available':len(observed),'observed_ambulances':len(journeys),
            'completed_ambulances':sum(j['completed'] for j in journeys),
            'censored_ambulances':sum(not j['completed'] for j in journeys),
            'journey_s':distribution(j['journey_time_s'] for j in journeys),
            'stopped_s':distribution(j['stopped_time_s'] for j in journeys),
            'approach_signal_response_s':distribution(a['signal_response_s'] for a in approaches),
            'approach_passage_s':distribution(a['passage_wait_s'] for a in approaches),
            'approaches_missing_crossing':sum(a['crossed_s'] is None for a in approaches),
            'red_stopped_s':distribution(sum(a.get('stopped_on_red_s',0) for a in r['metrics'].get('approaches',[])) for r in observed if 'approaches' in r['metrics']),
            'ordinary_time_loss_s':distribution(o['observed_time_loss_s'] for o in ordinary),
            'ordinary_wait_s':distribution(o['waiting_time_s'] for o in ordinary),
            'ordinary_insertion_delay_s':distribution(o['insertion_delay_s'] for o in ordinary),
            'ordinary_unfinished':sum(o['unfinished_inserted']+o.get('uninserted_at_end',0) for o in ordinary),
            'pedestrian_maximum_wait_s':distribution(r['metrics'].get('pedestrian',{}).get('maximum_observed_continuous_wait_s') for r in observed),
            'collision_episodes':sum(r['collision_events']>0 for r in observed),
            'collision_events':sum(r['collision_events'] for r in observed),
            'teleports':sum(r['teleport_events'] for r in observed),
            'phase_audit_errors':sum(r['metrics'].get('safety_audit_errors',0) for r in observed),
            'planner_max_latency_ms':distribution(r['metrics'].get('planner_latency_ms',{}).get('max') for r in observed),
            'model_fallback_events':sum(r['metrics'].get('event_counts',{}).get('planner_fallback',0) for r in observed),
            'prediction_quality':{**quality,'eta_mae_s':quality['forecast_absolute_error_sum_s']/eta_count if eta_count else None,
                'analytical_eta_mae_s':quality['analytical_absolute_error_sum_s']/eta_count if eta_count else None,
                'queue_mae':quality['queue_absolute_error_sum']/queue_count if queue_count else None,
                'queue_persistence_mae':quality['persistence_absolute_error_sum']/queue_count if queue_count else None,
                'interval_coverage':quality['interval_covered_count']/quality['interval_count'] if quality['interval_count'] else None}}
    pairs=[];pair_audit=[];incomplete=missing=mismatched=unsafe=0
    left_policy,right_policy=header['primary_comparison']
    paths={a['job_id']:a['result'] for a in attempts if a['result']}
    for scenario_id,policies_for_scenario in groups.items():
        left=policies_for_scenario.get(left_policy);right=policies_for_scenario.get(right_policy)
        if not left or not right:missing+=1;continue
        a=results.get(left['job_id']);b=results.get(right['job_id'])
        audit={'scenario_id':scenario_id,'seed':left['seed'],'family':left['family'],'demand':left['demand'],'od':left['od']}
        if a is None or b is None:
            missing+=1;audit['status']='missing_result';pair_audit.append(audit);continue
        try:comparison=compare(Path(paths[left['job_id']]),Path(paths[right['job_id']]))
        except ValueError as error:
            mismatched+=1;audit.update(status='unmatched',error=str(error));pair_audit.append(audit);continue
        complete=all(j['paired_completed'] for j in comparison['journeys'])
        if not complete:
            incomplete+=1;audit['status']='censored';pair_audit.append(audit);continue
        safety_issue=any(r['collision_events'] or r['teleport_events'] or r['metrics'].get('safety_audit_errors',0) for r in (a,b))
        unsafe+=safety_issue
        # Unsafe outcomes remain in the primary estimate and separately flagged; never cherry-pick them away.
        pair={**audit,'without_s':statistics.mean(j['without_s'] for j in comparison['journeys']),
              'with_s':statistics.mean(j['with_s'] for j in comparison['journeys']),'safety_issue':safety_issue,
              'ordinary_without':a['metrics'].get('ordinary'),'ordinary_with':b['metrics'].get('ordinary')}
        pairs.append(pair);pair_audit.append({**pair,'status':'paired_complete'})
    primary=clustered_estimate(pairs)
    primary.update(planned_scenarios=header['scenarios'],missing_scenarios=missing,censored_scenarios=incomplete,
        mismatched_scenarios=mismatched,paired_scenarios_with_safety_issue=unsafe,
        mean_definition='Each matched scenario has equal weight; average its ambulance journeys before averaging scenarios')
    # Per-family/load results preserve null values when no matched complete pair exists.
    strata={}
    for family in sorted({j['family'] for j in jobs}):
        for level in header['levels']:
            selected=[p for p in pairs if p['family']==family and p['demand']==level]
            strata[f'{family}/demand-{level}']=clustered_estimate(selected,repetitions=500)
    counts=dict(Counter(j['status'] for j in jobs));finished=sum(counts.get(s,0) for s in TERMINAL)
    point=primary['percent_reduction_in_mean']
    result={'schema_version':1,'planned_executions':header['jobs'],'status_counts':counts,
        'terminal_executions':finished,'actual_attempts':len(attempts),'policies':policies,'primary':primary,
        'strata':strata,'improvement_target_percent':[45,55],
        'conditional_point_estimate_in_target':point is not None and 45<=point<=55,
        'entire_campaign_target_established':finished==header['jobs'] and len(pairs)==header['scenarios'] and not unsafe and point is not None and 45<=point<=55,
        'note':'A target is not substituted for evidence. Failed, incomplete and missing pairs remain explicit. Conditional means are not population claims.',
        'runtime_profile':{'worker_wall_s':distribution(a['wall_s'] for a in attempts if a['wall_s'] is not None),
            'peak_worker_rss_bytes':distribution(a['peak_rss_bytes'] for a in attempts if a['peak_rss_bytes'] is not None),
            'episode_bytes':distribution(a['bytes'] for a in attempts if a['bytes'] is not None)}}
    evidence=root/'execution-evidence.jsonl'
    with evidence.open('w',encoding='utf-8') as stream:
        for row in executions:stream.write(json.dumps(row)+'\n')
    selected=[e for e in executions if e['status'] in TERMINAL]
    if len(selected)>20:
        selected=random.Random(2026).sample(selected,20)
    save(root/'timing-audit-20.json',{'available_terminal_attempts':len([e for e in executions if e['status'] in TERMINAL]),
        'sample_size':len(selected),'selection':'Up to 20 terminal attempts, deterministic seed-2026 sample when more exist',
        'executions':selected})
    save(root/'paired-outcomes.json',pair_audit)
    save(root/'report.json',result)
    text=f"# Frozen ZELVO evaluation\n\nRecorded terminal executions: **{finished:,} / {header['jobs']:,}**. Actual attempts: {len(attempts):,}.\n\n"
    text+=f"Matched complete scenarios: **{len(pairs):,} / {header['scenarios']:,}**. Missing: {missing}; censored: {incomplete}; unmatched: {mismatched}.\n\n"
    text+='No mean improvement is available yet.\n' if point is None else f"Conditional reduction in mean journey time: **{point:.2f}%**; mean saved **{primary['mean_saved_s']:.2f} s**. Target: 45–55%.\n"
    text+='\nThese conditional results do not hide failed, censored or unsafe episodes. See report.json for denominators, distributions, seed-cluster uncertainty and ordinary-traffic impacts. Execution timestamps and hashes are in execution-evidence.jsonl; timing-audit-20.json is the readable sample.\n'
    (root/'report.md').write_text(text,encoding='utf-8')
    return {'planned':header['jobs'],'terminal':finished,'matched_complete':len(pairs),'mean_saved_s':primary['mean_saved_s'],
            'percent_reduction_in_mean':point,'entire_campaign_target_established':result['entire_campaign_target_established']}
