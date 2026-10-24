"""The serial line protocol (design.md "Serial line formats"): what the hub understands, and what it refuses."""
from hypothesis import given, settings
from hypothesis import strategies as st

from roomsense_hub import (
    CsiRecord,
    Heartbeat,
    Response,
    TagSummary,
    format_record,
    parse_line,
)

names = st.from_regex(r"[A-Za-z0-9_-]{1,15}", fullmatch=True)
tag_ids = st.from_regex(r"[A-Za-z0-9_-]{1,4}", fullmatch=True)
versions = st.from_regex(r"[0-9A-Za-z._+-]{1,31}", fullmatch=True)
u32 = st.integers(0, 4294967295)
channels = st.integers(1, 14)
macs = st.binary(min_size=6, max_size=6).map(lambda b: ":".join(f"{x:02x}" for x in b))
amplitude_lists = st.lists(st.integers(0, 255), min_size=1, max_size=120).map(tuple)

heartbeats = st.builds(Heartbeat, names, names, macs, versions, u32, st.integers(0, 100000), u32, u32,
                       st.sampled_from(["HUB", "EDGE", "TRAINING"]))
csi_records = st.builds(CsiRecord, names, macs, u32, u32, st.integers(-128, 0), channels, amplitude_lists)
tag_summaries = st.builds(
    TagSummary, names, names, tag_ids, st.integers(1, 100000),
    st.integers(-1280, 0).map(lambda x: x / 10), st.integers(-128, 0),
)
any_record = st.one_of(heartbeats, csi_records, tag_summaries)

GOOD_CSI = CsiRecord("RX1", "4c:c3:82:20:c5:1c", 5, 1000, -50, 11, tuple(range(64)))


@given(any_record)
def test_every_record_round_trips(record):
    assert parse_line(format_record(record) + "\n") == record


def test_csi_matches_the_design_format_exactly():
    # CSI,<node_id>,<tx_mac>,<seq>,<ts_us>,<rssi_dbm>,<channel>,<n_sub>,<amp_0>,...
    line = "CSI,RX1,4c:c3:82:20:c5:1c,7,123456,-48,11,3,10,20,30"
    record = parse_line(line)
    assert record == CsiRecord("RX1", "4c:c3:82:20:c5:1c", 7, 123456, -48, 11, (10, 20, 30))
    assert format_record(record) == line


def test_heartbeat_matches_the_design_format_exactly():
    # HB,<node_id>,<room_id>,<paired_tx_mac>,<fw_version>,<uptime_ms>,<measured_pps>,<free_heap>,<csi_q_drops>,<rx_mode>
    line = "HB,RX1,R1,4c:c3:82:20:c5:1c,0.1.0,28123,98,181264,0,HUB"
    record = parse_line(line)
    assert record == Heartbeat("RX1", "R1", "4c:c3:82:20:c5:1c", "0.1.0", 28123, 98, 181264, 0, "HUB")
    assert format_record(record) == line


def test_tag_summary_matches_the_spec_format_exactly():
    # Requirement 24.4: TAG,<node_id>,<room_id>,<tag_id>,<packets_heard>,<mean_rssi>,<max_rssi>
    line = "TAG,RX1,R1,E1,9,-61.5,-55"
    record = parse_line(line)
    assert record == TagSummary("RX1", "R1", "E1", 9, -61.5, -55)
    assert format_record(record) == line


@given(st.text())
@settings(max_examples=300)
def test_arbitrary_text_never_raises(text):
    parse_line(text)  # must not raise; result is a record or None


@given(st.binary())
def test_arbitrary_bytes_decoded_loosely_never_raise(data):
    parse_line(data.decode("utf-8", errors="replace"))


def test_boot_rom_and_idf_log_lines_are_ignored():
    for noise in [
        "ets Jun  8 2016 00:22:57",
        "rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)",
        "I (312) wifi:mode : sta (24:6f:28:00:00:01)",
        "W (1203) csi: something odd",
        "roomsense> ",
        "",
        "   ",
        "\r\n",
    ]:
        assert parse_line(noise) is None


def test_the_old_boot_record_and_other_unknown_types_are_ignored():
    assert parse_line("BOOT,NODE,rx,ROOM1,0.1.0,11,HT20") is None
    assert parse_line("RSST,RX1,R1,1,2,3") is None  # edge-mode line: not implemented here


def test_a_line_that_starts_mid_record_is_ignored():
    line = format_record(GOOD_CSI)
    assert parse_line(line[10:]) is None  # capture began in the middle of the line


@given(csi_records, st.integers(1, 70))
def test_a_record_cut_at_a_field_boundary_is_rejected(record, keep_fields):
    fields = format_record(record).split(",")
    cut = ",".join(fields[: min(keep_fields, len(fields) - 1)])
    assert parse_line(cut) is None


def test_csi_with_the_wrong_amplitude_count_is_rejected():
    fields = format_record(GOOD_CSI).split(",")
    assert parse_line(",".join(fields[:-1])) is None  # 63 amplitudes but n_sub still says 64
    assert parse_line(",".join(fields + ["10"])) is None  # 65 amplitudes
    assert parse_line("CSI,RX1,4c:c3:82:20:c5:1c,1,2,-50,11,0") is None  # n_sub of zero


def test_out_of_range_values_are_rejected():
    fields = format_record(GOOD_CSI).split(",")

    def with_field(index, value):
        copy = list(fields)
        copy[index] = value
        return ",".join(copy)

    assert parse_line(with_field(8 + 3, "256")) is None  # amplitude above 255
    assert parse_line(with_field(8 + 3, "-1")) is None
    assert parse_line(with_field(2, "4C:C3:82:20:C5:1C")) is None  # uppercase MAC is not the protocol
    assert parse_line(with_field(2, "4c:c3:82:20:c5")) is None
    assert parse_line(with_field(3, "4294967296")) is None  # seq beyond 32 bits
    assert parse_line(with_field(5, "5")) is None  # positive rssi
    assert parse_line(with_field(6, "99")) is None  # impossible channel
    assert parse_line(with_field(1, "bad name")) is None


def test_heartbeat_rejects_unknown_modes_and_wrong_field_counts():
    assert parse_line("HB,RX1,R1,4c:c3:82:20:c5:1c,0.1.0,1000,100,181264,0,SOMETHING") is None
    assert parse_line("HB,RX1,R1,4c:c3:82:20:c5:1c,0.1.0,1000,100,181264,0") is None
    assert parse_line("HB,RX1,R1,4c:c3:82:20:c5:1c,0.1.0,1000,100,181264,0,HUB,extra") is None
    # the old heartbeat shape (with a role field) is no longer valid
    assert parse_line("HB,NODE,rx,ROOM1,1123,0,11,0") is None


def test_tag_summary_wrong_field_count_is_rejected():
    assert parse_line("TAG,RX1,R1,E1,9,-61.5") is None


def test_command_replies_are_parsed_as_responses():
    assert parse_line("OK,SET,node_id") == Response("OK", ("SET", "node_id"))
    assert parse_line("ERR,SET,bad_channel") == Response("ERR", ("SET", "bad_channel"))
    assert parse_line("PONG,RX1") == Response("PONG", ("RX1",))
    assert parse_line("CFG,node_id=RX1") == Response("CFG", ("node_id=RX1",))
    assert parse_line("OK,,") is None  # empty fields are not valid
