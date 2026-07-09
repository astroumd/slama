# Recovering Validity Thresholds from cursesmonitor "wacko" Bounds

`cursesmonitor` (the legacy curses-based observatory display) marks a cell
`wacko` whenever a freshly-read value falls outside a hardcoded sanity range —
almost always coded as a `#define WACKO_<THING>_MIN/MAX` pair checked
immediately after an `rm_read()` / `dsm_structure_get_element()` call, e.g.:

```c
#define WACKO_TEMP_MIN -20
#define WACKO_TEMP_MAX  25
...
if (floatvalue[i] > WACKO_TEMP_MAX || floatvalue[i] < WACKO_TEMP_MIN || floatvalue[i] != floatvalue[i]) {
    printDisabled("  wacko  ");
}
```

The literal string `"wacko"` appears 500+ times across `cursesmonitor/src`
(mostly repeated per-antenna/per-site loops reusing the same constant), but
the underlying **named bound constants number only ~19**. Those are a real,
grounded source of `err_low`/`err_high` sanity thresholds for `smax.json`
entries that currently have `smax_type` but no thresholds at all.

**None of the fields below currently have `warn_low`/`warn_high`/`err_low`/`err_high`
in `conf/smax.json`** (verified by inspection). `wacko` bounds are sanity
limits ("this reading is physically impossible / sensor garbage"), so they
map to **`err_low`/`err_high`**, not `warn_low`/`warn_high` — cursesmonitor
has no separate warning tier for these checks, it just blanks the cell.

No changes have been made to `smax.json` in this pass — proposals only.

---

## RM_* fields (direct `rm_read()` name — high confidence)

| Source (file:line) | Bound | Field read via `rm_read()` | Proposed smax.json target | Confidence |
|---|---|---|---|---|
| `tiltpage.c:2-3,237` | ±1500 | `RM_TILT1_LO_XELEV_TEMPERATURE_F` | `RM:<idx>:RM_TILT1_LO_XELEV_TEMPERATURE_F` — `err_low: -1500, err_high: 1500` | HIGH |
| `opTel.c:76-77,84` | -1 to 102 | `RM_CELESTRON_HUMIDITY_F` | `RM:<idx>:RM_CELESTRON_HUMIDITY_F` — `err_low: -1, err_high: 102` | HIGH |
| `opTel.c:107-109` | -50 to 100 | `RM_CELESTRON_TEMPERATURE_F` | `RM:<idx>:RM_CELESTRON_TEMPERATURE_F` — `err_low: -50, err_high: 100` | HIGH |
| `opTel.c:129-137` | 0.0001 to 500 | `RM_CELESTRON_FOCUS_MILS_F` | `RM:<idx>:RM_CELESTRON_FOCUS_MILS_F` — `err_low: 0.0001, err_high: 500` | HIGH |
| `opticsPage.c:23-24,379,414,439` | 0 to 150000 | `RM_WIRE_GRID_ENCODER_POSITION_L`, `RM_WIRE_GRID_TABLE_V8_L` | `RM:<idx>:RM_WIRE_GRID_ENCODER_POSITION_L` / `RM_WIRE_GRID_TABLE_V8_L` — `err_low: 0, err_high: 150000` | HIGH |
| `opticsPage.c:909-911,919` | 0 to 1024 | vane encoder (`ivalue`/`i2`, near `RM_TUNE6`-family reads — exact field name not confirmed in this pass) | likely `RM:<idx>:RM_TUNE6_VANE_*` — needs Marc to confirm exact field | MEDIUM |
| `receiverMonitor.c:38-39,986` | -150 to 25 dBm | `RM_GUNN1_REQUESTED_RFPOWER_DBM_F` / `RM_GUNN2_REQUESTED_RFPOWER_DBM_F` | `RM:<idx>:RM_GUNN{1,2}_REQUESTED_RFPOWER_DBM_F` — `err_low: -150, err_high: 25` | HIGH |
| `antMonitor.c:1036-1037,1055,1073,1179` | ±200000 counts | chopper X/Y/Z/tilt position (`posMm[]` × counts-per-mm) — sourced from an `rm_read()` call earlier in the function; exact RM field name not resolved in this pass | `RM:<idx>:RM_*CHOPPER*` (needs field-name confirmation) | LOW |
| `antMonitor.c:990` (`WACKO_OFFSET`) | ±129600 (36°) | `*eloff` (elevation offset) | needs field-name confirmation — likely a pointing/tracking offset field | LOW |

