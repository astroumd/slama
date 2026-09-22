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
# Shared helpers for ported curses-monitor logic
# ---------------------------------------------------------------------------

def _age_s(ts, ctx: ComputeContext) -> float:
    """Seconds since a Unix-time heartbeat value, by the engine's wall clock.

    Many RM points *are* timestamps (``RM_TRACK_TIMESTAMP_L``,
    ``RM_SERVO_TIMESTAMP_L``, ...), written by the antenna computer
    every cycle; their *value* is the freshness signal the curses
    monitor relied on, rather than their SMAX write time.

    Parameters
    ----------
    ts : int or float
        Unix epoch seconds, as stored in the heartbeat point.
    ctx : ComputeContext
        Supplies :attr:`ComputeContext.wall_clock` (never the monotonic
        :attr:`ComputeContext.clock`, whose epoch is arbitrary).

    Returns
    -------
    float
        ``ctx.wall_clock() - ts``. Negative if ``ts`` is in the
        future (clock skew or a garbage value); callers that care
        should compare ``abs()``, as the C code does.
    """
    return ctx.wall_clock() - float(ts)


def _label(code, table: dict, unknown: str = "?") -> str:
    """Look up the display label for an integer status code.

    Parameters
    ----------
    code : int, float, or numpy scalar
        Raw status code from SMAX. Integral floats (e.g. ``3.0``) are
        accepted; anything non-integral or non-numeric is unknown.
    table : dict of int to str
        Code -> label map, ported from the curses source.
    unknown : str, optional
        Label for a code not in ``table``. Default ``"?"``. Output
        points declare ``state_validity`` without this label, so their
        ``unknown_state`` (default ERROR) colours it — no extra
        validity plumbing needed in each function.

    Returns
    -------
    str
        ``table[int(code)]``, or ``unknown``.
    """
    try:
        f = float(code)
    except (TypeError, ValueError):
        return unknown
    if not f.is_integer():
        return unknown
    return table.get(int(f), unknown)


def _array_elem(value, idx: int):
    """Return element ``idx`` of an array-valued SMAX point.

    The compute config has no syntax for indexing into a vector point
    (``..._V16_F``, ``..._V2_S``); entries pass the whole array and name
    the index in ``params`` instead (as :func:`count_true` does with
    ``indices``).

    Parameters
    ----------
    value : numpy.ndarray, list, tuple, or scalar
        The pulled value. A scalar is accepted only for ``idx == 0``
        (a size-1 vector may arrive unwrapped).
    idx : int
        Zero-based index.

    Returns
    -------
    Any
        The element, as a plain Python scalar where possible.

    Raises
    ------
    IndexError
        If ``idx`` is out of range, or nonzero for a scalar ``value``.
    """
    if isinstance(value, (np.ndarray, list, tuple)):
        elem = np.asarray(value).ravel()[idx]
        return elem.item() if hasattr(elem, "item") else elem
    if idx == 0:
        return value
    raise IndexError(f"index {idx} into scalar value {value!r}")


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

    An optional ``ctx.params["indices"]`` -- a list of positions --
    restricts counting, for any array-valued input, to just those
    positions. Needed for e.g. a "V11" SMA bit-vector: index 0 is
    always a placeholder, indices 1-8 are the standard antennas, and
    9/10 are only meaningful when JCMT/CSO are patched into the array
    (a rare, deliberately-configured case). Scalar inputs are
    unaffected -- ``indices`` only ever selects within an array.
    """
    indices = ctx.params.get("indices")
    total = 0
    for r in inputs:
        v = r.value
        if isinstance(v, (np.ndarray, list, tuple)):
            if indices is not None:
                v = [v[i] for i in indices]
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
        Optional ``"track_ts"``: ``RM_TRACK_TIMESTAMP_L``; if present
        and older than :data:`TRACK_STALE_S`, the result is marked
        ``INVALID_NO_DATA`` (``arrayMonitor.c:1915-1920`` only alarms
        while tracking data is fresh).
    ctx : ComputeContext
        Supplies the wall clock for ``"track_ts"``.

    Returns
    -------
    float or tuple of (float, Validity)
        The angular separation in degrees, via
        :func:`slama.coordinates.core.sun_distance`; paired with
        ``INVALID_NO_DATA`` when tracking data is stale.
    """
    sd = float(sun_distance(
        inputs["sunaz"].value, inputs["sunel"].value,
        inputs["antaz"].value, inputs["antel"].value,
    ).to(u.degree).value)
    if "track_ts" in inputs and abs(_age_s(inputs["track_ts"].value, ctx)) > TRACK_STALE_S:
        # arrayMonitor.c:1915-1920 alarms only when trackStatus == 1:
        # with stale tracking data the antenna position is not current.
        return sd, Validity.INVALID_NO_DATA
    return sd


# ---------------------------------------------------------------------------
# arrayMonitor.c port — per-antenna tracking / drive (goals/monsubsys_arrayMonitor.md)
#
# C source: SMA-Software/online/Linux/applications/obscon/cursesmonitor/
# src/arrayMonitor.c. Line numbers below refer to that file.
# ---------------------------------------------------------------------------

TRACK_STALE_S = 3.0
"""``arrayMonitor.c:350-357``: tracking data older than this is stale."""

SERVO_STALE_S = 10.0
"""``arrayMonitor.c:578-587, 1949-1958``: servo heartbeat stale limit."""

CHOPPER_STALE_S = 4.0
"""``arrayMonitor.c:475-477``: chopper monitor heartbeat stale limit."""

DEICE_STALE_S = 300.0
"""``arrayMonitor.c:590-602``: deice heartbeat stale limit."""

TRACKING_ERROR_THRESHOLD_ARCSEC = 1.0
"""``arrayMonitor.c`` ``TRACKING_ERROR_THRESHOLD``: on source below this."""

