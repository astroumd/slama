"""Tests for :mod:`slama.sitefiles`: the C parser quirks, on tmp-dir site roots."""
import pytest

from slama import site_paths, sitefiles
from slama.sitefiles import DewarSensors, RxType


@pytest.fixture
def site(monkeypatch, tmp_path):
    """Point the site root at an empty tmp dir; return a file writer."""
    monkeypatch.setenv(site_paths.SITE_ROOT_ENV, str(tmp_path))
    site_paths.reset_site_root()

    def write(c_path, text):
        path = tmp_path / c_path.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    return write


# ---------------------------------------------------------------------------
# rxtype.conf / loadtype.conf
# ---------------------------------------------------------------------------

class TestTypeFiles:
    def test_missing_antenna_defaults_to_tune6(self, site):
        site(sitefiles.RXTYPE_CONFIG_FILE, "7 1\n")
        types = sitefiles.read_rxtypes()
        assert types[7] is RxType.WSMA
        assert all(types[a] is RxType.TUNE6 for a in (1, 2, 3, 4, 5, 6, 8))

    def test_comments_blank_lines_and_inline_comments(self, site):
        site(sitefiles.RXTYPE_CONFIG_FILE,
             "# header\n\n   # indented comment\n1\t1   wSMA since 2025\n")
        assert sitefiles.read_rxtypes()[1] is RxType.WSMA

    def test_negative_type_is_none(self, site):
        site(sitefiles.RXTYPE_CONFIG_FILE, "3 -1\n5 -7\n")
        types = sitefiles.read_rxtypes()
        assert types[3] is RxType.NONE
        assert types[5] is RxType.NONE

    def test_bad_lines_are_skipped(self, site, caplog):
        site(sitefiles.RXTYPE_CONFIG_FILE,
             "2 2\n"      # type >= N_RX_TYPES
             "9 1\n"      # antenna out of range
             "4\n"        # too few fields
             "x 1\n"      # not an integer
             "6 1\n")
        types = sitefiles.read_rxtypes()
        assert types[2] is RxType.TUNE6
        assert types[4] is RxType.TUNE6
        assert types[6] is RxType.WSMA
        assert 9 not in types
        assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 4

    def test_missing_file_returns_none(self, site):
        assert sitefiles.read_rxtypes() is None

    def test_loadtype_uses_its_own_file(self, site):
        site(sitefiles.RXTYPE_CONFIG_FILE, "1 1\n")
        site(sitefiles.LOADTYPE_CONFIG_FILE, "2 1\n")
        loads = sitefiles.read_loadtypes()
        assert loads[1] is RxType.TUNE6
        assert loads[2] is RxType.WSMA


# ---------------------------------------------------------------------------
# antenna_set (the "@rxtype:..." __each__ selector)
# ---------------------------------------------------------------------------

class TestAntennaSet:
    @pytest.fixture(autouse=True)
    def types(self, site):
        site(sitefiles.RXTYPE_CONFIG_FILE, "1 1\n3 -1\n7 1\n8 1\n")

    def test_wsma(self):
        assert sitefiles.antenna_set("rxtype:wsma") == [1, 7, 8]

    def test_tune6_excludes_none(self):
        assert sitefiles.antenna_set("rxtype:tune6") == [2, 4, 5, 6]

    def test_not_wsma_includes_none_like_the_c_else_branch(self):
        assert sitefiles.antenna_set("rxtype:!wsma") == [2, 3, 4, 5, 6]

    def test_none_and_case_insensitive(self):
        assert sitefiles.antenna_set("RXTYPE:None") == [3]

    @pytest.mark.parametrize("bad", ["rxtype", "rxtype:foo", "dewar:wsma", "rxtype:!"])
    def test_malformed_selector_raises(self, bad):
        with pytest.raises(ValueError, match="bad antenna-set selector"):
            sitefiles.antenna_set(bad)

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="loadtype.conf"):
            sitefiles.antenna_set("loadtype:wsma")


# ---------------------------------------------------------------------------
# dewarTemp.conf
# ---------------------------------------------------------------------------

class TestDewarSensors:
    def test_full_line(self, site):
        site(sitefiles.DEWAR_SENSORS_FILE, "# ant ch77 ch12 ch4 limit\n2\t1\t2\t9\t5.0\n")
        d = sitefiles.read_dewar_sensors()[2]
        assert d == DewarSensors(ch77=1, ch12=2, ch4=9, limit4k=5.0)
        assert d.ch4_index == 8

    def test_absent_antenna_gets_c_defaults(self, site):
        site(sitefiles.DEWAR_SENSORS_FILE, "2 1 2 9 5.0\n")
        assert sitefiles.read_dewar_sensors()[5] == DewarSensors(ch77=1, ch12=2, ch4=3, limit4k=5.2)

    def test_short_line_keeps_trailing_defaults(self, site):
        site(sitefiles.DEWAR_SENSORS_FILE, "4 5\n")
        assert sitefiles.read_dewar_sensors()[4] == DewarSensors(ch77=5)

    def test_out_of_range_channel_and_bad_limit_ignored(self, site):
        site(sitefiles.DEWAR_SENSORS_FILE, "6 1 2 17 -1\n")
        assert sitefiles.read_dewar_sensors()[6] == DewarSensors()

    def test_antenna_only_line_is_skipped(self, site):
        site(sitefiles.DEWAR_SENSORS_FILE, "3\n")
        assert sitefiles.read_dewar_sensors()[3] == DewarSensors()

    def test_missing_file_returns_none(self, site):
        assert sitefiles.read_dewar_sensors() is None

    def test_dewar_param(self, site):
        site(sitefiles.DEWAR_SENSORS_FILE, "2 1 2 9 5.0\n")
        assert sitefiles.dewar_param(2, "ch4_index") == 8
        assert sitefiles.dewar_param(2, "limit4k") == 5.0

    @pytest.mark.parametrize("ant, field, match", [
        (2, "ch99", "unknown dewarTemp field"),
        (9, "ch4", "out of range"),
    ])
    def test_dewar_param_errors(self, site, ant, field, match):
        site(sitefiles.DEWAR_SENSORS_FILE, "2 1 2 9 5.0\n")
        with pytest.raises(ValueError, match=match):
            sitefiles.dewar_param(ant, field)