## DSM:colossus:*_METEOROLOGY_X fields (per-site weather — high confidence)

`weather.c` applies the **same four bound families** to all 9 sites (SMA,
JCMT, Subaru, UKIRT, CFHT, UH88, IRTF, VLBA, Keck) via
`dsm_structure_get_element(&<site>Weather, "<FIELD>", ...)`. All target
fields already exist in `smax.json` under `DSM:colossus:<SITE>_METEOROLOGY_X`
(confirmed: `HUMIDITY_F`, `MBAR_F`, `TEMP_F`, `WINDDIR_F`, `WINDSPEED_F` all
present, all lacking thresholds).

| Bound constant | Range | Field | Proposed `err_low`/`err_high` | Confidence |
|---|---|---|---|---|
| `WACKO_TEMP_MIN/MAX` (`weather.h:19-20`) | -20 to 25 °C | `TEMP_F` | -20 / 25 | HIGH |
| `WACKO_HUMIDITY_MIN/MAX` (`weather.h:11-12`) | 0 to 110 % | `HUMIDITY_F` | 0 / 110 | HIGH |
| `WACKO_MBAR_MIN/MAX` (`weather.h:21-22`) | 500 to 700 mbar | `MBAR_F` | 500 / 700 | HIGH |
| `WACKO_WINDSPEED_MIN/MAX` (`weather.h:13-14`) | -9 to 150 mph | `WINDSPEED_F` | -9 / 150 | HIGH — note: mph, but smax.json doesn't record units on this field; confirm unit before applying |
| `WACKO_WINDDIR_MIN/MAX` (`weather.h:7-8`) | -99 to 400 ° | `WINDDIR_F` | -99 / 400 | HIGH — defined but check applied inconsistently in `weather.c` (grep shows the constant used at the site-loop level, not always paired with an explicit `if`); confirm before applying |
| `WACKO_TIMESTAMP_MIN/MAX` (`weather.c:459-460`) | 1,040,000,000–2,040,000,000 (Unix epoch, ~2002–2034) | `SERVER_TIMESTAMP_L` | -- | MEDIUM — this is a staleness/sanity check on the *timestamp*, not the reading; doesn't map to `err_low`/`err_high` on a physical quantity the same way. Could inform a separate "data age" validity check instead. |

Applies to: `DSM:colossus:SMA_METEOROLOGY_X`, `JCMT_METEOROLOGY_X`,
`SUBARU_METEOROLOGY_X`, `UKIRT_METEOROLOGY_X`, `CFHT_METEOROLOGY_X`,
`UH88_METEOROLOGY_X`, `IRTF_METEOROLOGY_X`, `VLBA_METEOROLOGY_X`,
`KECK_METEOROLOGY_X` — 9 sites × up to 5 fields each = up to 45 threshold
additions from this one table.

## Other DSM:* fields

