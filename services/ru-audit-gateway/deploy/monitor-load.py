"""Bounded VPS load runner; run in deploy/ after isolated namespace setup.

Abort the test containers if available host memory falls below 768 MiB or a
neighboring site takes over 2 seconds. It never stops production containers.
"""
import json
import os
import pathlib
import subprocess
import time

compose = ['docker', 'compose', '-p', 'pepper-audit-load', '-f', 'compose.load.yaml']
logs = pathlib.Path(os.environ.get('LOAD_LOG_DIR', '/tmp/pepper-audit-load'))
logs.mkdir(exist_ok=True)
started = time.monotonic()
out = (logs / 'result.jsonl').open('w')
process = subprocess.Popen(compose + ['run', '--rm', '--name', 'pepper-audit-load-client', 'client'], stdout=out, stderr=subprocess.STDOUT)
reason = None
try:
    with (logs / 'metrics.jsonl').open('w') as f:
        while process.poll() is None:
            available = int(next(l.split()[1] for l in pathlib.Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))) / 1024
            stats = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}'], capture_output=True, text=True, timeout=10)
            record = {'elapsed_s': round(time.monotonic() - started, 2), 'available_mib': available,
                      'containers': [json.loads(l) for l in stats.stdout.splitlines() if l.startswith('{')]}
            if int(record['elapsed_s']) % 3 == 0 or record['elapsed_s'] > 40:
                probes = []
                for host in ['lts.itsalt.ru', 'looktwinstudio.ru', 'shhhrk.looktwinstudio.ru', 'shtolyar.looktwinstudio.ru']:
                    r = subprocess.run(['curl', '-sS', '--max-time', '3', '-o', '/dev/null', '-w', '%{http_code} %{time_total}', 'https://' + host + '/'], capture_output=True, text=True)
                    fields = r.stdout.split()
                    probes.append({'host': host, 'result': r.stdout, 'exit': r.returncode})
                    if r.returncode or not fields or fields[0] != '200' or float(fields[1]) > 2:
                        reason = 'neighbor_health'
                record['neighbors'] = probes
            f.write(json.dumps(record) + '\n')
            f.flush()
            if available < 768:
                reason = 'host_memory'
            if time.monotonic() - started > 100:
                reason = 'watchdog'
            if reason:
                break
            time.sleep(1)
finally:
    if process.poll() is None:
        subprocess.run(['docker', 'stop', '-t', '2', 'pepper-audit-load-client'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.wait(timeout=10)
    out.close()
print(json.dumps({'exit': process.returncode, 'abort_reason': reason, 'log_dir': str(logs)}))
raise SystemExit(1 if reason else process.returncode)