# ---------------------------------------------------------------------------
# wselect.conf
# ---------------------------------------------------------------------------

class TestWsmaSelection:
    def test_parses_modes_case_insensitively(self, site):
        site(sitefiles.WSMA_SELECT_FILE, "# ant p1 p2 p3 p4\n7\t\tL\tH\tg\tD\n")
        assert sitefiles.read_wsma_selection() == {7: {1: "L", 2: "H", 3: "G", 4: "D"}}

    def test_invalid_code_leaves_position_unset(self, site):
        site(sitefiles.WSMA_SELECT_FILE, "1 L X G D\n")
        assert sitefiles.read_wsma_selection() == {1: {1: "L", 3: "G", 4: "D"}}

    def test_short_line_and_bad_antenna_skipped(self, site):
        site(sitefiles.WSMA_SELECT_FILE, "1 L H G\n9 L H G D\n")
        assert sitefiles.read_wsma_selection() == {}

    def test_missing_file_returns_none(self, site):
        assert sitefiles.read_wsma_selection() is None


# ---------------------------------------------------------------------------
# The committed mirror itself
# ---------------------------------------------------------------------------

def test_mirror_contents():
    """The conftest pins the root to site/; its files (live copies of
    2026-10-20) must parse to the known layout."""
    assert sitefiles.antenna_set("rxtype:wsma") == [1, 7, 8]
    assert sitefiles.antenna_set("loadtype:wsma") == [1, 7, 8]
    assert {a: sitefiles.dewar_param(a, "ch4") for a in (2, 3, 4, 5, 6)} == \
        {2: 9, 3: 11, 4: 3, 5: 11, 6: 11}
    gh_dl = {1: "G", 2: "H", 3: "D", 4: "L"}
    assert sitefiles.read_wsma_selection() == {1: gh_dl, 7: gh_dl, 8: gh_dl}


class TestWselectParam:
    def test_string_keys_and_missing_antenna(self, site):
        site(sitefiles.WSMA_SELECT_FILE, "7 L H G D\n")
        assert sitefiles.wselect_param(7) == {"1": "L", "2": "H", "3": "G", "4": "D"}
        assert sitefiles.wselect_param(1) == {}

    def test_errors(self, site):
        with pytest.raises(ValueError, match="wselect.conf"):
            sitefiles.wselect_param(1)
        site(sitefiles.WSMA_SELECT_FILE, "7 L H G D\n")
        with pytest.raises(ValueError, match="out of range"):
            sitefiles.wselect_param(9)


class TestSmokeIgnore:
    def test_one_line(self, site):
        site(sitefiles.SMOKE_IGNORE_FILE, "0 0 1 0 0 0 0 2\n")
        flags = sitefiles.read_smoke_ignore()
        assert [a for a, ignored in flags.items() if ignored] == [3, 8]

    def test_values_may_span_lines(self, site):
        site(sitefiles.SMOKE_IGNORE_FILE, "1 0 0 0\n0 0 0 1\n")
        assert [a for a, i in sitefiles.read_smoke_ignore().items() if i] == [1, 8]

    def test_short_file_and_junk_stop_reading(self, site):
        site(sitefiles.SMOKE_IGNORE_FILE, "0 1 x 1 1\n")
        assert [a for a, i in sitefiles.read_smoke_ignore().items() if i] == [2]

    def test_missing_file_returns_none(self, site):
        assert sitefiles.read_smoke_ignore() is None

    def test_param_missing_file_ignores_nothing(self, site, caplog):
        assert sitefiles.smoke_ignore_param(3) is False
        assert "ignoreAntSmoking.txt" in caplog.text

    def test_param_value_and_range(self, site):
        site(sitefiles.SMOKE_IGNORE_FILE, "0 0 1 0 0 0 0 0\n")
        assert sitefiles.smoke_ignore_param(3) is True
        assert sitefiles.smoke_ignore_param(4) is False
        with pytest.raises(ValueError, match="out of range"):
            sitefiles.smoke_ignore_param(0)


def test_mirror_smoke_ignore_is_all_zero():
    assert not any(sitefiles.read_smoke_ignore().values())