| Source | Bound | Field | Proposed target | Confidence |
|---|---|---|---|---|
| `deicemon.c:205,220,232` | > 100 °C (one-sided) | `ant5Temps[i]` | `DSM:hal9000:DSM_ANTENNA5_TEMPS_X:ANTENNA_THERMOMETERS_V20_F` (and the sibling `ANTENNA_SURFACE_MINMAX_TEMPS_V24_F`) — `err_high: 100` (no lower bound checked in source) | HIGH — reuses the `deice.json` mapping already confirmed in `dsm_placeholder_review.md` |
| `monitor.h:13`, `hangarPage.c:81`, `arrayMonitor.c:808,1745`, `projectpage.c:65` | 0 to 10,000,000 (one-sided upper; lower bound is `< 0`) | `projectID` | `DSM:hal9000:DSM_AS_PROJECT_ID_L` (and `DSM:oldhal:...` sibling) — `err_low: 0, err_high: 10000000` | HIGH — reuses the mapping already confirmed in `dsm_placeholder_review.md` |
| `arrayMonitor.c:764,789` | > 100000 (one-sided) | `*polarDut` (DUT1, read from `/global/polar/ser7.dat`, not SMAX) | Not applicable to `smax.json` — this value comes from a flat file, not DSM/SMAX. Confirms the earlier `dsm_placeholder_review.md` finding that `DSM_DUT` has **NO MATCH** because DUT1 isn't tracked in SMAX at all. | N/A |
| `arrayMonitor.c:1107,1134` | 1.0e6 to 3.0e12 Hz | `restFrequency[rx]` (rest frequency per receiver) | Needs field-name confirmation — likely `antenna:{ant}:receiver:{rx}:rest_frequency` or similar; not one of the DSM placeholder fields reviewed earlier | MEDIUM |

## receiverMonitor.c: printInvalidFloat()/printInvalidDouble() bounds (hardcoded per call site)

These don't use a `#define WACKO_*` constant, which is why the first pass
missed them — the bound is instead passed as a literal `min`/`max`
**function argument** at each call site:

```c
static int printInvalidFloat(int ant, float_value *point, double min, double max) {
  ...
  else if(point->value < min || point->value > max) printWacko();
}
...
else if(!printInvalidFloat(ant, &r->bias, -1.0, 10.0)) { ... }
```

The bound is just as static as a `#define` — only the packaging differs.
`receiverMonitor.c` has **two parallel data paths per field**, selected by
receiver type: WSMA receivers read straight from SMAX via `readSmaxFloat()`
(canonical name built from `"antenna:%d:receiver:%c:lo_plate:mixer:%d..."`),
legacy Gunn-oscillator receivers read via `rmRead()`. Both paths funnel into
the same `printInvalidFloat()` call and bound, so each row below can produce
up to two threshold proposals.

