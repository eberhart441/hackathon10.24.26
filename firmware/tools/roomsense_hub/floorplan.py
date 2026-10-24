"""The floor plan picture, its scale, and where each board stands on it.

Edited from the viewer page (upload a picture, click two points to set the scale, click or drag
boards into place) and saved in a folder (default firmware/tools/site/, git-ignored because a
floor plan of a real building can be sensitive). Positions are in feet from the top-left corner
of the picture.

A radio link exists when a receiver is placed AND the transmitter it is listening to is placed.
Receivers are known by node_id; transmitters by MAC address (that is all a receiver reports about
them), with names from boards.json (written by rs-setup) or from this plan.
"""
from __future__ import annotations

import json
import math
import re
import threading
from pathlib import Path

from .dxf_walls import read_dxf_text, to_layout
from .locate import Layout, Link

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "site"
BOARDS_FILE = Path(__file__).resolve().parent.parent / "boards.json"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
SEARCH_MARGIN_FT = 4.0     # motion is searched for this far around the placed boards
DEFAULT_FT_PER_PX = 0.05   # until the scale is set
DXF_UNITS_PER_FT = {1: 12.0, 2: 1.0, 4: 304.8, 5: 30.48, 6: 0.3048}  # $INSUNITS: inches, feet, mm, cm, m
DXF_MARGIN_FT = 2.0        # room around the drawing for boards placed on its outer walls
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,15}$")
_MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def tx_label(mac: str) -> str:
    """Name for a transmitter that nobody named: TX- plus the end of its MAC."""
    return "TX-" + mac.replace(":", "")[-4:]


