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
