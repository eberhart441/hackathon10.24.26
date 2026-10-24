"""Hook check: no Banned_Words in UI strings, no MAC addresses in dashboard/config (Req 9.6, 6.7, 17.1)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"\b(empty|clear(ed)?|safe)\b", re.I)
MAC = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", re.I)
LITERAL = re.compile(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'")

bad = []
strings = ROOT / "dashboard/src/scene/strings.ts"
for n, line in enumerate(strings.read_text(encoding="utf-8").splitlines(), 1):
    if any(BANNED.search(a or b) for a, b in LITERAL.findall(line)):
        bad.append(f"{strings.relative_to(ROOT)}:{n}: banned word: {line.strip()}")
for base in ("dashboard/src", "hub/config"):
    for f in sorted((ROOT / base).rglob("*")):
        if not f.is_file():
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if MAC.search(line):
                bad.append(f"{f.relative_to(ROOT)}:{n}: MAC-like string: {line.strip()}")

print("\n".join(bad) if bad else "OK")
sys.exit(1 if bad else 0)