| Label (line) | Bound | WSMA path (SMAX) | Legacy/Gunn path (RM) | Confidence |
|---|---|---|---|---|
| LO Freq (`687`) | 50.0–600.0 GHz | — (Gunn-only field) | `RM_LAST_GUNN_FREQ_V8_D` — `err_low: 50.0, err_high: 600.0` | HIGH |
| Gunn V (`805`) | -1.0–10.0 | C code reads `antenna:{ant}:receiver:{H\|L}:lo_plate:mixer:{n}:bias` — **verified missing at that exact path for both polarizations.** The nearest real field is `H:mixer:1:bias` (`smax.json:8801`, one level up, no `lo_plate:` prefix) — needs Marc to confirm whether the code's path is stale or the schema needs a `bias` alias under `lo_plate:mixer`. `L` has no `bias`-named field at all (see schema-mismatch section) | `RM_GUNN_BIAS_F` / `RM_GUNN2_BIAS_F` — `err_low: -1.0, err_high: 10.0` | HIGH (RM side only) |
| Stress V (`832`) | -10.0–10.0 | `antenna:{ant}:receiver:H:lo_plate:mixer:{n}:pll:stress` — **confirmed present, `H` only** (`smax.json:8727`ish). **`L` has no `lo_plate` container at all** (`L` keys are only `mixer`, `description` — `smax.json:8612-8641`), so this WSMA path is dead for `L` receivers entirely | `gunnBias[ant][rx] - RM_GUNN_TARGET_BIAS_V8_F[insert]` — a **computed difference**, not a raw reading (see next section); the bound itself is still a literal | HIGH (WSMA, H only), HIGH (RM) |
| IF Power (`863`) | -1e6–1e6 | `...H:lo_plate:mixer:{n}:pll:bandpass_power` — confirmed present, **H only**; code calls the SMAX key `"BPF"`, which doesn't match `bandpass_power` textually — confirm these are the same field before applying. Dead for `L` (no `lo_plate`) | `RM_GUNN_PLL_IFPOWER_F` / `RM_GUNN2_PLL_IFPOWER_F` — `err_low: -1e6, err_high: 1e6` | MEDIUM (WSMA, H only), HIGH (RM) |
| Nz Power (`888`) | -10.0–10.0 | `...H:lo_plate:mixer:{n}:pll:notch_power` — confirmed present, **H only**; code calls the SMAX key `"NF"`. Dead for `L` (no `lo_plate`) | `RM_GUNN_PLL_PHASENOISE_F` / `RM_GUNN2_PLL_PHASENOISE_F` — `err_low: -10.0, err_high: 10.0` | MEDIUM (WSMA, H only), HIGH (RM) |
| PLLRatio (`908`) | -10.0–1e6 | reuses `r->noisePower` (the *Nz Power* field again) rather than checking the displayed ratio itself — looks like a copy/paste leftover in the source, not a distinct bound worth recovering | — | N/A — likely a source bug, not a real threshold |
| SIS V (`1045`) | ±999.9 (`MIXER_BOARD_WACKO_VOLTAGE`) | C code reads `antenna:{ant}:receiver:{H\|L}:mixer:{n}:sis_bias:voltage` (traced to `receiverMonitor.c:373`) — **confirmed present, `L` only** (`smax.json:8634`, within `L:mixer:__each__:template:sis_bias`). `H` has **no `sis_bias` container**; the nearest real field is `H:mixer:1:bias` (`smax.json:8801`) — same mismatch as the Gunn V row above, opposite polarization affected | `RM_SIS_MIXER{rx0}_VOLTAGE_CALIB_F` (`:389`) — same bound | HIGH (WSMA, L only), HIGH (RM) |
| SIS I (`1073`) | ±999.9 | `...:mixer:{n}:sis_bias:current` (`:374`) — **confirmed present, `L` only** (`smax.json:8626`). `H` has `mixer:1:current` (`smax.json:8813`) directly, no `sis_bias` wrapper — same field, different path shape | `RM_SIS_MIXER{rx0}_CURRENT_CALIB_F` (`:391`) | HIGH (WSMA, L only), HIGH (RM) |
| SIS B (`1111`) | ±999.9 | `...:mixer:{n}:sis_bias:bfield_current` (`:375`) — **confirmed present, `L` only** (`smax.json:8622`). `H` has `mixer:1:bfield_current` (`smax.json:8786`) directly, no `sis_bias` wrapper | `RM_SIS_MIXER{rx0}_BFIELD_CALIB_F` (`:393`) | HIGH (WSMA, L only), HIGH (RM) |
| SIS P (`1140`) | ±999.9 | `...:mixer:{n}:sis_bias:power` (`:376`) — **confirmed present, `L` only** (`smax.json:8630`). `H` has `mixer:1:if_power` (`smax.json:8825`) — different name, not just a different path shape | `RM_SIS_MIXER{rx0}_POWER_F` (`:395`) | HIGH (WSMA, L only), HIGH (RM) |
| ContDet (`1197`) | -1.0–100 | — (populated for both receiver types the same way) | `RM_CONT1_DET1_F` / `RM_CONT2_DET1_F` (`:401`) — `err_low: -1.0, err_high: 100` | HIGH |
| CDP (`1222`) | -100.0–1e5 | — | `RM_CONT1_DET1_POWER_MUWATT_F` / `RM_CONT2_DET1_MUWATT_F` (`:402`) — `err_low: -100.0, err_high: 1e5` | HIGH |

The `sis[]` struct is populated at `receiverMonitor.c:355-397`, split the
same way as the rest of the file: WSMA receivers via `readSmaxFloat()` with
label `"antenna:%d:receiver:%c:mixer:%d:sis_bias"` (sub-keys `voltage`,
`current`, `bfield_current`, `power`), non-WSMA via `rmRead()` against
`RM_SIS_MIXER{1,2}_{VOLTAGE,CURRENT,BFIELD}_CALIB_F` / `RM_SIS_MIXER{1,2}_POWER_F`.

