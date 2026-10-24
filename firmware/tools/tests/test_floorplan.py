"""Board placement on the floor plan, and the page's editing endpoints (no hardware, no browser)."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from roomsense_hub import CsiRecord, format_record
from roomsense_hub.floorplan import FloorPlan, tx_label
from roomsense_hub.viewer import Hub, make_handler

TX = "4c:c3:82:28:1d:0c"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4fd0000000049454e44ae426082")


def plan(tmp_path, boards=None):
    boards_file = tmp_path / "boards.json"
    boards_file.write_text(json.dumps(boards or {"TX1": {"mac": TX, "role": "tx"}}), encoding="utf-8")
    return FloorPlan(tmp_path / "site", boards_file)


def test_a_link_needs_both_its_receiver_and_its_transmitter_placed(tmp_path):
    p = plan(tmp_path)
    p.set_size(40, 30)
    p.place("RX1", "rx", 20, 10)
    assert p.layout({"RX1": TX}) is None          # transmitter not placed yet
    p.place("TX1", "tx", 5, 10, mac=TX)
    layout = p.layout({"RX1": TX, "RX9": "aa:bb:cc:dd:ee:ff"})
    assert [(l.rx_id, l.tx, l.rx) for l in layout.links] == [("RX1", (5.0, 10.0), (20.0, 10.0))]
    # motion is searched only around the boards, not across the whole building
    assert layout.origin == (1.0, 6.0) and layout.room == (23.0, 8.0)


def test_positions_and_picture_survive_a_restart(tmp_path):
    p = plan(tmp_path)
    p.set_image(PNG, "image/png")
    p.set_scale(1000, 500, 0.04)                  # 40 x 20 ft
    p.place("TX1", "tx", 3, 4, mac=TX)
    again = plan(tmp_path)
    assert again.boards["TX1"] == {"role": "tx", "x": 3.0, "y": 4.0, "mac": TX}
    assert again.plan["width_ft"] == 40.0 and again.plan["scaled"] is True
    assert again.image() == (PNG, "image/png")


def test_changing_the_scale_keeps_boards_on_the_same_spot_of_the_picture(tmp_path):
    p = plan(tmp_path)
    p.set_image(PNG, "image/png")
    p.set_scale(1000, 500, 0.05, confirmed=False)  # placeholder: 50 ft wide
    p.place("RX1", "rx", 25, 10)                    # middle of the picture
    p.set_scale(1000, 500, 0.02)                    # measured: really 20 ft wide
    assert p.boards["RX1"]["x"] == 10.0 and p.boards["RX1"]["y"] == 4.0


def test_a_dxf_floor_plan_becomes_walls_to_scale(tmp_path):
    from pathlib import Path
    dxf = Path(__file__).resolve().parents[3] / "floor plans" / "walls_only.dxf"
    p = plan(tmp_path)
    p.set_dxf(dxf.read_bytes())
    walls = p.plan["walls"]
    assert walls and p.plan["image"] is None and p.plan["scaled"] is True
    xs = [x for line in walls for x, _ in line]
    ys = [y for line in walls for _, y in line]
    # drawn in inches: the 13 ft room fits inside, and the drawing sits 2 ft in from the edges
    assert p.plan["width_ft"] > 13 and min(xs) == 2.0 and min(ys) == 2.0
    assert max(xs) <= p.plan["width_ft"] - 1.99 and max(ys) <= p.plan["height_ft"] - 1.99
    with pytest.raises(ValueError):
        p.set_dxf(b"0\nSECTION\n0\nEOF\n")


def test_bad_input_is_refused(tmp_path):
    p = plan(tmp_path)
    for call in (lambda: p.place("bad name!", "rx", 1, 1),
                 lambda: p.place("TX2", "tx", 1, 1),               # transmitter without a MAC
                 lambda: p.place("RX1", "gateway", 1, 1),
                 lambda: p.set_image(b"<svg/>", "image/svg+xml"),
                 lambda: p.set_scale(100, 100, -1)):
        with pytest.raises(ValueError):
            call()


def test_unnamed_transmitters_get_a_label_from_their_mac():
    assert tx_label(TX) == "TX-1d0c"


def test_the_hub_lists_transmitters_by_who_hears_them(tmp_path):
    hub = Hub(plan=plan(tmp_path))
    for seq in range(1, 6):
        hub.feed_line(format_record(CsiRecord("RX1", TX, seq, seq * 10_000, -50, 11, tuple([20] * 64))), now=100.0)
    m = json.loads(hub.snapshot_json(100.5))
    assert m["transmitters"] == [{"id": "TX1", "mac": TX, "heardBy": [{"rx": "RX1", "rate": 5}]}]
    assert m["plan"]["boards"] == {} and "layout" not in m


@pytest.fixture
def server(tmp_path):
    hub = Hub(plan=plan(tmp_path))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(hub))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield hub, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def send(url, path, body, content_type="application/json", origin=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(url + path, data=data, method="POST", headers={"Content-Type": content_type})
    if origin:
        req.add_header("Origin", origin)
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_the_page_can_place_boards_and_upload_a_picture(server):
    hub, url = server
    assert send(url, "/plan/board", {"id": "TX1", "role": "tx", "mac": TX, "x": 2, "y": 3}, origin=url) == 204
    assert send(url, "/plan/image", PNG, "image/png", origin=url) == 204
    assert hub.plan.boards["TX1"]["x"] == 2.0
    assert urllib.request.urlopen(url + "/plan/image").read() == PNG
    assert send(url, "/plan/board", {"id": "RX1", "role": "rx", "x": "left", "y": 1}) == 400


def test_another_website_cannot_change_the_plan(server):
    hub, url = server
    status = send(url, "/plan/board", {"id": "RX1", "role": "rx", "x": 1, "y": 1}, origin="https://evil.example")
    assert status == 403 and hub.plan.boards == {}
