"""Tests for :mod:`slama.site_paths` root detection and path mapping."""
from pathlib import Path

import pytest

from slama import site_paths


@pytest.fixture
def no_env(monkeypatch):
    """Clear the conftest pin so auto-detection runs."""
    monkeypatch.delenv(site_paths.SITE_ROOT_ENV, raising=False)
    site_paths.reset_site_root()


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(site_paths.SITE_ROOT_ENV, str(tmp_path))
    site_paths.reset_site_root()
    assert site_paths.site_root() == tmp_path


def test_empty_env_var_is_ignored(monkeypatch, no_env):
    monkeypatch.setenv(site_paths.SITE_ROOT_ENV, "")
    monkeypatch.setattr(site_paths, "LIVE_MARKER", Path("/nonexistent/global/configFiles"))
    assert site_paths.site_root() == site_paths.MIRROR_ROOT


def test_live_global_detected(monkeypatch, tmp_path, no_env):
    marker = tmp_path / "global" / "configFiles"
    marker.mkdir(parents=True)
    monkeypatch.setattr(site_paths, "LIVE_MARKER", marker)
    assert site_paths.site_root() == site_paths.LIVE_ROOT


def test_other_instances_detected_separately(monkeypatch, tmp_path, no_env, caplog):
    marker = tmp_path / "global" / "configFiles"
    marker.mkdir(parents=True)
    monkeypatch.setattr(site_paths, "LIVE_MARKER", marker)
    monkeypatch.setattr(site_paths, "OTHER_INSTANCES_LIVE_MARKER", tmp_path / "nonexistent")
    assert site_paths.site_root() == site_paths.LIVE_ROOT
    assert site_paths.site_root(site_paths.OTHER_INSTANCES_TREE) == site_paths.MIRROR_ROOT
    assert site_paths.site_path("/otherInstances/acc/1/configFiles/pointingModel") == \
        site_paths.MIRROR_ROOT / "otherInstances/acc/1/configFiles/pointingModel"
    assert "different roots" in caplog.text


def test_both_trees_live_no_warning(monkeypatch, tmp_path, no_env, caplog):
    for name, sub in (("LIVE_MARKER", "global/configFiles"),
                      ("OTHER_INSTANCES_LIVE_MARKER", "otherInstances/acc")):
        (tmp_path / sub).mkdir(parents=True)
        monkeypatch.setattr(site_paths, name, tmp_path / sub)
    assert site_paths.site_root(site_paths.OTHER_INSTANCES_TREE) == site_paths.LIVE_ROOT
    assert "different roots" not in caplog.text


def test_env_var_overrides_both_trees(monkeypatch, tmp_path):
    monkeypatch.setenv(site_paths.SITE_ROOT_ENV, str(tmp_path))
    site_paths.reset_site_root()
    assert site_paths.site_path("/otherInstances/acc/2/x") == tmp_path / "otherInstances/acc/2/x"
    assert site_paths.site_root() == tmp_path


def test_unknown_tree_raises():
    with pytest.raises(ValueError, match="unknown site tree"):
        site_paths.site_root("bogus")


def test_mirror_fallback(monkeypatch, no_env):
    monkeypatch.setattr(site_paths, "LIVE_MARKER", Path("/nonexistent/global/configFiles"))
    monkeypatch.setattr(site_paths, "OTHER_INSTANCES_LIVE_MARKER", Path("/nonexistent/otherInstances/acc"))
    assert site_paths.site_root() == site_paths.MIRROR_ROOT
    assert site_paths.site_root(site_paths.OTHER_INSTANCES_TREE) == site_paths.MIRROR_ROOT


def test_mirror_is_repo_site_dir():
    assert site_paths.MIRROR_ROOT.name == "site"
    assert (site_paths.MIRROR_ROOT / "global" / "configFiles" / "rxtype.conf").is_file()


def test_root_is_cached_until_reset(monkeypatch, tmp_path):
    first = site_paths.site_root()
    monkeypatch.setenv(site_paths.SITE_ROOT_ENV, str(tmp_path))
    assert site_paths.site_root() == first
    site_paths.reset_site_root()
    assert site_paths.site_root() == tmp_path


def test_site_path_reroots(monkeypatch, tmp_path):
    monkeypatch.setenv(site_paths.SITE_ROOT_ENV, str(tmp_path))
    site_paths.reset_site_root()
    assert site_paths.site_path("/global/configFiles/rxtype.conf") == \
        tmp_path / "global" / "configFiles" / "rxtype.conf"


def test_site_path_live_root_is_identity(monkeypatch):
    monkeypatch.setenv(site_paths.SITE_ROOT_ENV, "/")
    site_paths.reset_site_root()
    assert site_paths.site_path("/global/polar/ser7.dat") == Path("/global/polar/ser7.dat")


def test_site_path_rejects_relative():
    with pytest.raises(ValueError, match="absolute"):
        site_paths.site_path("global/configFiles/rxtype.conf")