EMERGENCY_STOP_FAULT = 1 << 21
"""SCB fault-word bit (``global/include/s_cmd2.h:166``)."""

AIR_PRESSURE_SWITCH_FAULT = 1 << 30
"""SCB fault-word bit (``global/include/s_cmd2.h:175``); shown as AZBRAKE."""

DRIVE_STATUS_LABELS = {
    0: "off", 1: "on", 2: "fault", 3: "lockout", 4: "one mot",
    5: "EL LMT", 6: "AZ LMT", 7: "one tac", 8: "ESTOP",
}
"""``arrayMonitor.c`` ``dstat[]`` table, padding stripped."""

DEICED_FAULT = 1 << 31
"""``acc/deiced/include/deiced.h``: deicer fault bit."""

DEICE_CONTACTOR_MASK = 0x2000 | 0x4000
"""``deiced.h`` ``MAIN_CONTACTOR_STATUS_BIT | MAIN_CONTACTOR_BIT``: deicing."""

# RM_CHOPPER_STATUS_BITS_V16_B byte indices (acc/chopperd/include/chopperControl.h)
_CHOP_P20 = 4
_CHOP_POS_ERR_BITS = 5
_CHOP_UPDATE_STATUS = 10


@compute_function("timestamp_age")
def timestamp_age(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> float:
    """Seconds since an RM heartbeat point's value, by the engine's wall clock.

    Ports the staleness idiom used throughout ``arrayMonitor.c``, e.g.
    ``trackStatus`` (350-357, ``|ts - now| > 3``) and the servo check
    (1949-1958, ``> 10``). The age is written rather than a 0/1 flag:
    the output point's own ``warn_*``/``err_*`` thresholds in
    ``smax.json`` turn it into a validity, and the number itself tells
    an operator *how* stale.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"ts"``: a heartbeat point whose value is Unix epoch seconds
        (configure it with ``staleness_s: null`` so a frozen heartbeat
        shows a growing age rather than no data).
    ctx : ComputeContext
        Supplies the wall clock.

    Returns
    -------
    float
        Signed age in seconds; negative means the heartbeat is in the
        future (clock skew or garbage), which the output's ``err_low``
        catches.
    """
    return _age_s(inputs["ts"].value, ctx)


@compute_function("on_source")
def on_source(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> bool:
    """Whether an antenna is on source (``arrayMonitor.c:532-535, 550-551``).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"tracking_error"``: ``RM_TRACKING_ERROR_ARCSEC_F``;
        ``"refraction_flag"``: ``RM_REFRACTION_RADIO_FLAG_B``.
    ctx : ComputeContext
        Unused.

    Returns
    -------
    bool
        ``True`` iff the tracking error is below
        :data:`TRACKING_ERROR_THRESHOLD_ARCSEC` and the radio
        refraction flag is set (the C forces ``onSource = 0`` when the
        flag is 0).
    """
    return (float(inputs["tracking_error"].value) < TRACKING_ERROR_THRESHOLD_ARCSEC
            and int(inputs["refraction_flag"].value) != 0)


@compute_function("drive_status")
def drive_status(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Antenna drive status label (``arrayMonitor.c:461-464, 540-547, 578-587, 1949-1995``).

    Combines, in the C's order of precedence:

    1. Servo heartbeat older than :data:`SERVO_STALE_S` ->
       ``("stale", INVALID_NO_DATA)`` (the C shows "SrvS").
    2. Base code from ``RM_ANTENNA_DRIVE_STATUS_B`` (``d``) and
       ``RM_SERVO_FAULT_STATE_B`` (``f``): ``d`` if ``f == 0 or d == 0``,
       else ``f + 1`` if ``f > 0``. The C leaves the code *unassigned*
       for ``f < 0, d != 0``; this port reports ``"???"`` instead.
    3. When not on source (tracking error >= 1″): encoder elevation at
       or beyond the SCB up/low limits -> 5 (EL LMT), then encoder
       azimuth at or beyond the CW/CCW limits -> 6 (AZ LMT, wins).
    4. SCB fault word :data:`EMERGENCY_STOP_FAULT` bit -> 8 (ESTOP).
    5. Code 0 with :data:`AIR_PRESSURE_SWITCH_FAULT` -> ``"AZBRAKE"``.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"drive"``, ``"fault_state"``, ``"faultword"``, ``"servo_ts"``,
        ``"tracking_error"``, ``"enc_az"``, ``"enc_el"``, ``"up_limit"``,
        ``"low_limit"``, ``"cw_limit"``, ``"ccw_limit"``.
    ctx : ComputeContext
        Supplies the wall clock for the servo heartbeat.

    Returns
    -------
    str or tuple of (str, Validity)
        A label from :data:`DRIVE_STATUS_LABELS`, ``"AZBRAKE"``, or
        ``"???"`` (validity from the output's ``state_validity``), or
        ``("stale", INVALID_NO_DATA)``.
    """
    if abs(_age_s(inputs["servo_ts"].value, ctx)) > SERVO_STALE_S:
        return "stale", Validity.INVALID_NO_DATA

    d = int(inputs["drive"].value)
    f = int(inputs["fault_state"].value)
    if f == 0 or d == 0:
        code = d
    elif f > 0:
        code = f + 1
    else:
        code = None

    if float(inputs["tracking_error"].value) >= TRACKING_ERROR_THRESHOLD_ARCSEC:
        el = float(inputs["enc_el"].value)
        az = float(inputs["enc_az"].value)
        if el >= float(inputs["up_limit"].value) or el <= float(inputs["low_limit"].value):
            code = 5
        if az >= float(inputs["cw_limit"].value) or az <= float(inputs["ccw_limit"].value):
            code = 6

    faultword = int(inputs["faultword"].value) & 0xFFFFFFFF
    if faultword & EMERGENCY_STOP_FAULT:
        code = 8
    if code == 0 and faultword & AIR_PRESSURE_SWITCH_FAULT:
        return "AZBRAKE"
    if code is None:
        return "???"
    return _label(code, DRIVE_STATUS_LABELS, unknown="???")


@compute_function("chopper_status")
def chopper_status(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> dict:
    """Chopper status label and focus-curve flag (``arrayMonitor.c:469-482, 2015-2058``).

    Decodes ``RM_CHOPPER_STATUS_BITS_V16_B`` as the C does: position
    error bits from byte 5 (X=8, Y=4, Z=2, tilt=1), chopping when byte
    4 == 2, focus curve on when byte 10 == 1.

    Labels: ``"stale"`` (heartbeat older than :data:`CHOPPER_STALE_S`),
    ``"OK/FC"`` / ``"OK/NFC"`` (no position errors, not chopping), or
    the C's four-character field, e.g. ``"X--T"``, ``"---C"``
    (chopping).

    Deliberately *not* ported: the C's "focus curve disagrees with the
    array" beep (2041-2043), because line 2053 unconditionally calls
    ``NoBeep`` for the same antenna in the same cycle, so it never
    sounded. The array count is still exposed via ``focus_curve``.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"bits"``: the 16-byte status vector; ``"ts"``:
        ``RM_CHOPPER_MONITOR_TIMESTAMP_L``.
    ctx : ComputeContext
        Supplies the wall clock.

    Returns
    -------
    dict
        ``{"status": (label, Validity), "focus_curve": bool or (bool,
        Validity)}``. Status validity: any position error ->
        ``VALID_ERROR``; ``OK/NFC`` -> ``VALID_WARNING`` (the C
        highlights it); ``OK/FC`` or chopping-only -> ``VALID_GOOD``;
        stale -> ``INVALID_NO_DATA`` for both roles, so a stale
        antenna drops out of the array focus-curve count.
    """
    focus_curve = int(_array_elem(inputs["bits"].value, _CHOP_UPDATE_STATUS)) == 1
    if abs(_age_s(inputs["ts"].value, ctx)) > CHOPPER_STALE_S:
        return {"status": ("stale", Validity.INVALID_NO_DATA),
                "focus_curve": (focus_curve, Validity.INVALID_NO_DATA)}

    pos_err = int(_array_elem(inputs["bits"].value, _CHOP_POS_ERR_BITS)) & 0x0F
    chopping = int(_array_elem(inputs["bits"].value, _CHOP_P20)) == 2

    if pos_err == 0 and not chopping:
        if focus_curve:
            status = ("OK/FC", Validity.VALID_GOOD)
        else:
            status = ("OK/NFC", Validity.VALID_WARNING)
    else:
        label = ("X" if pos_err & 8 else "-") + ("Y" if pos_err & 4 else "-") \
            + ("Z" if pos_err & 2 else "-") \
            + ("C" if chopping else ("T" if pos_err & 1 else "-"))
        status = (label, Validity.VALID_ERROR if pos_err else Validity.VALID_GOOD)
    return {"status": status, "focus_curve": focus_curve}


@compute_function("deice_status")
def deice_status(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> str:
    """Deicer status label (``arrayMonitor.c:590-602``, ``deiceChar``).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"ts"``: ``RM_DEICE_TIMESTAMP_L``; ``"bits"``:
        ``RM_DEICE_STATUS_BITS_L`` (int32; bit 31 read unsigned).
    ctx : ComputeContext
        Supplies the wall clock.

    Returns
    -------
    str
        ``"fault"`` if the heartbeat is older than
        :data:`DEICE_STALE_S` or :data:`DEICED_FAULT` is set (C: 'F');
        ``"deicing"`` if a main-contactor bit is set (C: 'D');
        otherwise ``"ok"``. Validity comes from the output's
        ``state_validity``.
    """
    bits = int(inputs["bits"].value) & 0xFFFFFFFF
    if abs(_age_s(inputs["ts"].value, ctx)) > DEICE_STALE_S or bits & DEICED_FAULT:
        return "fault"
    if bits & DEICE_CONTACTOR_MASK:
        return "deicing"
    return "ok"


@compute_function("clock_offset")
def clock_offset(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> float:
    """Antenna clock offset in seconds (``arrayMonitor.c:2685-2713``).

    The C compares the monitor host's UT against ``RM_UTC_HR_D`` read
    live from reflective memory. Here the reference is the input's SMAX
    **write timestamp** (:attr:`ResolvedInput.timestamp`), not "now":
    the engine reads SMAX up to a tick after the write, and that lag
    would swamp a sub-second offset. Falls back to the wall clock if
    the timestamp is unknown.

    Two C bugs are not ported: ``tm_sec/3600`` integer division (whole
    seconds dropped) and ``timeProblems()`` tested with ``== 1`` so
    the highlight never fired.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"utc_hr"``: ``RM_UTC_HR_D``, UT hours of day on the antenna.
    ctx : ComputeContext
        Supplies the wall clock fallback.

    Returns
    -------
    float
        Reference UT minus antenna UT, in seconds, wrapped to
        [-43200, 43200) so midnight rollover doesn't read as ±24 h.
    """
    ref = inputs["utc_hr"].timestamp
    if ref is None:
        ref = ctx.wall_clock()
    offset = (ref % 86400.0) - float(inputs["utc_hr"].value) * 3600.0
    return (offset + 43200.0) % 86400.0 - 43200.0


# ---------------------------------------------------------------------------
# arrayMonitor.c port — receiver / LO (goals/monsubsys_arrayMonitor.md)
#
# Antenna receiver types (/global/configFiles/rxtype.conf, per Marc
# 2026-09-22): wSMA on 1, 7, 8; old Tune6 receivers on 2-6. The wSMA LO
# lock (wsmaSelection/wsmaIsLocked) is not ported yet, so LO points exist
# only for the Tune6 antennas in computations.json.
# ---------------------------------------------------------------------------

PHASE_LOCK_IS_STALE_S = 90.0
"""``arrayMonitor.c`` ``PHASE_LOCK_IS_STALE``: gunn-lock heartbeat limit."""

HI_LO_FREQ_CUTOFF_HZ = 600.0e9
"""``receiverMonitor.h`` ``HI_LO_FREQ_CUTOFF_GHZ`` in Hz."""

LAKESHORE_STALE_S = 60.0
"""``arrayMonitor.c`` ``LAKESHORE_STALE``: dewar temperature heartbeat limit."""

DEWAR_WACKO_K = 2.0
"""``arrayMonitor.c:2296-2326``: a 4K reading at or below this is not physical."""

SMA_N_CORR_SEGMENTS = 8
"""Correlator chunk count; ``DSM_REQUESTED_CHUNK_V2_S`` is valid in 1..8."""

RX_CODE_LABELS = {"A1": "230", "E": "240", "B1": "345", "C": "400"}
"""``smaglobal.h`` ``RXCODE_*`` -> band label (``arrayMonitor.c:1143-1147``)."""

# RM_TUNE6_COMMAND_BUSY_S codes (global/include/tune6status.h)
TUNE6_BUSY_LABELS = {1: "tuningL", 2: "tuningH", 3: "LO adjL", 4: "LO adjH"}
"""Busy codes that replace the whole LO field (``arrayMonitor.c:2163-2175``)."""
_TUNE6_IV_SWEEP = 6
_TUNE6_IV_SWEEP_HIGH_FREQ = 7
_TUNE6_PB_SWEEP = 8
_TUNE6_PB_SWEEP_HIGH_FREQ = 9
_TUNE6_LINEAR_LOAD = 12
_TUNE6_MAX_CODE = 12

HOTLOAD_LABELS = {1: "Sky", 3: "Sky", 2: "Amb", 4: "Amb", 5: "Mov"}
"""``RM_UNHEATEDLOAD_STATUS_S`` -> label (``printNewHotloadPosition``, 2808-2831)."""


def _tri_state(v) -> str:
    """``printTriState``: 1 -> "1", 0 -> "0", anything else -> "w"."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "w"
    return "1" if f == 1 else ("0" if f == 0 else "w")


def _is_one(v) -> bool:
    """True iff ``v`` is numerically 1 (the C's ``== 1`` lock tests)."""
    try:
        return float(v) == 1
    except (TypeError, ValueError):
        return False


@compute_function("yig_locked")
def yig_locked(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """YIG lock flag (``arrayMonitor.c:486-489``: ``(RM_YIGn_LOCKED_S == 1)``).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"locked"``: ``RM_YIG1_LOCKED_S`` or ``RM_YIG2_LOCKED_S``.
    ctx : ComputeContext
        Unused.

    Returns
    -------
    tuple of (bool, Validity)
        ``(True, VALID_GOOD)`` if locked, else ``(False,
        VALID_WARNING)`` — unlocked is normal for an unused receiver,
        so the band-aware alarm is left to :func:`lo_lock_ok`.
    """
    locked = _is_one(inputs["locked"].value)
    return locked, (Validity.VALID_GOOD if locked else Validity.VALID_WARNING)


@compute_function("lo_status")
def lo_status(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Tune6 LO status field (``arrayMonitor.c:2160-2225``).

    Busy codes 1-4 replace the whole field (``tuningL``, ``tuningH``,
    ``LO adjL``, ``LO adjH``). Otherwise the field is
    ``<left>/<right>``: left is ``IV`` (busy 6), ``PB`` (8), or
    ``gunn1-yig1``; right is ``IV`` (7), ``PB`` (9), or ``gunn2-yig2``,
    each lock shown as ``1``/``0``/``w`` (``printTriState``).

    The C tests ``PB_SWEEP`` (8) on *both* sides and never
    ``PB_SWEEP_HIGH_FREQ`` (9); this port uses 9 on the right, as
    intended. A busy code outside 0..12 (garbage — common in the
    2026-09-22 snapshot) gives ``"?"`` rather than the C's silent
    fall-through.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"busy"``, ``"gunn1"``, ``"gunn2"``, ``"yig1"``, ``"yig2"``.
    ctx : ComputeContext
        Unused.

    Returns
    -------
    tuple of (str, Validity)
        ``VALID_ERROR`` for ``"?"``; ``VALID_WARNING`` while tuning or
        sweeping, or if any lock is not 1; ``VALID_GOOD`` for
        ``"1-1/1-1"``.
    """
    busy_label = _label(inputs["busy"].value, {i: str(i) for i in range(_TUNE6_MAX_CODE + 1)})
    if busy_label == "?":
        return "?", Validity.VALID_ERROR
    busy = int(busy_label)
    if busy in TUNE6_BUSY_LABELS:
        return TUNE6_BUSY_LABELS[busy], Validity.VALID_WARNING

    g1, y1, g2, y2 = (_tri_state(inputs[k].value) for k in ("gunn1", "yig1", "gunn2", "yig2"))
    left = {_TUNE6_IV_SWEEP: "IV", _TUNE6_PB_SWEEP: "PB"}.get(busy, f"{g1}-{y1}")
    right = {_TUNE6_IV_SWEEP_HIGH_FREQ: "IV", _TUNE6_PB_SWEEP_HIGH_FREQ: "PB"}.get(busy, f"{g2}-{y2}")
    label = f"{left}/{right}"
    return label, (Validity.VALID_GOOD if label == "1-1/1-1" else Validity.VALID_WARNING)


@compute_function("lo_lock_ok")
def lo_lock_ok(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Whether the LO is locked for the observing band (``arrayMonitor.c:2152-2158``).

    The C raises ``LO_FAULT`` unless all of gunn1, yig1 and gunn2 are
    locked, or the chain that the rest frequency needs is locked: above
    :data:`HI_LO_FREQ_CUTOFF_HZ`, gunn2 + yig1; below it, gunn1 + yig1.
    The gunn1 lock heartbeat (``RM_GUNN1_LOCKED_TIMESTAMP_L``) older
    than :data:`PHASE_LOCK_IS_STALE_S` is also an error (the C
    highlights it).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"gunn1"``, ``"gunn2"``, ``"yig1"``, ``"gunn1_ts"``, and
        ``"rest_freq"`` (``DSM_REQUESTED_FREQUENCY_V2_D``; element
        ``0``, as the C uses ``restFrequency[0]``).
    ctx : ComputeContext
        Supplies the wall clock.

    Returns
    -------
    tuple of (bool, Validity)
        ``(ok, VALID_GOOD)`` or ``(ok, VALID_ERROR)``; ``VALID_ERROR``
        whenever the heartbeat is stale, regardless of ``ok``.
    """
    g1, g2, y1 = (_is_one(inputs[k].value) for k in ("gunn1", "gunn2", "yig1"))
    rest = float(_array_elem(inputs["rest_freq"].value, 0))
    ok = (g1 and y1 and g2) \
        or (rest > HI_LO_FREQ_CUTOFF_HZ and g2 and y1) \
        or (rest < HI_LO_FREQ_CUTOFF_HZ and g1 and y1)
    stale = _age_s(inputs["gunn1_ts"].value, ctx) > PHASE_LOCK_IS_STALE_S
    return ok, (Validity.VALID_GOOD if ok and not stale else Validity.VALID_ERROR)


@compute_function("hotload_position")
def hotload_position(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> str:
    """Hot/ambient load position label (``printNewHotloadPosition``, 2808-2831; caller 2333-2343).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"status"``: ``RM_UNHEATEDLOAD_STATUS_S``; ``"busy"``:
        ``RM_TUNE6_COMMAND_BUSY_S``; optional ``"optics_board"``:
        ``RM_OPTICS_BOARD_PRESENT_S`` (the C checks it only for
        antennas without a wSMA load).
    ctx : ComputeContext
        Unused.

    Returns
    -------
    str
        ``"NoB"`` if the optics board is absent; ``"LinLoad"`` while
        Tune6 runs a linear-load measurement (C: "mov", renamed so it
        is not a case-only twin of ``"Mov"``); ``"Sky"``, ``"Amb"``,
        ``"Mov"`` from :data:`HOTLOAD_LABELS`; otherwise ``"?"`` (C:
        "Wac"). Validity comes from the output's ``state_validity``.
    """
    if "optics_board" in inputs and _label(inputs["optics_board"].value, {0: "0"}) == "0":
        return "NoB"
    if _label(inputs["busy"].value, {_TUNE6_LINEAR_LOAD: "x"}) == "x":
        return "LinLoad"
    return _label(inputs["status"].value, HOTLOAD_LABELS)


@compute_function("rx_label")
def rx_label(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> str:
    """Receiver band label from an active-receiver code (``arrayMonitor.c:1138-1148``).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"code"``: ``RM_ACTIVE_LOW_RECEIVER_C10`` or
        ``RM_ACTIVE_HIGH_RECEIVER_C10``.
    ctx : ComputeContext
        ``ctx.params["default"]``: label for an unrecognised code
        (the C uses ``"A"`` for the low slot, ``"B"`` for the high).

    Returns
    -------
    str
        ``"230"``, ``"240"``, ``"345"``, ``"400"``, or the default.
    """
    return RX_CODE_LABELS.get(str(inputs["code"].value).strip()[:9], ctx.params["default"])


@compute_function("line_name")
def line_name(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Spectral line label for one receiver slot (``arrayMonitor.c:1181-1201``).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"names"``: ``DSM_AS_IFLO_LINE_NAME_V2_C41``; ``"chunks"``:
        ``DSM_REQUESTED_CHUNK_V2_S``; ``"mrg_locked"``:
        ``MRG_CONTROL_X:YIG_LOCKED_V2_S``. All are 2-element vectors.
    ctx : ComputeContext
        ``ctx.params["index"]``: 0 for the low receiver slot, 1 for
        the high.

    Returns
    -------
    tuple of (str, Validity)
        ``("YIG Unlkd", VALID_WARNING)`` if the MRG YIG is unlocked;
        otherwise the line name (at most 12 characters), falling back
        to ``"sNN"`` for a valid correlator chunk when the name is
        empty or ``"unknown"``, else ``""``; ``VALID_GOOD``.
    """
    idx = int(ctx.params["index"])
    if not _is_one(_array_elem(inputs["mrg_locked"].value, idx)):
        return "YIG Unlkd", Validity.VALID_WARNING
    name = str(_array_elem(inputs["names"].value, idx)).strip()[:12]
    if name in ("", "unknown"):
        chunk = int(_array_elem(inputs["chunks"].value, idx))
        name = f"s{chunk:02d}" if 0 < chunk <= SMA_N_CORR_SEGMENTS else ""
    return name, Validity.VALID_GOOD


@compute_function("dewar_4k_temp")
def dewar_4k_temp(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Dewar 4K-stage temperature (``arrayMonitor.c:508-521, 2295-2326``).

    Two input shapes, one per receiver type:

    * Tune6: ``"temps"`` (``RM_DEWAR_TEMPS_V16_F``) indexed by
      ``ctx.params["sensor"]`` (0-based; ``dewarTemp.conf`` column
      ``ch4`` minus 1), gated by ``"ts"`` (``RM_LAKESHORE_TIMESTAMP_L``)
      against :data:`LAKESHORE_STALE_S`.
    * wSMA: ``"temp"`` (SMAX ``antenna:N:receiver:wsma:cryostat:
      temperatures:4K-plate``); freshness is the engine's own
      ``staleness_s`` on that input, as the C used its SMAX timestamp.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        See above.
    ctx : ComputeContext
        ``params["sensor"]`` for the Tune6 shape; wall clock for ``"ts"``.

    Returns
    -------
    float or tuple of (float, Validity)
        The temperature in K. ``(T, INVALID_NO_DATA)`` if the lakeshore
        heartbeat is stale; ``(T, VALID_ERROR)`` if ``T <=``
        :data:`DEWAR_WACKO_K` (C: "wac"); otherwise bare, so the
        output's ``err_high`` (the ``dewarTemp.conf`` 4K limit) applies.
    """
    if "temps" in inputs:
        t = float(_array_elem(inputs["temps"].value, int(ctx.params["sensor"])))
        if _age_s(inputs["ts"].value, ctx) > LAKESHORE_STALE_S:
            return t, Validity.INVALID_NO_DATA
    else:
        t = float(inputs["temp"].value)
    if t <= DEWAR_WACKO_K:
        return t, Validity.VALID_ERROR
    return t


# ---------------------------------------------------------------------------
# arrayMonitor.c port — weather / array environment (goals/monsubsys_arrayMonitor.md)
#
# All *_METEOROLOGY_X structs live on DSM:colossus and are rewritten every
# cycle even when a station is dead, so their SMAX timestamps say nothing;
# each struct's SERVER_TIMESTAMP_L *value* is the real freshness signal.
# ---------------------------------------------------------------------------

MPH_TO_MPS = 0.44704
"""``weather.h`` ``MPH_TO_METER_PER_SEC``."""

WIND_METER_FROZEN_CUTOFF_MPH = 0.20
"""``arrayMonitor.c``: a wind speed below this means a frozen anemometer."""

WIND_STATION_STALE_S = 1800.0
"""``computeMedianWindspeed()``: stations older than this are excluded."""

WIND_SPEED_WACKO_MPS = 150.0 * MPH_TO_MPS
"""``arrayMonitor.c:1587``: speeds above 150 mph are shown as "wacko"."""

WIND_AVERAGE_STATIONS = ("UH88", "IRTF", "CFHT", "SUBARU")
"""``computeMedianWindspeed()`` station order (VLBA deliberately excluded).

UKIRT is omitted: the telescope has been decommissioned and its weather
station no longer produces data (Marc, 2026-09-22).
"""

WIND_DIRECT_STATIONS = ("CFHT", "SUBARU", "UH88", "VLBA", "IRTF")
"""Stations ``DSM_WIND_SERVER_C7`` can name directly (``arrayMonitor.c:386-417``).

Matched in this order by case-insensitive substring, after ``"SMA"``
(which the C checks first, so ``"SMAaux"`` also counts as SMA). The C's
UKIRT branch (no frozen fallback) is dropped with the decommissioned
station; a server naming UKIRT now gives no wind.
"""

SUNSHINE_CRITERION_C = 4.0
"""``weather.h`` ``SUNSHINE_CRITERION``: solar minus air temperature, degC."""

WEATHER_STALE_S = 1200.0
"""``arrayMonitor.c`` ``STALE_SECONDS``: weather source data age limit."""

GETWEATHER_STALE_S = 720.0
"""``arrayMonitor.c:1526``: ``DSM_GETWEATHER_TIMESTAMP_L`` (weather daemon) limit."""

WEATHER_TIMESTAMP_STATIONS = ("KECK", "CFHT", "SUBARU", "JCMT", "UH88", "VLBA", "IRTF")
"""Non-SMA sources ``DSM_TEMPERATURE_SERVER_C7`` can name (``arrayMonitor.c:1375-1520``)."""

GENSET_ACTIVE_AFTER_S = 120.0
"""``arrayMonitor.c:711-721``: nonzero generator current for this long => active.

The C counts 120 refresh cycles (~1 s each); this port uses elapsed time
so the result doesn't depend on the engine's interval.
"""


def _circular_mean_deg(angles) -> float:
    """Mean direction of ``angles`` (degrees), in [0, 360).

    The C averages wind directions arithmetically, so 350° and 10°
    average to 180°; a vector mean gives the intended 0°.
    """
    rad = np.radians(np.asarray(angles, dtype=float))
    mean = float(np.degrees(np.arctan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360.0)
    # arctan2 of a tiny negative sine gives -1e-15 deg, which % 360 turns
    # into 359.999...; snap that back to 0.
    return 0.0 if mean > 360.0 - 1e-9 else mean


def _station_wind(inputs, name, ctx):
    """``(speed_mph, direction_deg, fresh)`` for one station's ``<name>_*`` inputs."""
    speed = float(inputs[f"{name}_speed"].value)
    direction = float(inputs[f"{name}_dir"].value)
    fresh = abs(_age_s(inputs[f"{name}_ts"].value, ctx)) <= WIND_STATION_STALE_S
    return speed, direction, fresh


@compute_function("wind")
def wind(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> dict:
    """Summit wind speed/direction with frozen-meter fallback (``arrayMonitor.c:372-419, 2715-2783``).

    Source selection follows ``DSM_WIND_SERVER_C7``:

    * contains ``"SMA"``: the SMA station, unless its speed is at or
      below :data:`WIND_METER_FROZEN_CUTOFF_MPH` (frozen) or its
      ``SERVER_TIMESTAMP_L`` is older than :data:`WIND_STATION_STALE_S`
      (not in the C, which had no SMA freshness check here), in which
      case the cross-station average is used instead.
    * names a station in :data:`WIND_DIRECT_STATIONS`: that station,
      falling back to the average when below the cutoff, as in the C.
    * anything else (KECK, JCMT, the decommissioned UKIRT, empty): no
      wind; the C left the variables uninitialised.

    The cross-station average (``computeMedianWindspeed``, despite the
    name a mean) uses :data:`WIND_AVERAGE_STATIONS`, excluding any
    station below the cutoff or with ``SERVER_TIMESTAMP_L`` older than
    :data:`WIND_STATION_STALE_S`.

    Deliberate differences from the C: the direction average is a
    circular mean (:func:`_circular_mean_deg`); speeds are output in
    m/s (SMA reports m/s; the other stations are treated as mph and
    converted, as the C does); a fallback with no valid station is
    no-data rather than 0.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"server"``; ``"SMA_speed"``, ``"SMA_dir"``, ``"SMA_ts"``; and
        ``"<ST>_speed"``, ``"<ST>_dir"``, ``"<ST>_ts"`` for every station
        in :data:`WIND_DIRECT_STATIONS`.
    ctx : ComputeContext
        Supplies the wall clock.

    Returns
    -------
    dict
        Roles ``"speed"`` (m/s), ``"direction"`` (deg), ``"source"``
        (``"SMA"``, a station name, ``"average"``, or ``"none"``) and
        ``"invalid_stations"`` (count excluded from the average).
    """
    valid, invalid = [], 0
    for st in WIND_AVERAGE_STATIONS:
        speed, direction, fresh = _station_wind(inputs, st, ctx)
        if speed < WIND_METER_FROZEN_CUTOFF_MPH or not fresh:
            invalid += 1
        else:
            valid.append((speed * MPH_TO_MPS, direction))

    def average():
        if not valid:
            return None, None, "none"
        return (float(np.mean([s for s, _ in valid])),
                _circular_mean_deg([d for _, d in valid]), "average")

    server = str(inputs["server"].value).upper()
    if "SMA" in server:
        speed_mps = float(inputs["SMA_speed"].value)
        sma_fresh = abs(_age_s(inputs["SMA_ts"].value, ctx)) <= WIND_STATION_STALE_S
        if sma_fresh and speed_mps / MPH_TO_MPS > WIND_METER_FROZEN_CUTOFF_MPH:
            speed, direction, source = speed_mps, float(inputs["SMA_dir"].value), "SMA"
        else:
            speed, direction, source = average()
    else:
        station = next((st for st in WIND_DIRECT_STATIONS if st in server), None)
        if station is None:
            speed, direction, source = None, None, "none"
        else:
            mph, direction, _ = _station_wind(inputs, station, ctx)
            speed, source = mph * MPH_TO_MPS, station
            if mph < WIND_METER_FROZEN_CUTOFF_MPH:
                speed, direction, source = average()

    if speed is None:
        return {"speed": (None, Validity.INVALID_NO_DATA),
                "direction": (None, Validity.INVALID_NO_DATA),
                "source": ("none", Validity.VALID_ERROR),
                "invalid_stations": invalid}
    speed_out = (speed, Validity.VALID_ERROR) if not 0 <= speed <= WIND_SPEED_WACKO_MPS else speed
    dir_out = (direction, Validity.VALID_ERROR) if not -99 < direction <= 400 else direction
    return {"speed": speed_out, "direction": dir_out, "source": source,
            "invalid_stations": invalid}


@compute_function("sun_visible")
def sun_visible(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> bool:
    """Sunshine indicator (``arrayMonitor.c:770-778``).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"solar_temp"`` and ``"air_temp"``: ``SMA_METEOROLOGY_X``
        ``SOLAR_TEMP_F`` and ``TEMP_F`` (degC).
    ctx : ComputeContext
        Unused.

    Returns
    -------
    bool
        True if the solar sensor reads more than
        :data:`SUNSHINE_CRITERION_C` above the air temperature.
    """
    return float(inputs["solar_temp"].value) - float(inputs["air_temp"].value) > SUNSHINE_CRITERION_C


def _server_is(server: str, name: str) -> bool:
    """The C's ``present()``: a case-sensitive substring test."""
    return name in server


@compute_function("weather_server_label")
def weather_server_label(inputs: dict[str, ResolvedInput], ctx: ComputeContext) -> str:
    """Summarise the four weather-source servers (``printWeatherServer``, 2555-2598).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"temperature"``, ``"humidity"``, ``"wind"``, ``"pressure"``:
        the ``DSM_*_SERVER_C7`` strings.
    ctx : ComputeContext
        Unused.

    Returns
    -------
    str
        First matching rule: all identical -> first 5 characters; all
        contain SMA -> ``"SMA"``; each contains one of a pair ->
        ``"SM/JC"``, ``"JC/SU"``, ``"SM/SU"``, ``"SM/CF"``, ``"JC/CF"``;
        else ``"mix"``.
    """
    servers = [str(inputs[k].value) for k in ("temperature", "humidity", "wind", "pressure")]
    if all(s == servers[0] for s in servers):
        return servers[0][:5].strip()
    for label, names in (("SMA", ("SMA",)), ("SM/JC", ("SMA", "JCMT")),
                         ("JC/SU", ("Subaru", "JCMT")), ("SM/SU", ("Subaru", "SMA")),
                         ("SM/CF", ("CFHT", "SMA")), ("JC/CF", ("CFHT", "JCMT"))):
        if all(any(_server_is(s, n) for n in names) for s in servers):
            return label
    return "mix"


@compute_function("weather_data_age")
def weather_data_age(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Age of the temperature source's data (``arrayMonitor.c:1352-1543``).

    Resolves the source like the C: manual weather
    (``DSM_MANUAL_WEATHER_FLAG_S == 1``) uses that flag's own write
    time; otherwise ``DSM_TEMPERATURE_SERVER_C7`` picks the SMA struct
    or a station in :data:`WEATHER_TIMESTAMP_STATIONS`, whose
    ``SERVER_TIMESTAMP_L`` is used. ``"SMAaux"`` would need
    ``RM_AUX_WEATHER_TIMESTAMP_L`` on acc6, which is neither in SMAX nor
    declared, so it resolves to no data. Only the temperature source
    matters: the C resolves all four but tests only this one.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"server"``, ``"manual"``, ``"getweather_ts"``, ``"SMA_ts"``,
        and ``"<ST>_ts"`` for every station in
        :data:`WEATHER_TIMESTAMP_STATIONS`.
    ctx : ComputeContext
        Supplies the wall clock.

    Returns
    -------
    float or tuple of (float, Validity)
        Age in seconds; the output's ``err_high`` applies
        :data:`WEATHER_STALE_S`. ``(age, VALID_ERROR)`` if the weather
        daemon heartbeat is older than :data:`GETWEATHER_STALE_S` (C:
        "d.stl"); ``(None, INVALID_NO_DATA)`` if the source can't be
        resolved.
    """
    manual = _is_one(inputs["manual"].value)
    if manual:
        ts = inputs["manual"].timestamp
    else:
        server = str(inputs["server"].value)
        if "SMAaux" in server:
            ts = None
        elif "SMA" in server:
            ts = inputs["SMA_ts"].value
        else:
            st = next((s for s in WEATHER_TIMESTAMP_STATIONS if s in server.upper()), None)
            ts = inputs[f"{st}_ts"].value if st else None
    if ts is None:
        return None, Validity.INVALID_NO_DATA
    age = _age_s(ts, ctx)
    if not manual and _age_s(inputs["getweather_ts"].value, ctx) > GETWEATHER_STALE_S:
        return age, Validity.VALID_ERROR
    return age


@compute_function("genset_active")
def genset_active(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Backup generator running (``arrayMonitor.c:711-721``, with hysteresis).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"l1"``, ``"l2"``, ``"l3"``: ``DSM_IWATCH_DATA_X``
        ``CURRENTL{1,2,3}_F``.
    ctx : ComputeContext
        ``ctx.state["nonzero_since"]`` holds the monotonic ``ctx.clock``
        time the current run of nonzero readings began.

    Returns
    -------
    tuple of (bool, Validity)
        ``(True, VALID_WARNING)`` once any phase current has been
        nonzero for more than :data:`GENSET_ACTIVE_AFTER_S`; otherwise
        ``(False, VALID_GOOD)``.
    """
    now = ctx.clock()
    if any(float(inputs[k].value) != 0.0 for k in ("l1", "l2", "l3")):
        since = ctx.state.setdefault("nonzero_since", now)
        active = now - since > GENSET_ACTIVE_AFTER_S
    else:
        ctx.state.pop("nonzero_since", None)
        active = False
    return active, (Validity.VALID_WARNING if active else Validity.VALID_GOOD)


def _ut_stale(hours: float, margin: float, ut_hours: float) -> bool:
    """Port of ``computeUTstale()`` (``arrayMonitor.c:2600-2608``).

    ``hours`` is the measurement time as UT hours of day; it is stale if
    older than ``ut_hours - margin``, with the C's handling of the
    window crossing midnight.
    """
    lo = ut_hours - margin
    if lo < 0:
        if hours < ut_hours + 0.01:
            return False
        lo += 24
    return hours < lo


@compute_function("tau_stale")
def tau_stale(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Whether a CSO/tipper tau measurement is stale (``arrayMonitor.c:1603-1609``).

    ``DSM_CSO_*_TAU_TSTAMP_L`` is *minutes of the UT day*, not a Unix
    time. The C compares it against ``RM_UTC_HOURS_F`` of a reference
    antenna; this port uses the engine's wall-clock UT, which is the
    same quantity without depending on an antenna being up.

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"tstamp"``: the measurement's minute of the UT day.
    ctx : ComputeContext
        ``ctx.params["margin_h"]``: 1.0 for 225 GHz, 0.5 for 350 um.

    Returns
    -------
    tuple of (bool, Validity)
        ``(True, VALID_WARNING)`` if stale, else ``(False, VALID_GOOD)``.
    """
    ut_hours = (ctx.wall_clock() % 86400.0) / 3600.0
    stale = _ut_stale(float(inputs["tstamp"].value) / 60.0, float(ctx.params["margin_h"]), ut_hours)
    return stale, (Validity.VALID_WARNING if stale else Validity.VALID_GOOD)


def _standout_tau(freq_hz: float) -> float:
    """``STANDOUT_TAU()`` (``arrayMonitor.c:2785-2790``): tau above which to highlight."""
    if freq_hz < 300e9:
        return 0.40
    if freq_hz < 600e9:
        return 0.20
    return 0.10


@compute_function("tau_standout")
def tau_standout(inputs: dict[str, ResolvedInput], ctx: ComputeContext):
    """Tau with a frequency-dependent highlight (``arrayMonitor.c:1611-1655``).

    Parameters
    ----------
    inputs : dict of str to ResolvedInput
        ``"tau"``; ``"rest_freq"``: ``DSM_REQUESTED_FREQUENCY_V2_D``
        (element 0, as the C uses ``restFrequency[0]``).
    ctx : ComputeContext
        Unused.

    Returns
    -------
    tuple of (float, Validity)
        ``VALID_ERROR`` if tau is outside [0, 9.99] (C: "wack");
        ``VALID_WARNING`` above :func:`_standout_tau` for the observing
        frequency; else ``VALID_GOOD``. (The C tested the CSO tau even
        when showing GFS; this port tests the value it reports.)
    """
    tau = float(inputs["tau"].value)
    if not 0.0 <= tau <= 9.99:
        return tau, Validity.VALID_ERROR
    limit = _standout_tau(float(_array_elem(inputs["rest_freq"].value, 0)))
    return tau, (Validity.VALID_WARNING if tau > limit else Validity.VALID_GOOD)
