import json
import subprocess
import sys

MAX_ITERS = 20

for i in range(1, MAX_ITERS + 1):
    # Run ruff check and write JSON
    # Use Ruff's --output-format and --output-file flags to generate JSON
    subprocess.run([
        sys.executable,
        '-m',
        'ruff',
        'check',
        '.',
        '--output-format',
        'json',
        '--output-file',
        'ruff_all.json',
    ])

    try:
        with open('ruff_all.json', 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception:
        print('ERROR: could not read ruff_all.json')
        sys.exit(2)

    count = len(data)
    print(f'ITER {i}: {count} issues')
    if count == 0:
        print('DONE: no Ruff issues')
        sys.exit(0)

    # Attempt auto-fix
    print('Running ruff --fix...')
    res = subprocess.run([sys.executable, '-m', 'ruff', 'check', '.', '--fix'])
    if res.returncode not in (0, 1):
        print('Ruff --fix failed with', res.returncode)
        sys.exit(res.returncode)

print('MAX_ITERS reached')
# final count
with open('ruff_all.json', 'r', encoding='utf-8') as fh:
    data = json.load(fh)
print('FINAL:', len(data))
sys.exit(1)
