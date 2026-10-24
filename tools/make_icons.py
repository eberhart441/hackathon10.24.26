"""Generate RoomSense PWA icons (dependency-free PNG writer). Not part of the build.

Design: dark background, teal house outline with signal arcs inside.
Run: python tools/make_icons.py
"""
import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "dashboard" / "public" / "icons"
BG = (0x0E, 0x11, 0x16)
FG = (0x4F, 0xD1, 0xC5)


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def render(size, scale):
    # Coordinates in unit square, shrunk by `scale` around center (maskable safe zone).
    def u(v):
        return 0.5 + (v - 0.5) * scale

    house = [(0.2, 0.48), (0.5, 0.2), (0.8, 0.48), (0.8, 0.82), (0.2, 0.82), (0.2, 0.48)]
    house = [(u(x), u(y)) for x, y in house]
    cx, cy = u(0.5), u(0.72)
    w = 0.045 * scale
    rows = []
    for j in range(size):
        row = bytearray([0])
        for i in range(size):
            x, y = (i + 0.5) / size, (j + 0.5) / size
            d = min(seg_dist(x, y, *house[k], *house[k + 1]) for k in range(len(house) - 1))
            r = math.hypot(x - cx, y - cy)
            ang = math.atan2(cy - y, x - cx)
            if r < 0.04 * scale:
                d = 0
            elif math.pi / 4 < ang < 3 * math.pi / 4:
                for rad in (0.12, 0.22):
                    d = min(d, abs(r - rad * scale))
            hit = d < w / 2
            row += bytes(FG if hit else BG)
        rows.append(bytes(row))
    return b"".join(rows)


def png(path, size, scale=1.0):
    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data))

    raw = render(size, scale)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(data)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    png(OUT / "icon-192.png", 192)
    png(OUT / "icon-512.png", 512)
    png(OUT / "icon-maskable-512.png", 512, scale=0.7)
    png(OUT / "apple-touch-icon-180.png", 180)
    print("icons written to", OUT)
