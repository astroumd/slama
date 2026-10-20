"""Resolve observatory file paths (``/global``, ``/otherInstances``) on- or offsite.

The SMA C code reads configuration and state files at fixed absolute
paths such as ``/global/configFiles/rxtype.conf``. On-site those
directories are live NFS mounts; offsite they don't exist. SLAMA keeps a
partial mirror at ``<repo>/site/``, laid out as a fake filesystem root
(``site/global/configFiles/rxtype.conf``), so a C path maps to either
location by swapping the root prefix.

The root is chosen once per process, in this order:

1. The ``SLAMA_SITE_ROOT`` environment variable, if set (``/`` = live).
2. ``/`` if ``/global/configFiles`` is a directory (we are on-site).
3. The repository mirror, ``<repo>/site``.

Known limitation: detection looks only at ``/global``. A host that
mounts ``/global`` but not ``/otherInstances`` would resolve
``/otherInstances`` paths to the (missing) live directory.
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

MIRROR_ROOT: Path = Path(__file__).resolve().parents[2] / "site"
"""The repository's offsite mirror (``<repo>/site``)."""

_site_root: Path | None = None


def site_root() -> Path:
    """Return the root directory that observatory paths resolve against.

    The result is cached for the life of the process (the C code also
    reads its site files once); call :func:`reset_site_root` to force
    re-detection, e.g. in tests.

    Returns
    -------
    pathlib.Path
        ``$SLAMA_SITE_ROOT`` if set, else ``/`` if
        :data:`LIVE_MARKER` is a directory, else :data:`MIRROR_ROOT`.
    """
    global _site_root
    if _site_root is None:
        env = os.environ.get(SITE_ROOT_ENV)
        if env:
            _site_root, reason = Path(env), f"from ${SITE_ROOT_ENV}"
        elif LIVE_MARKER.is_dir():
            _site_root, reason = LIVE_ROOT, f"auto: {LIVE_MARKER} found"
        else:
            _site_root, reason = MIRROR_ROOT, f"auto: no {LIVE_MARKER}, using mirror"
        logger.info("site root: %s (%s)", _site_root, reason)
    return _site_root


def reset_site_root() -> None:
    """Forget the cached site root so the next :func:`site_root` re-detects it."""
    global _site_root
    _site_root = None


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
        ``c_path`` re-rooted under :func:`site_root`; unchanged when
        the root is ``/``.

    Raises
    ------
    ValueError
        If ``c_path`` is not absolute.
    """
    if not c_path.startswith("/"):
        raise ValueError(f"site path must be absolute: {c_path!r}")
    return site_root() / c_path.lstrip("/")