**Schema-mismatch caveat found while confirming the WSMA path.** This turned
out to be **two separate, opposite-direction gaps**, not one — `L` is
missing an entire subtree that `H` has, and `H` is missing an entire subtree
that `L` has. Exact `conf/smax.json` locations, both under
`antenna:__each__:template:receiver`:

- **`L` polarization node has no `lo_plate` container at all.**
  `L`'s only children are `mixer` and `description` — full node:
  ```
  8612  "L": {
  8613    "mixer": { ... },              ← see sis_bias detail below
  8641    "description": "Information on the L-band cartridge"
        }
  ```
  Verified: `rx["L"].keys() == ["mixer", "description"]`. This means every
  `pll:*` field the C code reads via `lo_plate:mixer:{n}:pll:*` — `stress`,
  `bandpass_power` ("IF Power"), `notch_power` ("Nz Power") — **has no home
  in `smax.json` for `L` receivers**. Those three WSMA canonical-name
  proposals in the table above are `H`-only, not `{H|L}` as first written.

- **`L`'s `mixer` *does* have the `sis_bias` container** the C code expects
  for the SIS-bias fields, with sub-keys matching `readSmaxFloat()` exactly:
  ```
  8612  "L": {
  8613    "mixer": {
  8614      "__each__": {
  8615        "over": "1-2",
  8617        "template": {
  8617          "sis_bias": {
  8622            "bfield_current": { "smax_type": "int", ... },
  8626            "current":        { "smax_type": "float", ... },
  8630            "power":          { "smax_type": "float", ... },
  8634            "voltage":        { "smax_type": "float", ... }
  ```

- **`H` polarization node has `lo_plate` (with `pll:stress`,
  `pll:bandpass_power`, `pll:notch_power` all present) but no `sis_bias`
  container anywhere under `mixer`.** The same four SIS-bias quantities sit
  directly under `mixer:1`, with two of the four renamed:
  ```
  8644  "H": {
  8646    "lo_plate": {
  8647      "mixer": {
  8649        "1": {
                ...
  8681          "pll": {
  8681            "bandpass_power": { "smax_type": "float", "unit": "?" },  ← FOUND
  8703            "notch_power":    { "smax_type": "float", "unit": "?" },  ← FOUND
  8727            "stress":         { "smax_type": "float", "unit": "mV" }, ← FOUND
              }
            }
          }
        },
  8784    "mixer": {                    ← sibling of lo_plate, NOT lo_plate:mixer
  8785      "1": {
  8786        "bfield_current": { "smax_type": "float", "unit": "uA" },   ← matches L's sis_bias:bfield_current
  8801        "bias":           { "smax_type": "float", "unit": "mV" },   ← C code (Gunn V / SIS V) expects "voltage"
  8813        "current":        { "smax_type": "float", "unit": "uA" },   ← matches L's sis_bias:current
  8825        "if_power":       { "smax_type": "float", "unit": "uW?" },  ← C code (SIS P) expects "power"
  8825        "ivp_curve":      { ... }   ← this is the "[dict]"-smax_type node flagged in
                                            the 2026-07-01 insight ("Invalid smax_type values")
  ```
  Verified: `H:lo_plate:mixer:1:bias` — missing; `H:mixer:1:sis_bias:voltage`
  — missing; `H:mixer:1:bias` — found (the real field, one level up from
  where the C code's `lo_plate:mixer:{n}:bias` label would put it, and named
  `bias` instead of `voltage`).

**Net effect on the printInvalidFloat/printInvalidDouble table above:**
Stress V / IF Power / Nz Power's WSMA canonical names are `H`-only (dead for
`L`). SIS V/I/B/P's WSMA canonical names are `L`-only (dead for `H`) — for
`H`, the nearest real fields are `mixer:1:bias` and `mixer:1:if_power`,
renamed and unwrapped relative to what the C code's `sis_bias:{voltage,power}`
labels expect. Same physical readouts on both polarizations of the same
antenna's receiver, but two structurally different schemas — this reads
like independent, uncoordinated additions to `smax.json` for `H` vs. `L`
rather than a deliberate difference, and is worth flagging to Marc as a
schema-consistency question independent of the wacko-threshold work this
doc otherwise tracks.

