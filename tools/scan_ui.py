"""Hook check: no Banned_Words in UI strings, no MAC addresses in dashboard/config (pwa-dashboard Req 9.6, 6.7, 17.1).

Scans every string literal in dashboard/src/**/*.ts(x) (comment lines skipped) for
"empty", "clear", "cleared" or "safe", and every file in dashboard/src and hub/config*
for a MAC-address-like string. Exits 1 and lists each hit if anything matches.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"\b(empty|clear(ed)?|safe)\b", re.I)
MAC = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", re.I)
LITERAL = re.compile(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`")
COMMENT = ("//", "/*", "*")

bad = []
for f in sorted((ROOT / "dashboard/src").rglob("*.ts*")):
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        code = line.strip()
        if code.startswith(COMMENT):
            continue
        code = code.split(" //", 1)[0]  # drop a trailing comment
        if any(BANNED.search(s) for groups in LITERAL.findall(code) for s in groups if s):
            bad.append(f"{f.relative_to(ROOT)}:{n}: banned word: {line.strip()}")

mac_files = list((ROOT / "dashboard/src").rglob("*"))
for cfg in sorted(ROOT.glob("hub/config*")):
    mac_files += cfg.rglob("*")
for f in sorted(p for p in mac_files if p.is_file()):
    for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if MAC.search(line):
            bad.append(f"{f.relative_to(ROOT)}:{n}: MAC-like string: {line.strip()}")

print("\n".join(bad) if bad else "OK")
sys.exit(1 if bad else 0)
