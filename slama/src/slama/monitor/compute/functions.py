"""Registry of compute functions, plus the built-in vocabulary.

A compute function has the uniform signature::

    f(inputs, ctx) -> value
    f(inputs, ctx) -> (value, Validity)
    f(inputs, ctx) -> {role: value, ...}
    f(inputs, ctx) -> {role: (value, Validity), ...}

``inputs`` is a ``list[ResolvedInput]`` (list-form config entry) or
``dict[str, ResolvedInput]`` (dict-form entry); the engine has already
applied the node's staleness/invalid-input policy, so a function only
ever sees inputs it should actually use (never called on an empty
input set — see
:meth:`slama.monitor.compute.engine.ComputeEngine._resolve_inputs`).

Returning a bare ``value`` lets the engine derive validity from the
*output* point's own declared thresholds in ``smax.json`` (the common
case — reuses :attr:`MonitorPoint.validity` exactly as any ordinary
point would). Returning ``(value, Validity)`` lets a function assert
validity directly, needed when the function's entire job *is* the
validity computation (``worst_validity``, ``sequence_validity``).

The two dict-returning shapes are for a **multi-output** entry (design
doc §8, config ``"output"`` is a dict of role name -> canonical name):
the function returns a dict keyed by those same role names, each value
either bare or a ``(value, Validity)`` tuple, mixed as needed per role.
The returned dict's keys must exactly match the entry's declared roles
— a mismatch fails that node for the tick (see
:meth:`slama.monitor.compute.engine.ComputeEngine._evaluate_node`).
Role names are function-local, not canonical names, which is what lets
one multi-output function stay reusable under ``__each__`` expansion
(e.g. ``min_max_value`` below, called once per antenna with the same
``{"min": ..., "max": ...}`` shape every time).

Per the design doc's one hard rule for Design A: **no logic in JSON**.
Anything beyond input wiring and a policy flag belongs here as a
registered, unit-testable Python function — not as config.
"""
from __future__ import annotations

import statistics
from typing import Callable

import astropy.units as u
import numpy as np
from slama.monitor.monitorpoint import Validity
from slama.coordinates import sun_distance

from .computenode import ComputeContext, ResolvedInput


FUNCTION_REGISTRY: dict[str, Callable] = {}
"""dict: config ``function`` name -> callable. Populated by
:func:`compute_function`; looked up by
:meth:`slama.monitor.compute.computeconfig.ComputeConfig.from_dict` at
load time (unknown names fail config loading, not a tick) and by
:class:`slama.monitor.compute.engine.ComputeEngine` at tick time.
"""


def compute_function(name: str) -> Callable:
    """Decorator registering a function under ``name`` in :data:`FUNCTION_REGISTRY`.

    Parameters
    ----------
    name : str
        The ``function`` value used to reference this callable from
        ``computations.json``.

    Raises
    ------
    ValueError
        If ``name`` is already registered.
    """
    def deco(fn: Callable) -> Callable:
        if name in FUNCTION_REGISTRY:
            raise ValueError(f"duplicate compute function name {name!r}")
        FUNCTION_REGISTRY[name] = fn
        return fn
    return deco


def get_function(name: str) -> Callable:
    """Look up a registered compute function by name.

    Raises
    ------
    ValueError
        If ``name`` is not registered.
    """
    try:
        return FUNCTION_REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"unknown compute function {name!r}; known: {sorted(FUNCTION_REGISTRY)}"
        )


# ---------------------------------------------------------------------------
# Severity ordering for worst_validity
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: tuple[Validity, ...] = (
    Validity.INVALID_NO_DATA,
    Validity.INVALID_HW_BAD,
    Validity.INVALID_NO_HW,
    Validity.VALID_ERROR_HIGH,
    Validity.VALID_ERROR_LOW,
    Validity.VALID_ERROR,
    Validity.VALID_WARNING_HIGH,
    Validity.VALID_WARNING_LOW,
    Validity.VALID_WARNING,
    Validity.VALID_NOT_CHECKED,
    Validity.VALID,
    Validity.VALID_GOOD,
)
"""Most-severe-first ranking used by :func:`worst_validity`.

``Validity`` is an ``IntEnum`` whose member values are declaration
order, not severity — ``INVALID_NO_DATA`` (arguably the worst outcome:
no data at all) has the *lowest* int value, below ``VALID_GOOD``. A
naive ``max()`` over ``Validity`` members would therefore pick
``VALID_ERROR_HIGH`` over ``INVALID_NO_DATA``, which is backwards for
a "worst status of my children" rollup. This table is the explicit,
local severity order that fixes that; it is not used anywhere outside
this module.
"""

_SEVERITY_RANK: dict[Validity, int] = {v: i for i, v in enumerate(_SEVERITY_ORDER)}


def _severity_score(v: Validity) -> int:
    """0 (``VALID_GOOD``) .. len(_SEVERITY_ORDER)-1 (``INVALID_NO_DATA``): higher is worse.

    Deliberately *not* ``int(v)`` — ``Validity``'s own ordinal is
    declaration order, not severity (see :data:`_SEVERITY_ORDER`), so
    writing the raw ordinal as a status point's value would scramble
    any later numeric comparison or ``err_high``/``warn_high``
    threshold placed on that point.
    """
    rank = _SEVERITY_RANK.get(v, 0)  # unranked -> most severe -> highest score
    return len(_SEVERITY_ORDER) - 1 - rank