There's also a **third bound source** discovered while tracing this: the
per-mixer `flags->mixerVoltage/Current/Bfield` warning flags (`:405-411`,
distinct from the `printInvalidFloat` wacko check) use `minV/maxV`,
`minI/maxI`, `minB/maxB` arrays loaded at startup from external files —
`readLimits(BIAS_LIMITS_FILE, ...)` where `BIAS_LIMITS_FILE =
"/global/configFiles/mixerBias.targets"` (and `mixerCurrent.targets`,
`mixerBfield.targets`, `receiverMonitor.c:29-31,256-258`). These are
per-antenna, per-mixer calibration targets read from a config file on disk
— neither a `#define` nor a live computation. They represent a *warning*
tier (`flags->mixerVoltage[ant] = 1` drives highlighting, not a blanked
"wacko" cell) layered on top of the wider `printInvalidFloat` sanity bound —
i.e. this one field already has cursesmonitor's two-tier warn/err structure,
just sourced from two different places. Recovering these into `warn_low`/
`warn_high` would require reading `mixerBias.targets` et al., which live
outside this repository — flagged for awareness, not pursued further here.

Net new HIGH-confidence candidates from this table: **11** (LO Freq, Gunn V,
Stress V, RM-path IF Power and Nz Power, plus SIS V/I/B/P and ContDet/CDP —
all six of the previously-LOW `sis[]` fields resolved cleanly on the RM
side), plus the `antenna:*:receiver:*:lo_plate:mixer:*:pll:stress` and
`...mixer:*:sis_bias:*` SMAX paths, which are new additions to the earlier
DSM/RM tables.

## Wacko checks that are NOT a static hardcoded-value comparison

A broader pass over every `wacko`-emitting site (not just ones tied to a
named bound) found several patterns that don't reduce to a fixed
`err_low`/`err_high` pair at all. These are listed for completeness and to
head off re-discovering them — none should be added to `smax.json` as static
thresholds without first deciding whether `MonitorPoint` needs a new
validity concept.

**Bound computed from another live value at read time** (the threshold
itself moves, so no static number exists to record):
- `receiverMonitor.c:1249-1264` — Tsys sanity check: `exp = 0.4 * freq[rx0] / GHZ`
  (expected system temperature, derived live from the antenna's currently
  tuned LO frequency via `DSM_REQUESTED_FREQUENCY_V2_D`), then
  `tsys < 0.5*exp || tsys > 10.0*exp`. The bound is a multiple of a
  simultaneously-read value — there is no fixed range to lift out.
- `arrayMonitor.c:696-700,1541` — `windSpeedWacko = WIND_SPEED_WACKO * MPH_TO_METER_PER_SEC`
  only when the display's unit setting is metric — a unit-dependent runtime
  bound, not the raw `WIND_SPEED_WACKO` constant itself.

**Sanity check on a mathematically-impossible sign/value, not an empirical
range** (would map to a "must be non-negative" or "must not be NaN"
validity rule, not a min/max pair):
- `allanVariance.c:102` — `if (allan[antennaNumber][j][i] < 0)` — an Allan
  variance can't be negative; this flags a bad computation, not an
  out-of-range physical reading.
- `c1DC.c:283` — `isnan(controlVoltageRMSs[...]) || controlVoltageRMSs[...] <= 0.0`
  — explicit NaN check combined with "RMS can't be ≤ 0."
- `dDSCursesMonitor.c:380` — `fringeRate[..] == fringeRate[..]` is a NaN
  self-inequality check, paired with a literal ±1000 range.

**Value under test is itself a computed quantity** (a formula or
difference), even though the final bound is a literal — these could still
become `err_low`/`err_high` thresholds, but on a *derived* field, not a raw
SMAX reading, so they'd need a computed-field concept in `MonitorSystem`
before a threshold means anything:
- `airHandler.c:584` — `floatvalue = -setPointC + insideTemperatureC`
  (temperature differential), then `fabs(floatvalue) > 100`.
