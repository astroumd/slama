"""Unit tests for fault-system actions."""
import pytest

from slama.fault.actions import LogFileAction, build_action
from slama.fault.faultnode import FaultEvent
from slama.monitor.monitorpoint import Validity


def _event(name="a:b", validity=Validity.VALID_ERROR, ts=1700000000.0):
    return FaultEvent(
        canonical_name=name,
        validity=validity,
        timestamp=ts,
        transient_filter_s=0.0,
    )


class TestLogFileAction:
    def test_appends_one_line_per_event(self, tmp_path):
        path = tmp_path / "faults.log"
        action = LogFileAction(path)
        action.fire(_event(name="a:b", validity=Validity.VALID_ERROR_HIGH))
        action.fire(_event(name="c:d", validity=Validity.INVALID_NO_HW))

        lines = path.read_text().splitlines()
        assert len(lines) == 2
        assert "a:b" in lines[0]
        assert "VALID_ERROR_HIGH" in lines[0]
        assert "c:d" in lines[1]
        assert "INVALID_NO_HW" in lines[1]

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "faults.log"
        action = LogFileAction(path)
        action.fire(_event())
        assert path.exists()


class TestBuildAction:
    def test_builds_log_file_action(self, tmp_path):
        spec = {"type": "log_file", "path": str(tmp_path / "f.log")}
        action = build_action(spec)
        assert isinstance(action, LogFileAction)

    def test_rejects_missing_type(self):
        with pytest.raises(ValueError, match="missing 'type'"):
            build_action({"path": "/tmp/x"})

    def test_rejects_unknown_type(self):
        with pytest.raises(ValueError, match="unknown action type"):
            build_action({"type": "smoke_signal"})

    def test_log_file_requires_path(self):
        with pytest.raises(ValueError, match="requires 'path'"):
            build_action({"type": "log_file"})


class TestLogLineValueAndContext:
    def test_value_and_context_appended(self, tmp_path):
        path = tmp_path / "faults.log"
        event = FaultEvent(
            canonical_name="monitorsystem:antenna:4:gunn1_lock_fault",
            validity=Validity.VALID_ERROR, timestamp=1700000000.0,
            transient_filter_s=5.0, value=False,
            context={"monitorsystem:antenna:4:gunn1_pll_ifpower": -1.4e29,
                     "monitorsystem:antenna:4:gunn1_pll_noise": None},
        )
        LogFileAction(path).fire(event)
        (line,) = path.read_text().splitlines()
        assert line.split()[1:] == [
            "monitorsystem:antenna:4:gunn1_lock_fault", "VALID_ERROR",
            "value=False",
            "monitorsystem:antenna:4:gunn1_pll_ifpower=-1.4e+29",
            "monitorsystem:antenna:4:gunn1_pll_noise=None",
        ]

    def test_absent_value_and_no_context(self, tmp_path):
        path = tmp_path / "faults.log"
        LogFileAction(path).fire(_event())
        assert path.read_text().split()[-1] == "value=None"

    @pytest.mark.parametrize("value, text", [
        ("terminated", "terminated"),
        ("no restarts", '"no restarts"'),
        ("", '""'),
    ])
    def test_strings_with_spaces_are_quoted(self, tmp_path, value, text):
        path = tmp_path / "faults.log"
        event = FaultEvent("monitorsystem:x", Validity.VALID_ERROR,
                           1700000000.0, 5.0, value=value)
        LogFileAction(path).fire(event)
        assert path.read_text().rstrip("\n").endswith(f"value={text}")
