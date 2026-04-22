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
