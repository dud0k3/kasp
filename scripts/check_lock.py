"""Check every installed Python distribution against the committed lock."""
from importlib.metadata import distributions
from pathlib import Path
import re
import sys


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


expected = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    name, version = line.split("==")
    expected[normalized(name)] = version
actual = {normalized(d.metadata["Name"]): d.version for d in distributions()}
if actual != expected:
    for name in sorted(expected.keys() | actual.keys()):
        if actual.get(name) != expected.get(name):
            print(name, "expected", expected.get(name), "installed", actual.get(name))
    raise SystemExit("Python environment does not match requirements.txt")
print("All", len(actual), "Python dependencies match the lock")
