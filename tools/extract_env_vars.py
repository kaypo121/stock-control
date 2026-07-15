import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
keys = set()
for path in root.rglob('*.py'):
    text = path.read_text(encoding='utf-8', errors='ignore')
    for match in re.finditer(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]", text):
        keys.add(match.group(1))

for key in sorted(keys):
    print(key)
