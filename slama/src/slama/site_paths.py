"""Resolve observatory file paths (``/global``, ``/otherInstances``) on- or offsite.

The SMA C code reads configuration and state files at fixed absolute
paths such as ``/global/configFiles/rxtype.conf``. On-site those
directories are live NFS mounts; offsite they don't exist. SLAMA keeps a
partial mirror at ``<repo>/site/``, laid out as a fake filesystem root
(``site/global/configFiles/rxtype.conf``), so a C path maps to either
location by swapping the root prefix.

Each top-level tree (``/global``, ``/otherInstances``) gets its own
root, chosen once per process:

1. The ``SLAMA_SITE_ROOT`` environment variable, if set (``/`` = live),
   for every tree.
2. ``/`` if the tree's live marker directory exists
   (:data:`LIVE_MARKER`, :data:`OTHER_INSTANCES_LIVE_MARKER`).
3. The repository mirror, ``<repo>/site``.

If the trees end up with different roots (e.g. a host that mounts
``/global`` but not ``/otherInstances``), a WARNING is logged: on-site
that means mirror copies are standing in for live files.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path


logger = logging.getLogger(__name__)


SITE_ROOT_ENV: str = "SLAMA_SITE_ROOT"
"""Environment variable that overrides site-root detection."""

LIVE_ROOT: Path = Path("/")
"""Filesystem root used on-site, where ``/global`` is mounted."""

LIVE_MARKER: Path = Path("/global/configFiles")
"""Directory whose presence means the live ``/global`` is mounted."""

OTHER_INSTANCES_LIVE_MARKER: Path = Path("/otherInstances/acc")
"""Directory whose presence means the live ``/otherInstances`` is mounted."""

GLOBAL_TREE: str = "global"
"""Top-level tree name of ``/global`` paths."""

OTHER_INSTANCES_TREE: str = "otherInstances"
"""Top-level tree name of ``/otherInstances`` paths."""

MIRROR_ROOT: Path = Path(__file__).resolve().parents[2] / "site"
"""The repository's offsite mirror (``<repo>/site``)."""

_site_roots: dict[str, Path] | None = None


def _live_markers() -> dict[str, Path]:
    """Map each tree to its live marker, read at call time so tests can patch them."""
    return {GLOBAL_TREE: LIVE_MARKER, OTHER_INSTANCES_TREE: OTHER_INSTANCES_LIVE_MARKER}


def _detect_roots() -> dict[str, Path]:
    """Choose every tree's root and log the choice (see the module docstring)."""
    env = os.environ.get(SITE_ROOT_ENV)
    roots = {}
    for tree, marker in _live_markers().items():
        if env:
            root, reason = Path(env), f"from ${SITE_ROOT_ENV}"
        elif marker.is_dir():
            root, reason = LIVE_ROOT, f"auto: {marker} found"
        else:
            root, reason = MIRROR_ROOT, f"auto: no {marker}, using mirror"
        logger.info("site root for /%s: %s (%s)", tree, root, reason)
        roots[tree] = root
    if len(set(roots.values())) > 1:
        logger.warning("site trees resolve to different roots (%s); mirror copies "
                       "are standing in for live files",
                       ", ".join(f"/{t} -> {r}" for t, r in roots.items()))
    return roots


def site_root(tree: str = GLOBAL_TREE) -> Path:
    """Return the root directory that one tree's observatory paths resolve against.

    The result is cached for the life of the process (the C code also
    reads its site files once); call :func:`reset_site_root` to force
    re-detection, e.g. in tests.

    Parameters
    ----------
    tree : str, optional
        :data:`GLOBAL_TREE` (default) or :data:`OTHER_INSTANCES_TREE`.

    Returns
    -------
    pathlib.Path
        ``$SLAMA_SITE_ROOT`` if set, else ``/`` if the tree's live
        marker is a directory, else :data:`MIRROR_ROOT`.

    Raises
    ------
    ValueError
        Unknown ``tree``.
    """
    global _site_roots
    if tree not in _live_markers():
        raise ValueError(f"unknown site tree {tree!r}")
    if _site_roots is None:
        _site_roots = _detect_roots()
    return _site_roots[tree]


def reset_site_root() -> None:
    """Forget the cached site roots so the next :func:`site_root` re-detects them."""
    global _site_roots
    _site_roots = None


def site_path(c_path: str) -> Path:
    """Map an absolute observatory path to the current site root.

    Parameters
    ----------
    c_path : str
        The path exactly as the C code spells it, e.g.
        ``"/global/configFiles/rxtype.conf"``.

    Returns
    -------
    pathlib.Path
        ``c_path`` re-rooted under its tree's :func:`site_root`
        (``/otherInstances/...`` under the ``otherInstances`` root,
        anything else under the ``global`` root); unchanged when the
        root is ``/``.

    Raises
    ------
    ValueError
        If ``c_path`` is not absolute.
    """
    if not c_path.startswith("/"):
        raise ValueError(f"site path must be absolute: {c_path!r}")
    rel = c_path.lstrip("/")
    tree = OTHER_INSTANCES_TREE if rel.split("/", 1)[0] == OTHER_INSTANCES_TREE else GLOBAL_TREE
    return site_root(tree) / rel