def _known_transmitters(boards_file: Path) -> dict[str, str]:
    """mac -> name, from boards.json."""
    try:
        boards = json.loads(boards_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {b["mac"].lower(): name for name, b in boards.items()
            if isinstance(b, dict) and b.get("role") == "tx" and _MAC.match(str(b.get("mac", "")).lower())}


class FloorPlan:
    def __init__(self, folder: Path | None = DEFAULT_DIR, boards_file: Path | None = BOARDS_FILE):
        """folder=None keeps everything in memory (used by the simulator and tests).
        boards_file=None: do not read transmitter names from rs-setup's boards.json."""
        self.folder = folder
        self.boards_file = boards_file
        self.lock = threading.Lock()
        self.version = 0
        self.plan = {"image": None, "width_ft": 13.0, "height_ft": 9.33, "scaled": True}
        self.boards: dict[str, dict] = {}
        self._image_bytes: bytes | None = None
        self._load()

    # --- storage ---------------------------------------------------------------
    def _load(self) -> None:
        if self.folder is None:
            return
        try:
            data = json.loads((self.folder / "site.json").read_text(encoding="utf-8"))
            self.plan.update(data.get("plan", {}))
            self.boards = dict(data.get("boards", {}))
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        self.version += 1
        if self.folder is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        data = {"plan": self.plan, "boards": self.boards}
        (self.folder / "site.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def image(self) -> tuple[bytes, str] | None:
        name = self.plan.get("image")
        if not name:
            return None
        content_type = next((t for t, ext in IMAGE_TYPES.items() if name.endswith("." + ext)), "application/octet-stream")
        if self._image_bytes is not None:
            return self._image_bytes, content_type
        if self.folder is None:
            return None
        try:
            return (self.folder / name).read_bytes(), content_type
        except OSError:
            return None

    # --- edits from the page ---------------------------------------------------
    def set_image(self, body: bytes, content_type: str) -> None:
        ext = IMAGE_TYPES.get(content_type.split(";")[0].strip().lower())
        if ext is None:
            raise ValueError("upload a PNG, JPEG, WebP or GIF picture")
        if not body or len(body) > MAX_IMAGE_BYTES:
            raise ValueError("picture is empty or larger than 15 MB")
        with self.lock:
            name = f"floorplan.{ext}"
            self._clear_images()
            if self.folder is None:
                self._image_bytes = body
            else:
                self.folder.mkdir(parents=True, exist_ok=True)
                (self.folder / name).write_bytes(body)
            # a new picture has a new scale; boards keep their feet but should be checked
            self.plan.update({"image": name, "walls": [], "scaled": False, "width_px": None, "height_px": None})
            self._save()

    def set_dxf(self, body: bytes) -> None:
        """A DXF floor plan: its LINE/LWPOLYLINE walls become the background, already to scale."""
        if not body or len(body) > MAX_IMAGE_BYTES:
            raise ValueError("DXF is empty or larger than 15 MB")
        lines, units = read_dxf_text(body.decode("utf-8", errors="replace"))
        if not lines:
            raise ValueError("no LINE or LWPOLYLINE walls found in that DXF")
        per_ft = DXF_UNITS_PER_FT.get(units, 12.0)  # drawings without $INSUNITS are usually inches
        xs = [x for line in lines for x, _ in line]
        ys = [y for line in lines for _, y in line]
        m = DXF_MARGIN_FT * per_ft
        walls = to_layout(lines, (min(xs) - m, max(ys) + m), per_ft)
        width_ft = (max(xs) - min(xs)) / per_ft + 2 * DXF_MARGIN_FT
        height_ft = (max(ys) - min(ys)) / per_ft + 2 * DXF_MARGIN_FT
        if not (1 <= width_ft <= 2000 and 1 <= height_ft <= 2000):
            raise ValueError(f"that DXF is {width_ft:.0f} x {height_ft:.0f} ft; check its units")
        with self.lock:
            self._clear_images()
            self.plan.update({"image": None, "walls": [[list(p) for p in line] for line in walls],
                              "width_ft": round(width_ft, 3), "height_ft": round(height_ft, 3),
                              "width_px": None, "height_px": None, "scaled": True})
            self._save()

    def _clear_images(self) -> None:
        self._image_bytes = None
        if self.folder is not None:
            for old in IMAGE_TYPES.values():
                (self.folder / f"floorplan.{old}").unlink(missing_ok=True)

    def set_scale(self, width_px: float, height_px: float, ft_per_px: float, confirmed: bool = True) -> None:
        """confirmed=False: a placeholder scale right after an upload, until the user measures one.
        Boards keep their position on the picture when the scale changes."""
        if not all(math.isfinite(v) and v > 0 for v in (width_px, height_px, ft_per_px)):
            raise ValueError("scale values must be positive numbers")
        width_ft, height_ft = width_px * ft_per_px, height_px * ft_per_px
        if not (1 <= width_ft <= 2000 and 1 <= height_ft <= 2000):
            raise ValueError("that scale makes the plan smaller than 1 ft or larger than 2000 ft")
        with self.lock:
            old_w = self.plan.get("width_ft") or width_ft
            factor = width_ft / old_w if self.plan.get("width_px") == width_px else 1.0
            for b in self.boards.values():
                b["x"], b["y"] = round(b["x"] * factor, 2), round(b["y"] * factor, 2)
            self.plan.update({"width_px": width_px, "height_px": height_px,
                              "width_ft": round(width_ft, 3), "height_ft": round(height_ft, 3), "scaled": confirmed})
            self._save()

    def set_size(self, width_ft: float, height_ft: float) -> None:
        """Plan without a picture: just a blank area of this size."""
        if not all(math.isfinite(v) and 1 <= v <= 2000 for v in (width_ft, height_ft)):
            raise ValueError("size must be between 1 and 2000 ft")
        with self.lock:
            self.plan.update({"width_ft": width_ft, "height_ft": height_ft})
            self._save()

    def place(self, board_id: str, role: str, x: float, y: float, mac: str | None = None) -> None:
        if not _NAME.match(board_id or ""):
            raise ValueError("board name: up to 15 letters, digits, _ or -")
        if role not in ("rx", "tx"):
            raise ValueError("role must be rx or tx")
        if role == "tx":
            mac = (mac or "").lower()
            if not _MAC.match(mac):
                raise ValueError("a transmitter needs its MAC address")
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("position must be numbers")
        with self.lock:
            w, h = self.plan["width_ft"], self.plan["height_ft"]
            entry = {"role": role, "x": round(min(max(x, 0.0), w), 2), "y": round(min(max(y, 0.0), h), 2)}
            if role == "tx":
                entry["mac"] = mac
            self.boards[board_id] = entry
            self._save()

    def remove(self, board_id: str) -> None:
        with self.lock:
            if self.boards.pop(board_id, None) is not None:
                self._save()

    # --- reading ---------------------------------------------------------------
    def tx_names(self) -> dict[str, str]:
        """mac -> name: boards.json first, then names given on this plan."""
        names = _known_transmitters(self.boards_file) if self.boards_file else {}
        with self.lock:
            for name, b in self.boards.items():
                if b.get("role") == "tx" and b.get("mac"):
                    names[b["mac"]] = name
        return names

    def layout(self, rx_to_tx_mac: dict[str, str | None]) -> Layout | None:
        """The links that can be drawn: placed receivers whose transmitter is placed too."""
        with self.lock:
            tx_pos = {b["mac"]: (b["x"], b["y"]) for b in self.boards.values() if b.get("role") == "tx" and b.get("mac")}
            links = []
            for rx_id, mac in sorted(rx_to_tx_mac.items()):
                rx = self.boards.get(rx_id)
                if rx is None or rx.get("role") != "rx" or not mac or mac.lower() not in tx_pos:
                    continue
                tx = tx_pos[mac.lower()]
                if math.dist(tx, (rx["x"], rx["y"])) < 0.5:
                    continue  # on top of each other: no line to sense along
                links.append(Link(rx_id, tx, (rx["x"], rx["y"])))
            if not links:
                return None
            w, h = self.plan["width_ft"], self.plan["height_ft"]
        xs = [p[0] for l in links for p in (l.tx, l.rx)]
        ys = [p[1] for l in links for p in (l.tx, l.rx)]
        x0, y0 = max(0.0, min(xs) - SEARCH_MARGIN_FT), max(0.0, min(ys) - SEARCH_MARGIN_FT)
        x1, y1 = min(w, max(xs) + SEARCH_MARGIN_FT), min(h, max(ys) + SEARCH_MARGIN_FT)
        return Layout((max(x1 - x0, 1.0), max(y1 - y0, 1.0)), tuple(links), (x0, y0))

    def to_json(self) -> dict:
        with self.lock:
            return {"version": self.version, "plan": dict(self.plan),
                    "boards": {k: dict(v) for k, v in self.boards.items()}}
