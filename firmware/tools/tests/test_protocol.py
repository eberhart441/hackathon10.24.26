"""The serial line protocol: what the hub understands, and what it refuses."""
from hypothesis import given, settings
from hypothesis import strategies as st

from roomsense_hub import (
    AMPLITUDE_COUNT,
    Boot,
    CsiRecord,
    Heartbeat,
    Response,
    TagSummary,
    format_record,
    parse_line,
)

names = st.from_regex(r"[A-Za-z0-9_-]{1,15}", fullmatch=True)
tag_ids = st.from_regex(r"[A-Za-z0-9_-]{1,7}", fullmatch=True)
u32 = st.integers(0, 4294967295)
channels = st.integers(1, 14)
roles = st.sampled_from(["tx", "rx", "tag"])
macs = st.binary(min_size=6, max_size=6).map(lambda b: ":".join(f"{x:02x}" for x in b))

boots = st.builds(Boot, names, roles, names, st.from_regex(r"[0-9A-Za-z._+-]{1,31}", fullmatch=True),
                  channels, st.sampled_from(["HT20", "HT40"]))
heartbeats = st.builds(Heartbeat, names, roles, names, u32, st.integers(0, 100000), channels, u32)
csi_records = st.builds(
    CsiRecord, names, names, macs, u32, u32, st.integers(-128, 0), channels,
    st.lists(st.integers(0, 255), min_size=AMPLITUDE_COUNT, max_size=AMPLITUDE_COUNT).map(tuple),
)
tag_summaries = st.builds(
    TagSummary, names, names, tag_ids, st.integers(1, 100000),
    st.integers(-1280, 0).map(lambda x: x / 10), st.integers(-128, 0),
)
any_record = st.one_of(boots, heartbeats, csi_records, tag_summaries)


@given(any_record)
def test_every_record_round_trips(record):
    assert parse_line(format_record(record) + "\n") == record


@given(csi_records)
def test_csi_lines_have_the_documented_shape(record):
    fields = format_record(record).split(",")
    assert fields[0] == "CSI"
    assert fields[8] == "64"
    assert len(fields) == 9 + 64  # type + 8 header fields + 64 amplitudes


def test_tag_summary_matches_the_spec_format_exactly():
    # Requirement 24.4: TAG,<node_id>,<room_id>,<tag_id>,<packets_heard>,<mean_rssi>,<max_rssi>
    line = "TAG,RX1,ROOM1,E1,9,-61.5,-55"
    record = parse_line(line)
    assert record == TagSummary("RX1", "ROOM1", "E1", 9, -61.5, -55)
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


def test_a_line_that_starts_mid_record_is_ignored():
    record = CsiRecord("RX1", "ROOM1", "1a:00:00:00:00:00", 5, 1000, -50, 11, tuple(range(64)))
    line = format_record(record)
    assert parse_line(line[10:]) is None  # capture began in the middle of the line


@given(csi_records, st.integers(1, 70))
def test_a_record_cut_at_a_field_boundary_is_rejected(record, keep_fields):
    fields = format_record(record).split(",")
    cut = ",".join(fields[: min(keep_fields, len(fields) - 1)])
    assert parse_line(cut) is None


def test_csi_with_wrong_amplitude_count_is_rejected():
    record = CsiRecord("RX1", "ROOM1", "1a:00:00:00:00:00", 5, 1000, -50, 11, tuple([10] * 64))
    fields = format_record(record).split(",")
    assert parse_line(",".join(fields[:-1])) is None  # 63 amplitudes but n still says 64
    assert parse_line(",".join(fields + ["10"])) is None  # 65 amplitudes


def test_out_of_range_values_are_rejected():
    ok = CsiRecord("RX1", "ROOM1", "1a:00:00:00:00:00", 5, 1000, -50, 11, tuple([10] * 64))
    fields = format_record(ok).split(",")

    def with_field(index, value):
        copy = list(fields)
        copy[index] = value
        return ",".join(copy)

    assert parse_line(with_field(8 + 3, "256")) is None  # amplitude above 255
    assert parse_line(with_field(8 + 3, "-1")) is None
    assert parse_line(with_field(3, "1A:00:00:00:00:00")) is None  # uppercase MAC is not the protocol
    assert parse_line(with_field(3, "1a:00:00:00:00")) is None
    assert parse_line(with_field(4, "4294967296")) is None  # seq beyond 32 bits
    assert parse_line(with_field(6, "5")) is None  # positive rssi
    assert parse_line(with_field(7, "99")) is None  # impossible channel
    assert parse_line(with_field(1, "bad name")) is None


def test_boot_and_heartbeat_reject_unknown_roles():
    assert parse_line("BOOT,RX1,gateway,ROOM1,0.1.0,11,HT20") is None
    assert parse_line("HB,RX1,gateway,ROOM1,1000,100,11,0") is None


def test_wrong_field_count_is_rejected():
    assert parse_line("HB,RX1,rx,ROOM1,1000,100,11") is None
    assert parse_line("HB,RX1,rx,ROOM1,1000,100,11,0,extra") is None
    assert parse_line("TAG,RX1,ROOM1,E1,9,-61.5") is None


def test_command_replies_are_parsed_as_responses():
    assert parse_line("OK,CFG,node_id") == Response("OK", ("CFG", "node_id"))
    assert parse_line("ERR,CFG,bad_channel") == Response("ERR", ("CFG", "bad_channel"))
    assert parse_line("PONG,RX1") == Response("PONG", ("RX1",))
    assert parse_line("CFG,node_id=RX1,channel=11") == Response("CFG", ("node_id=RX1", "channel=11"))
    assert parse_line("OK,,") is None  # empty fields are not valid
