"""Repo-wide pytest fixtures."""
import pytest

from slama import site_paths


@pytest.fixture(autouse=True)
def _pin_site_root_to_mirror(monkeypatch):
    """Resolve /global paths against the repo ``site/`` mirror in every test.

    Without this, a test run on-site would auto-detect the live
    ``/global`` and its results would depend on whatever receivers are
    installed that day. Tests that need another root set
    ``SLAMA_SITE_ROOT`` themselves and call
    :func:`slama.site_paths.reset_site_root`.
    """
    monkeypatch.setenv(site_paths.SITE_ROOT_ENV, str(site_paths.MIRROR_ROOT))
    site_paths.reset_site_root()
    yield
    site_paths.reset_site_root()
