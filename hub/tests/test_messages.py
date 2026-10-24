from __future__ import annotations

import pytest

from hub.web.messages import label_for


def test_label_for_maps_no_detection_with_space() -> None:
    assert label_for("NO_DETECTION") == "NO DETECTION"
    for s in ("MOTION", "POSSIBLE", "UNKNOWN"):
        assert label_for(s) == s


def test_label_for_rejects_unknown_state() -> None:
    with pytest.raises(ValueError):
        label_for("EMPTY")  # type: ignore[arg-type]
