# Curses display styles → SLAMA `Validity`

Status: **adopted (Marc, 2026-10-21)**; the gating question is open. Applies when porting a curses
monitor page (`cursesmonitor/src/*.c`) to a computed `monitorsystem`
point and its `state_validity` / thresholds in `smax.json`.

The rule for converted displays is to show what the C **shows** (see the
arraymonitor trim, #43). How the C shows it is part of that: the curses
pages encode severity in text attributes. This document defines how those
attributes map onto SLAMA's validity levels, so the choice isn't made one
point at a time.

## 1. What the C uses

The SMA wrappers live in `cursesmonitor/src/monitor.c` (lines 1900–2020).
Each one sets attributes, calls ncurses `printw("%s", text)`, and resets
them. The colors are set by `init_pair` at lines 2096–2101.

| Wrapper | Attribute | Color |
|---|---|---|
| `printDisabled` / `setDisabled` | `COLOR_DISABLED` | red |
| `printBright` / `setBright` | `COLOR_EMPHASIS` | yellow |
| `printEnabled` / `setEnabled` | `COLOR_ENABLED` | green |
| `printAlt` / `setAlt` | `COLOR_VARIANT` | magenta (blue on a white background) |
| `printLabel`, `printUnit` | `COLOR_LABEL` | cyan |
| plain `printw` / `addch` | `COLOR_NORMAL` | default |
| `printHighlighted` / `highlight()` | `A_STANDOUT` | reverse video, color unchanged |
| `setFlashing()` | `A_BLINK` | blinking |

Two signals sit outside the text attributes:

- **`Beep(FAULT + ant)`** sounds an audible alarm. In `arrayMonitor.c`
  these fault classes beep: `DRIVE_FAULT`, `LO_FAULT`, `M3_FAULT`,
  `CHOPPER_FAULT`, `DEWAR_WARM`, `SUN_DISTANCE`. Most beeps are gated on
  `isAntennaInArray`.
- **Gating.** Many styles apply only when the antenna is in the project
  (`isAntennaInArray`), online, or not dead. SLAMA ports have not gated on
  this so far: every antenna is checked.

`monoFlag` (no color) and `lowColorFlag` (everything in normal color) are
display options. They don't change meaning.

## 2. Mapping

Apply the first rule that matches.

1. **The condition beeps** → **ERROR**. An audible alarm is the C's
   strongest signal.
2. **Red** (`printDisabled` / `setDisabled`) → **ERROR**.
3. **Yellow** (`printBright` / `setBright`), or **standout** without red →
   **WARNING**.
4. **Green, magenta, cyan or normal** → **GOOD**.
5. **Categorical coloring.** When a `switch` gives *each valid
   alternative* its own color, the colors identify the category, not a
   severity. All valid alternatives are **GOOD**, and only the default /
   bad case follows rules 1–3.
    - Example: the waveplate prints `R` yellow and `L` magenta, and only `?`
     red.
6. **Nothing shown** (the C prints a blank) → **GOOD**, unless a SLAMA
   decision says otherwise (§3, "Deliberate deviations").
7. **Wacko** ranges (physically impossible values, printed `wacko` /
   `wac` / `Wac`) are treated like any other range (Marc, 2026-10-21,
   after consulting the observatory team):
   - **standout = WARNING**, so a wacko range drawn in standout gives
     **WARNING**;
   - a wacko range drawn in red gives **ERROR** (rule 2).
   - The C uses wacko and standout inconsistently, because the code grew
     over many years. So the draw style decides, not the word "wacko".
     `INVALID_HW_BAD` is not used for wacko ranges.
   - Ports from before this decision keep their choice until they are next
     touched: wind speed, hour angle, scan age, dewar `wac`.

Blinking (`setFlashing`) only appears together with red (smoke), so it
adds nothing beyond rule 2.

## 3. Ported indicators checked against the mapping

Ported `arrayMonitor.c` indicators with a `state_validity` map, as of #44.
"Was" is the validity before this check; the last column is the outcome
(Marc, 2026-10-21; details in §4).

| Point | State | C style | Mapping | Was | Outcome |
|---|---|---|---|---|---|
| `drive_status` | `on` | green | GOOD | GOOD | ✓ |
| | `off` | red, beeps (in array) | ERROR | WARNING | deferred: gating |
| | fault, lockout, one mot, EL/AZ LMT, one tac, ESTOP, AZBRAKE | red, beeps | ERROR | ERROR | ✓ |
| `m3_state` | `open` | green | GOOD | GOOD | ✓ |
| | `moving` | yellow | WARNING | WARNING | ✓ |
| | `close` | red, beeps (in array) | ERROR | WARNING | deferred: gating |
| | `close?`, `open?` | red | ERROR | WARNING | deferred: gating |
| | `???`, `-----` | red | ERROR | ERROR | ✓ |
| `deice_status` | `deicing` (`D`) | yellow | WARNING | WARNING | ✓ |
| | `fault` (`F`, printed as a yellow `D`) | yellow | WARNING | ERROR | kept: deviation |
| `hotload_position` | `Sky` | green | GOOD | GOOD | ✓ |
| | `Amb` | magenta (categorical) | GOOD | GOOD | ✓ |
| | `Mov`, `LinLoad` | yellow (+ standout for `mov`) | WARNING | WARNING | ✓ |
| | `NoB` | red | ERROR | INVALID_NO_HW | kept: deviation |
| `waveplate` | `R`, `L` | yellow / magenta (categorical) | GOOD | GOOD | ✓ |
| | `?` | red | ERROR | ERROR (unknown) | ✓ |
| `smoke_alarm` | `SMOKING` | red, blinking, standout | ERROR | ERROR | ✓ |
| | `ignored` | nothing shown | GOOD | WARNING | kept: deviation |
| `tilt_flag` (#42) | `T` | green | GOOD | WARNING | → GOOD (#45) |
| `motor_alarm` (#44) | `Motor` (≥ 50 A) | yellow, standout | WARNING | WARNING | ✓ |
| | `Motor!` (≥ 100 A) | red, standout | ERROR | ERROR | ✓ |
| `azel_flag` (#44) | `I` | standout only, no beep | WARNING | ERROR | → WARNING (#44) |
| | `C` | normal | GOOD | WARNING | → GOOD (#44) |
| `wind_source` | all | no C style (a SLAMA label) | n/a | — | — |

Notes:

1. **`deice_status` fault.** The C draws a deice fault and active deicing
   identically: a yellow `D` (`arrayMonitor.c:1821-1825`). So the C cannot
   tell them apart on this page. SLAMA's ERROR for a fault is more
   informative than the C. Keeping it would be a deliberate deviation;
   matching the C means WARNING.
2. **`drive_status` off and `m3_state` close.** The C beeps on these only
   when the antenna is in the project. Without that gating, ERROR will
   also show for antennas that are parked on purpose. This is the gating
   question from §1, not a mapping question.
3. **`smoke_alarm` ignored** is a recorded deviation (Marc, 2026-10-20):
   the C shows nothing for an ignored antenna, but SLAMA keeps a tripped
   sensor visible.
4. **`hotload_position` NoB.** No optics board is a hardware absence, and
   `INVALID_NO_HW` says that more precisely than ERROR. The C's red is the
   only way curses can express it.
5. **Numeric thresholds** (`warn_*` / `err_*`) are not covered here. They
   come from the C's standout and wacko ranges, and rule 7 picks their
   level.

## 4. Decisions (Marc, 2026-10-21)

- **Follow the mapping:**
  - `tilt_flag` `T` → GOOD (#45);
  - `azel_flag` `C` → GOOD and `I` → WARNING (folded into #44).
- **Deliberate deviations, kept.** Each is recorded in the point's
  `smax.json` description or here.
  - `deice_status` `fault` stays **ERROR**: SLAMA tells a fault apart from
    active deicing, and the C's display cannot.
  - `hotload_position` `NoB` stays **INVALID_NO_HW**: it means a missing
    optics board, which is more precise than the C's red.
  - `smoke_alarm` `ignored` stays **WARNING** (2026-10-20).
- **Deferred until SLAMA decides whether to gate on array membership:**
  - `drive_status` `off` and `m3_state` `close` / `close?` / `open?`;
  - the C's beep and red for these apply mainly to antennas in the
    project;
  - this ties to porting `projects/antennasInArray` (`isAntennaInArray`).
- **New ports:** pick validity with §2, and list any deviation in the PR.
