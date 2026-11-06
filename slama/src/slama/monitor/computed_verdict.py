"""Verdict for a compute-engine (``monitorsystem:*``) point.

The compute engine pushes each output's verdict as ``validity`` metadata
(``smax_push_meta``). That metadata is never cleared, so a stopped engine
would leave its last verdict in place indefinitely. The point's own SMAX
timestamp, refreshed by the engine on every tick, gates it: a point older
than ``max_age_s`` reads :attr:`Validity.INVALID_NO_DATA`.

Every consumer of engine verdicts uses :func:`computed_validity`, so the
gate is defined once:

- the web display (:meth:`slama.web.data_bridge.DataBridge._computed_css_class`)
  maps the result to a CSS class;
- the fault system (:meth:`slama.fault.faultsystem.FaultSystem.tick`) uses
  it as each fault node's verdict.
"""
from __future__ import annotations

from slama.monitor.monitorpoint import Validity


def computed_validity(result, raw_validity, now: float,
                      max_age_s: float) -> Validity:
    """Return a computed point's verdict, gated on its SMAX timestamp age.

    Parameters
    ----------
    result : SmaxVarBase or None
        The value pulled from SMAX for the point (an ``SmaxFloat``,
        ``SmaxStr``, ...), whose ``.timestamp`` is a :class:`datetime.datetime`
        holding the engine's last write. ``None`` when the point was never
        pulled or is absent from SMAX.
    raw_validity : str, int or None
        The point's ``validity`` metadata as returned by
        ``smax_pull_meta("validity", name)``: the integer value of a
        :class:`Validity`, usually as a string. ``None`` when missing.
    now : float
        Current time in epoch seconds. Callers pass their own wall clock
        (for example the fault system's injected clock, which ``--as-of``
        sets), never :func:`time.time` directly.
    max_age_s : float
        Oldest acceptable age of the point's timestamp, in seconds. A
        point written in the future (negative age) is fresh.

    Returns
    -------
    Validity
        :attr:`Validity.INVALID_NO_DATA` when ``result`` is ``None``, its
        timestamp is missing, ``now - timestamp > max_age_s``, or
        ``raw_validity`` is missing or not a :class:`Validity` value.
        Otherwise the pushed :class:`Validity`.

    Examples
    --------
    >>> computed_validity(None, "7", now=0.0, max_age_s=6.0)
    <Validity.INVALID_NO_DATA: 1>
    """
    if result is None:
        return Validity.INVALID_NO_DATA
    ts = getattr(result, "timestamp", None)
    if ts is None or now - ts.timestamp() > max_age_s:
        return Validity.INVALID_NO_DATA
    try:
        return Validity(int(raw_validity))
    except (TypeError, ValueError):
        return Validity.INVALID_NO_DATA