- `airHandler.c:1074` — `expectedHumidity = outsideHumidity * exp(HoverR * (1/celsiusToKelvin2(insideTemp) - 1/outsideTemp))`
  (full psychrometric formula), then `fabs(expectedHumidity) > 150`.
- `dewarpage.c:238` — `hoursSinceRebuild = runningHours - rebuildHours`,
  then range-checked.
- `antPage2.c:268,312` — `azTrErrorArcSec / 3600.0` compared against 100000.
- `receiverMonitor.c:832` non-WSMA Stress V path (see table above).

**Non-numeric sanity checks** (string corruption or unrecognized
enum/status code — not a range at all):
- `antMonitor.c:436-447` — `strlen(source) > SOURCE_CHAR_LEN` and
  `source[i] < 0` (non-ASCII byte) flag a corrupted source-name string.
- `arrayMonitor.c:820,832,846,854` — same pattern for the project
  description/PI/observer/operating-location strings.
- `dewarpage.c:443` — `strlen(turboStatusString) > 8`.
- Switch-`default` cases (`aCMonitor.c:432`, `antMonitor.c:1029`,
  `antPage2.c:579`, `iFLOMonitor.c:240,254`) — an unrecognized enum/status
  code, not a numeric comparison.

---

## Summary

- **~55-65 concrete threshold candidates** recovered with HIGH confidence,
  concentrated in three clusters: the 9-site meteorology block in
  `weather.c` (up to 45 fields), a handful of `RM_CELESTRON_*`/`RM_TILT1_*`/
  `RM_GUNN*_RFPOWER*`/`RM_WIRE_GRID_*` fields with literal `rm_read()` names,
  and the `receiverMonitor.c` `printInvalidFloat`/`printInvalidDouble` call
  sites (bounds passed as function arguments rather than `#define`s — same
  static-value pattern, different packaging).
- Two prior "NO MATCH" findings from `dsm_placeholder_review.md` are now
  explained rather than just unresolved: `DSM_DUT` has no SMAX field because
  cursesmonitor reads DUT1 from a flat file (`ser7.dat`), not DSM.
- A few bounds (chopper counts, elevation offset, vane encoder, rest
  frequency) still need one more grep pass to pin down the exact
  `rm_read()`/populating field before a canonical name can be proposed with
  confidence — flagged LOW/MEDIUM above rather than guessed. (The `sis[]`
  fields in `receiverMonitor.c` were traced to completion and moved to HIGH.)
- Tracing the `sis[]` population also surfaced a schema-mismatch between the
  `H` and `L` polarization nodes in `smax.json` (`H` is missing the
  `sis_bias` container the code expects) and a third, file-based bound
  source (`/global/configFiles/mixer{Bias,Current,Bfield}.targets`) that
  drives a separate warning tier — neither is a `wacko` finding per se, but
  both are worth a look independent of this review.
- `WACKO_TIMESTAMP_MIN/MAX` doesn't fit the `err_low`/`err_high` model — it's
  a staleness check on `SERVER_TIMESTAMP_L`, which is a different validity
  concept (data age) than a sanity bound on the reading itself.
- **Not every `wacko` reduces to a static threshold at all.** A broader scan
  found bounds computed from another live value at read time (Tsys vs.
  expected-Tsys-from-frequency, unit-dependent wind speed), sanity checks on
  a mathematically-impossible sign or NaN rather than an empirical range,
  checks on a derived/computed value (temperature differentials, a
  psychrometric formula) rather than a raw reading, and non-numeric
  string/enum corruption checks. None of these fit the current
  `err_low`/`err_high` model on `MonitorPoint`; recovering them as validity
  logic would need either a computed-threshold mechanism or a different
  validity concept (NaN/sign sanity, string-corruption detection) — out of
  scope for this pass.

**Next step (pending Marc's review):** apply the HIGH-confidence `err_low`/
`err_high` pairs to `conf/smax.json`, following the same
propose-then-confirm workflow used for `dsm_placeholder_review.md`.
