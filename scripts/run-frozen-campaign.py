"""Run a frozen coordinator and refresh evidence during a long local campaign."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--wait-profile', action='store_true', help='Wait for the already-running profile to finish')
    parser.add_argument('--verify-pilot', action='store_true', help='Run separate CLI parity/ablations before dispatching remaining jobs')
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root/'engine'))
    from zelvo.campaign import connect, TERMINAL, verify
    from zelvo.campaign_io import read, save, process_alive
    from zelvo.campaign_report import report
    from zelvo.campaign_audit import audit
    verify(root)
    save(root/'monitor-started.json', {'monitor_pid': os.getpid(), 'started_unix_s': time.time(),
         'waiting_for_profile': args.wait_profile, 'verify_pilot': args.verify_pilot})
    if args.wait_profile:
        while not (root/'profile.json').exists():
            state = read(root/'status.json')
            if not process_alive(state['coordinator_pid']):
                # The profile writes its projection immediately after releasing its lock.
                time.sleep(2)
                if not (root/'profile.json').exists():
                    raise RuntimeError('Profile coordinator ended without a profile; inspect its logs before resuming')
            time.sleep(10)
        print(json.dumps({'profile': read(root/'profile.json')}), flush=True)
    if args.verify_pilot:
        helper = Path(__file__).with_name('verify-campaign-pilot.py')
        with (root/'pilot-verification.stdout.log').open('a') as stdout, (root/'pilot-verification.stderr.log').open('a') as stderr:
            subprocess.run([sys.executable, str(helper), '--root', str(root)], check=True,
                           stdout=stdout, stderr=stderr, timeout=9000,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    code = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('zelvo.campaign',run_name='__main__')"
    command = [sys.executable, '-c', code, str(root/'engine'), 'run', '--root', str(root),
               '--workers', str(args.workers)]
    with (root/'coordinator.stdout.log').open('a') as stdout, (root/'coordinator.stderr.log').open('a') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        save(root/'background.json', {'monitor_pid': os.getpid(), 'coordinator_pid': process.pid,
                                     'started_unix_s': time.time(), 'command': command})
        last_count = -1
        last_report = 0
        while True:
            finished = process.poll() is not None
            # Poll the compact ledger, not thousands of episode JSON files.
            with connect(root) as database:
                counts = dict(database.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
            measured = {'counts': counts, 'terminal_jobs': sum(counts.get(s, 0) for s in TERMINAL),
                        'updated_unix_s': time.time()}
            count = measured['terminal_jobs']
            # Refresh after the first 20, then every ten minutes while progress exists.
            due = count >= 20 and last_count < 20 or time.monotonic()-last_report >= 600
            if finished or count != last_count and due:
                summary = report(root)
                print(json.dumps(summary), flush=True)
                if count >= 20 or finished:
                    print(json.dumps(audit(root)), flush=True)
                last_count = count
                last_report = time.monotonic()
            if finished:
                save(root/'background-ended.json', {'ended_unix_s': time.time(),
                     'coordinator_exit_code': process.returncode, 'status': measured})
                raise SystemExit(process.returncode)
            time.sleep(10)


if __name__ == '__main__':
    main()