@compute_function("worst_validity")
def worst_validity(inputs: list[ResolvedInput], ctx: ComputeContext):
    """Value and validity are both the most-severe validity among ``inputs``.

    Ties (e.g. two inputs both ``VALID_ERROR``) resolve to that shared
    validity. The numeric value written is :func:`_severity_score` —
    0 for ``VALID_GOOD``, increasing with severity — so a threshold
    like ``err_high: 9`` on the output point means something stable,
    unlike the raw (non-severity-ordered) ``Validity`` ordinal would.
    """
    worst = min(inputs, key=lambda r: _SEVERITY_RANK.get(r.validity, -1)).validity
    return _severity_score(worst), worst


@compute_function("count_true")
def count_true(inputs: list[ResolvedInput], ctx: ComputeContext) -> int:
    """Count truthy elements across ``inputs``.

    Each input's value is usually a scalar (one boolean point per
    antenna, e.g. a hypothetical ``antenna:1-8:is_online``), but a
    single input may instead resolve to an array -- the real,
    already-deployed case being
    ``DSM:hal9000:DSM_ONLINE_ANTENNAS_V11_B``, a size-11 ``int8``
    bit-vector point tracking which antennas are online (the
    per-antenna ``is_online`` points are schema-only and never
    actually written by the live system). Array-valued inputs are
    summed element-wise rather than tested with a bare ``if r.value``,
    which raises ``ValueError`` ("truth value of an array with more
    than one element is ambiguous") for any multi-element array.
    """
    total = 0
    for r in inputs:
        v = r.value
        if isinstance(v, np.ndarray):
            total += int(np.count_nonzero(v))
        elif isinstance(v, (list, tuple)):
            total += sum(1 for x in v if x)
        else:
            total += 1 if v else 0
    return total


@compute_function("count_valid")
def count_valid(inputs: list[ResolvedInput], ctx: ComputeContext) -> int:
    """Count inputs whose effective validity is not an ``INVALID_*`` state."""
    invalid = {Validity.INVALID_NO_DATA, Validity.INVALID_NO_HW, Validity.INVALID_HW_BAD}
    return sum(1 for r in inputs if r.validity not in invalid)


@compute_function("min_value")
def min_value(inputs: list[ResolvedInput], ctx: ComputeContext) -> float:
    return min(float(r.value) for r in inputs)


@compute_function("max_value")
def max_value(inputs: list[ResolvedInput], ctx: ComputeContext) -> float:
    return max(float(r.value) for r in inputs)


@compute_function("mean_value")
def mean_value(inputs: list[ResolvedInput], ctx: ComputeContext) -> float:
    return statistics.mean(float(r.value) for r in inputs)


@compute_function("median_value")
def median_value(inputs: list[ResolvedInput], ctx: ComputeContext) -> float:
    return statistics.median(float(r.value) for r in inputs)


@compute_function("min_max_value")
def min_max_value(inputs: list[ResolvedInput], ctx: ComputeContext) -> dict[str, float]:
    """Min and max over the same input set, in one pass (design doc §8).

    A multi-output entry pairs this with ``"output": {"min": ...,
    "max": ...}``; the two role names here (``"min"``/``"max"``) must
    match those config keys exactly. Written as one function rather
    than reusing :func:`min_value`/:func:`max_value` from two separate
    config entries specifically to avoid iterating (and re-resolving)
    the same input set twice per tick.
    """
    values = [float(r.value) for r in inputs]
    return {"min": min(values), "max": max(values)}


@compute_function("sequence_validity")
def sequence_validity(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Trajectory check for a state-machine string point (design doc §3.5).

    Classification (which states mean GOOD/WARNING/ERROR) is the
    source point's own ``state_validity`` map, applied by
    :attr:`MonitorPoint.validity` — this function only adds the
    time/order-aware layer on top: a state that has read as
    ``VALID_WARNING`` for longer than ``ctx.params["stuck_timeout_s"]``
    is escalated to ``VALID_ERROR``.

    Parameters
    ----------
    inputs : dict
        Must contain a ``"state"`` key (the tuning-state-like point).
    ctx : ComputeContext
        ``ctx.params["stuck_timeout_s"]`` (seconds) is required.
        ``ctx.state`` persists ``last_state``/``entered_t`` across
        ticks.
    """
    state_input = inputs["state"]
    state = state_input.value
    now = ctx.clock()
    if state != ctx.state.get("last_state"):
        ctx.state["last_state"] = state
        ctx.state["entered_t"] = now

    validity = state_input.validity
    stuck_timeout_s = ctx.params["stuck_timeout_s"]
    if validity == Validity.VALID_WARNING and (now - ctx.state["entered_t"]) > stuck_timeout_s:
        validity = Validity.VALID_ERROR
    return state, validity


@compute_function("sun_distance")
def sun_distance_degrees(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> float:
    """Angular distance in degrees from one antenna's pointing to the Sun.

    One antenna per call -- paired with a ``__each__``-expanded entry
    per antenna (design doc §3.6/§8's discussion of ``__each__``),
    rather than a single multi-output entry, so there is no positional
    slicing/ordering to get wrong between antennas.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        Must contain ``"sunaz"``, ``"sunel"`` (the Sun's azimuth/
        elevation as seen from this antenna) and ``"antaz"``,
        ``"antel"`` (this antenna's actual pointing), all in degrees.
    ctx : ComputeContext
        Unused by this function.

    Returns
    -------
    float
        The angular separation in degrees, via
        :func:`slama.coordinates.core.sun_distance`.
    """
    sd = sun_distance(
        inputs["sunaz"].value, inputs["sunel"].value,
        inputs["antaz"].value, inputs["antel"].value,
    )
    return float(sd.to(u.degree).value)
