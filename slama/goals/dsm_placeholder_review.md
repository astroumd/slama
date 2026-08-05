# DSM Placeholder → Real Canonical Name Review

Generated from cross-referencing `dsm:placeholder:DSM_*` strings in
`src/slama/conf/displays/*.json` against the refreshed `conf/smax.json`
(post `smax_from_valkey.py --merge --overwrite` update).

**146 placeholder occurrences across 19 files.** Each entry below is tagged:

- **HIGH** — field name/semantics match closely, likely correct as-is
- **MEDIUM** — plausible match but multiple candidate fields exist, or a caveat applies (units, indexing, node ambiguity)
- **LOW** — weak match, likely wrong; included only as a starting point
- **NO MATCH** — no corresponding field found in current `smax.json`; may not exist in Valkey yet, or needs a different namespace

Note: **HIGH** confidence mappings have been edited to JSON (checked off below).

**2026-07-15 correction pass:** an audit found that most of the "DSM ID (monitor C
code)" identifiers below were never actually verified against the cursesmonitor C
source — many were invented placeholder names that happen to look like real DSM
identifiers. `goals/dsm_placeholder_review.csv` has been fully re-derived against
the literal `dsmRead`/`call_dsm_read`/`dsm_structure_get_element`/`rmRead` call
sites in `cursesmonitor/src/*.c`, with an exact `file:line` citation on every row
(or an explicit "no C-code read found" flag where the placeholder had no real
source). That CSV is now the authoritative, line-cited version — this markdown
file has NOT been fully regenerated to match it row-for-row, but the entries below
that changed as a result of that audit are corrected in place, each flagged
`[CORRECTED 2026-07-15]`. For any entry not so flagged, cross-check the CSV before
relying on it, since the CSV received the full citation pass and this file did not.

**2026-07-16 vector-field pass:** most corrected canonical names were then wired
directly into the `src/slama/conf/displays/*.json` files, replacing the
`dsm:placeholder:` strings. Along the way, `smax.json`'s `size` metadata revealed
that many of the "real" fields identified above are multi-element arrays (2 to
242 elements), not single scalars — e.g. the mRG/YIG fields (`_V2_*`, size 2),
BDC detector/attenuator fields (`_V8_*`, size 8), and the coherence fringe
fields (`_V11_V11_V2_*`, size 242). `DataBridge.fetch_cell()` has no per-index
addressing, so these cells now show a stringified array rather than one number
— a deliberate tradeoff (real data over a dead placeholder) confirmed with
Marc, not an oversight. Fixing this properly needs a template/schema extension
to select a single array index per display column. `DSM_BASELINE_M`,
`DSM_FRINGE_TIMESTAMP`, `DSM_GENSET_STATUS`, `DSM_SMAINIT_PROGRESS`, the two
BDC "no ATTN field" rows, `DSM_PACU_STATUS`, `DSM_FULLPOL_STATUS`,
`DSM_SWARM_STATUS`, `DSM_ANT{ant}_SKYDIP_AGE`, `DSM_HAL_HAL_LAST_IPOINT_V11_L`,
and `DSM_HAL_HAL_NIGHTLY_POINTING_S` remain placeholders — genuinely no live
field exists for these. The `croom_iflo.json` IF/LO fields also remain
placeholders: their real canonical name needs polarization (`H`/`L`) *and*
mixer (`1`/`2`) indices that the `{ant}`-only template can't express at all.

---

## `aCmonitor.json`

### AC/PACU Status (DSM — placeholders)

- [ ] `DSM_AC_TEMP_C`  (Temp (C) (DSM))
      → proposed: `DSM:corcon:CORR_PACU_STATUS_X:RETURN_AIR_TEMP_F`   **[MEDIUM]**
      note: Multiple temp fields exist (RETURN_AIR_TEMP_F, SUPPLY_AIR_TEMP_F, MIXED_AIR_TEMP_F, OUTSIDE_AIR_TEMP_F) — pick the one that matches the physical sensor intended
- [ ] `DSM_AC_SMOKE`  (Smoke detected (DSM))
      → proposed: `DSM:corcon:CORR_PACU_STATUS_X:RETURN_DUCT_SMOKE_B`   **[MEDIUM]**
      note: Also SUPPLY_DUCT_SMOKE_B and ANALOG_RACK_SMOKE_V14_B/DIGITAL_RACK_SMOKE_V9_B exist — pick correct sensor
- [ ] `DSM_AC_FAN_STATUS`  (Fan status (DSM))
      → proposed: `DSM:corcon:CORR_PACU_STATUS_X:RETURN_FAN_STARTED_B`   **[MEDIUM]**
      note: Also SUPPLY_FAN_STARTED_B, SUPPLY_FAN_ENABLE_B, RETURN_FAN_ENABLE_B exist
- [ ] `DSM_AC_COMPRESSOR1`  (Compressor 1 (DSM))
      → proposed: `DSM:corcon:CORR_PACU_STATUS_X:COMPRESSOR_1_STAGE_A_B`   **[MEDIUM]** `[CORRECTED 2026-07-15]`
      note: aCMonitor.c does NOT read ALARM_B at all — it reads STAGE_A_B (aCMonitor.c:218) and STAGE_B_B (:225). ALARM_B exists live in the same struct and may still be the better single-cell status semantic; flagging both
- [ ] `DSM_AC_COMPRESSOR2`  (Compressor 2 (DSM))
      → proposed: `DSM:corcon:CORR_PACU_STATUS_X:COMPRESSOR_2_STAGE_A_B`   **[MEDIUM]** `[CORRECTED 2026-07-15]`
      note: Same correction as Compressor 1 — aCMonitor.c reads STAGE_A_B (:232)/STAGE_B_B (:239), not ALARM_B
- [ ] `DSM_AC_HUMIDITY`  (Humidity % (DSM))
      → proposed: `DSM:corcon:CORR_PACU_STATUS_X:RETURN_AIR_REL_HUM_F`   **[MEDIUM]**
      note: Also OUTSIDE_AIR_REL_HUM_F, SUPPLY_AIR_REL_HUM_F exist
- [ ] `DSM_PACU_STATUS`  (PACU status (DSM))
      → **NO MATCH**
      note: No single composite "status" field; CORR_PACU_STATUS_X has 50+ individual fields. Needs Marc to pick specific field(s) or this cell should be dropped/replaced with multiple cells

---

## `airhandler.json`

### Site Weather (DSM — placeholder)

- [x] `DSM_SMA_TEMP_F`  (SMA temp (DSM))
      → proposed: `DSM:colossus:SMA_METEOROLOGY_X:TEMP_F`   **[HIGH]**
- [x] `DSM_SMA_HUMIDITY_F`  (SMA humidity (DSM))
      → proposed: `DSM:colossus:SMA_METEOROLOGY_X:HUMIDITY_F`   **[HIGH]**

---

## `antdrive.json`

### Drive Fault State (DSM — placeholder)

- [x] `DSM_ESTOP_COMMAND_S`  (DSM ESTOP (unavailable))
      → proposed: `DSM:acc{ant}:DSM_ESTOP_COMMAND_S`   **[HIGH]**
      note: Per-antenna computer field; needs {ant} template, not a single global point

---

## `arraymonitor.json`

### Project / Observation (DSM — placeholders)

- [x] `DSM_AS_PROJECT_ID_L`  (Project ID (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_ID_L`   **[HIGH]**
      note: hal9000 = current control computer (oldhal is legacy backup with same field)
- [x] `DSM_AS_PROJECT_OBSERVER_C30`  (Observer (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_OBSERVER_C30`   **[HIGH]**
- [x] `DSM_AS_PROJECT_OPERATINGLOCATION_C256`  (Location (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_OPERATINGLOCATION_C256`   **[HIGH]**
- [x] `DSM_SCANS_REMAINING`  (Scans remain (DSM))
      → proposed: `DSM:hal9000:DSM_AS_SCANS_REMAINING_L`   **[HIGH]**
- [ ] `DSM_FULLPOL_STATUS`  (FullPol (DSM))
      → **NO MATCH**
      note: No full-polarization status field found in DSM; may need to check "polar" fields: DSM_AS_POLAR_MODE_S / DSM_OBS_POLAR_MODE_S under hal9000 as loose candidates
- [ ] `DSM_SWARM_STATUS`  (SWARM status (DSM))
      → **NO MATCH**
      note: No single SWARM status field; closest is per-board DSM:<roach2-idx>:SMAINIT_REPORT_X:PRG_STATUS_V24_V6_L (per-board init status, not overall status)
- [ ] `DSM_DUT`  (DUT (DSM))
      → proposed: `RM:acc{ant}:RM_POLAR_DUT_SEC_D`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected from NO MATCH — arrayMonitor.c:418 reads RM_POLAR_DUT_SEC_D via rmRead(specialAntenna,...) for the "DUT" label. Confirmed live for all 9 antennas. RM_* fields use a bare `RM:` prefix per antenna, never a `DSM:` node
- [ ] `DSM_TAU225`  (Tau225 (DSM))
      → proposed: `DSM:colossus:DSM_CSO_225GHZ_TAU_F`   **[MEDIUM]**
      note: Alternative: weather:forecast:cso:tau225 (forecast value) vs this raw CSO feed — pick which source is intended
- [x] `DSM_TAU350`  (Tau350 (DSM))
      → proposed: `DSM:colossus:DSM_CSO_350MICRON_TAU_SCALED_F`   **[HIGH]**

---

## `bdc.json`

### BDC 4-8 GHz (DSM — placeholders)

- [ ] `DSM_BDC_4_8_DET_V_CH1`  (Det voltage ch1 (DSM))
      → proposed: `DSM:obscon:BDC48_X:DSM_BDC_CR1_DETECTOR_READBACK_V8_F`   **[MEDIUM]**
      note: Node-to-band mapping (BDC48_X=4-8GHz) is inferred by name, not confirmed
- [ ] `DSM_BDC_4_8_DET_V_CH2`  (Det voltage ch2 (DSM))
      → proposed: `DSM:obscon:BDC48_X:DSM_BDC_CR2_DETECTOR_READBACK_V8_F`   **[MEDIUM]**
- [ ] `DSM_BDC_4_8_VGA`  (VGA setting (DSM))
      → proposed: `DSM:obscon:BDC48_X:DSM_BDC_VVA1_CTRL_READBACK_V8_F`   **[LOW]**
      note: VVA field exists but which of VVA1-6 maps to "VGA setting" is unclear
- [ ] `DSM_BDC_4_8_ATTN`  (Attn setting (DSM))
      → **NO MATCH**
      note: No ATTN-named field in BDC48_X (only VVA1-6, CR1-6, TEMP, DI); may be same as VGA/VVA

### BDC 8-12 GHz (DSM — placeholders)

- [ ] `DSM_BDC_8_12_DET_V_CH1`  (Det voltage ch1 (DSM))
      → proposed: `DSM:obscon:BDC_X:DSM_BDC_AR1_DETECTOR_READBACK_V8_F`   **[LOW]**
      note: BDC_X has no band name; mapped here only by elimination (4 obscon BDC nodes exist: BDC48_X, BDC1012_X, BDC1216_X, BDC_X — need Marc to confirm BDC_X = 8-12 GHz)
- [ ] `DSM_BDC_8_12_DET_V_CH2`  (Det voltage ch2 (DSM))
      → proposed: `DSM:obscon:BDC_X:DSM_BDC_AR2_DETECTOR_READBACK_V8_F`   **[LOW]**
- [ ] `DSM_BDC_8_12_VGA`  (VGA setting (DSM))
      → proposed: `DSM:obscon:BDC_X:DSM_BDC_AR1_CTRL_READBACK_V8_F`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected from NO MATCH — BDC_8_12.c's curses labels literally read "VGA1"/"VGA2" for the AR1/AR2 control-readback fields (:112,:117). AR1/AR2 *are* the VGA fields, just named AR in the DSM schema
- [ ] `DSM_BDC_8_12_ATTN`  (Attn setting (DSM))
      → proposed: `DSM:obscon:BDC_X:DSM_BDC_AT20_CTRL_READBACK_V8_F`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected — the previous proposal (AR1_CTRL_READBACK_V8_F) was actually the VGA field, not ATTN (see row above). The real "ATTEN1 CONTROL RDBK" label reads AT20_CTRL_READBACK_V8_F (:122); AT21 (:127) is the ATTEN2 sibling

### BDC 10-12 GHz (DSM — placeholders)

- [ ] `DSM_BDC_10_12_DET_V_CH1`  (Det voltage ch1 (DSM))
      → proposed: `DSM:obscon:BDC1012_X:DSM_BDC_AR1_DETECTOR_READBACK_V8_F`   **[MEDIUM]**
- [ ] `DSM_BDC_10_12_DET_V_CH2`  (Det voltage ch2 (DSM))
      → proposed: `DSM:obscon:BDC1012_X:DSM_BDC_AR2_DETECTOR_READBACK_V8_F`   **[MEDIUM]**
- [ ] `DSM_BDC_10_12_ATTN`  (Attn setting (DSM))
      → proposed: `DSM:obscon:BDC1012_X:DSM_BDC_AT20_CTRL_READBACK_V8_F`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected — same AR-vs-AT mislabeling as the 8-12 GHz chassis. "VGA1/VGA2" labels (:116,:121) read AR1/AR2; "ATTEN1/ATTEN2" labels (:126,:131) read AT20/AT21

### BDC 12-16 GHz (DSM — placeholders)

- [ ] `DSM_BDC_12_16_DET_V_CH1`  (Det voltage ch1 (DSM))
      → proposed: `DSM:obscon:BDC1216_X:DSM_BDC_CR1_DETECTOR_READBACK_V8_F`   **[MEDIUM]**
- [ ] `DSM_BDC_12_16_DET_V_CH2`  (Det voltage ch2 (DSM))
      → proposed: `DSM:obscon:BDC1216_X:DSM_BDC_CR2_DETECTOR_READBACK_V8_F`   **[MEDIUM]**
- [ ] `DSM_BDC_12_16_VGA`  (VGA setting (DSM))
      → proposed: `DSM:obscon:BDC1216_X:DSM_BDC_VVA1_CTRL_READBACK_V8_F`   **[LOW]**
      note: Which of VVA1-6 is unclear
- [ ] `DSM_BDC_12_16_ATTN`  (Attn setting (DSM))
      → **NO MATCH**
      note: No ATTN-named field in BDC1216_X (only VVA1-6, CR1-6, TEMP, DI)

---

## `coherence.json`

### Fringe / Coherence Status (DSM — placeholders)

- [ ] `DSM_FRINGE_AMPLITUDE`  (Fringe amplitude (DSM))
      → proposed: `DSM:hcn:LAST_SCAN_VISIBILITES_X:AMP_V11_V11_V2_F`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected — the prior proposal (phasemon:PHASEMON_DATA_X:CORR_AMPLITUDE_V10_D) is the wrong subsystem (12 GHz phase-monitor delay tracking, not per-scan visibility). coherence.c:177 reads AMP_V11_V11_V2_F from the LAST_SCAN_VISIBILITES_X structure it fetches via dsmRead("hcn",...) at :123. AMP_H_V11_V11_V2_F is the Rx B/H-pol sibling
- [ ] `DSM_FRINGE_PHASE`  (Fringe phase (deg) (DSM))
      → proposed: `DSM:hcn:LAST_SCAN_VISIBILITES_X:PHASE_V11_V11_V2_F`   **[MEDIUM]** `[CORRECTED 2026-07-15]`
      note: Corrected — same wrong-subsystem issue as Fringe Amplitude. PHASE_V11_V11_V2_F is confirmed live in the same struct coherence.c already reads, but coherence.c itself doesn't extract it with dsmGetElement — held at MEDIUM for that reason
- [ ] `DSM_COHERENCE_PCT`  (Coherence (%) (DSM))
      → proposed: `DSM:hcn:LAST_SCAN_VISIBILITES_X:CORR_V11_V11_V2_F`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected from NO MATCH — coherence.c:178 directly reads this field for its "Coherence"-labeled column. CORR_H_V11_V11_V2_F is the Rx B/H-pol sibling
- [ ] `DSM_BASELINE_M`  (Baseline (m) (DSM))
      → **NO MATCH** (reconfirmed)
      note: No baseline-length-in-meters field exists live. The only live "BASELINE"-named field is DSM:phasemon:PHASEMON_HRDWR_STAT_X:BASELINES_V10_V3_B, a per-baseline hardware-status bitmap, not a physical length
- [ ] `DSM_COHERENCE_INTEG`  (Integration (s) (DSM))
      → proposed: `DSM:hal9000:SCAN_LENGTH_F`   **[LOW]** `[CORRECTED 2026-07-15]`
      note: coherence.c itself reads no integration-time field. SCAN_LENGTH_F is a plausible candidate but from the scan-scheduling subsystem (hal9000), not something coherence.c reads — flagged as a guess, not C-code-verified
- [ ] `DSM_FRINGE_TIMESTAMP`  (Last update (DSM))
      → **NO MATCH** (reconfirmed)
      note: No field-level timestamp exists inside LAST_SCAN_VISIBILITES_X live. coherence.c:123's dsmRead(...,&t) captures the SMAX fetch timestamp as a local variable, not a distinct DSM field

---

## `croom_iflo.json`

### iFLO LO Lock and IF Power (DSM — placeholders)

- [ ] `DSM_ANT{ant}_IFLO_LO_LOCK`  (LO lock status (DSM))
      → proposed: `antenna:{ant}:receiver:{H|L}:lo_plate:mixer:{1|2}:pll:lock`   **[MEDIUM — upgraded from LOW]**
      note: Superseded by the `wacko_validity_review.md` receiverMonitor.c/live-dump trace
      (2026-07-15): a live `dump_redis.py` snapshot confirms `pll:lock` is a real, currently-written
      field per antenna, per polarization (`H`/`L`), per mixer (`1`/`2`) — verified on antennas 1, 7,
      8. This is a much better field-semantics match than the earlier `DSM:hal9000` vector guess, but
      it's indexed by polarization *and* mixer, not just `{ant}` — the current display JSON `{ant}`-only
      template can't address it without a schema/template extension (same class of gap as the
      phasemon `V10` vector fields below). Confidence held at MEDIUM pending that design decision,
      not because the field identity is in doubt.
- [ ] `DSM_ANT{ant}_IFLO_IF_POWER`  (IF power (DSM))
      → proposed: `antenna:{ant}:receiver:{H|L}:lo_plate:mixer:{1|2}:pll:BPF`   **[MEDIUM — upgraded from MEDIUM]**
      note: Same live-dump trace as above. `BPF` (bandpass filter power) is the literal live key name —
      also independently confirmed as the field `receiverMonitor.c`'s "IF Power" row reads via
      `readSmaxFloat(label, "BPF", ...)` (see `wacko_validity_review.md`'s `printInvalidFloat` table).
      Same `{ant}`-only template limitation as `IFLO_LO_LOCK` above; the `DSM:m5:C1DC_STATUS_X` guess
      is superseded — that field is a correlator downconverter reading, not the receiver LO chain this
      placeholder's label describes.
- [ ] `DSM_ANT{ant}_IFLO_LO_FREQ`  (LO freq (GHz) (DSM))
      → proposed: `antenna:{ant}:receiver:{H|L}:lo_plate:mixer:{1|2}:vco:tune_freq`   **[MEDIUM — upgraded from LOW]**
      note: Live dump confirms `vco:tune_freq` as a real per-antenna, per-polarization, per-mixer field
      (no bare "frequency" key exists under `lo_plate:mixer` in the live DB, despite `smax.json` listing
      one). Held at MEDIUM for the same `{ant}`-only template reason as above, and because unit/scale
      (Hz vs. GHz) needs confirming before wiring it up — the placeholder label says GHz.
- [ ] `DSM_ANT{ant}_IFLO_TIMESTAMP`  (Last update (DSM))
      → **NO MATCH — confirmed absent in live dump**
      note: No timestamp field appears anywhere under `lo_plate:mixer:*` in either `conf/dump1.out` or
      `conf/dump2.out`; the earlier "no match found" conclusion (from `smax.json` alone) is reconfirmed
      against the live database.

---

## `deice.json`

### Antenna 5 Structural Temps (DSM — placeholder)

- [x] `DSM_ANTENNA5_TEMPS_X`  (Ant5 structural temps (DSM))
      → proposed: `DSM:hal9000:DSM_ANTENNA5_TEMPS_X`   **[HIGH]**
      note: Branch node with several sub-fields (ANTENNA_SURFACE_MINMAX_TEMPS_V24_F, ANTENNA_THERMOMETERS_V20_F, QUADRUPOD_1-4_V24_F) — display should reference specific sub-field, not the branch itself

---

## `gps.json`

### GPS Status (DSM — placeholders)

- [ ] `DSM_GPS8_LOCK_STATUS`  (GPS8 lock (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_STATUS_B`   **[MEDIUM]** `[CORRECTED 2026-07-15]`
      note: Swapped from GPS8_CTL_STATUS_B (gpsPage.c:102, "Bad Control status" — a fault flag, not lock) to GPS8_STATUS_B (gpsPage.c:74, the "Valid Time/GPS Lock/..." flag group) — closer semantic match
- [ ] `DSM_TRUETIME_LOCK_STATUS`  (TrueTime lock (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:TT_PHASE_LOCKED_S`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected from wrong subsystem — the prior proposal (m5:MRG_STATUS_X:52MHZ_LOCK_S) is the LO-reference-chain PLL lock, unrelated to TrueTime. gpsPage.c:152 reads TT_PHASE_LOCKED_S from the same GPSD_REPORT_X structure as every other row in this group
- [x] `DSM_GPS_AVG_PHASE_NS`  (Avg Phase (ns) (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_AVG_PHASE_F`   **[HIGH]**
- [x] `DSM_GPS_FREQ_CTL`  (Freq ctl (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_FREQ_CTLR_VALUE_F`   **[HIGH]**
- [x] `DSM_GPS_NEXT_LEAP`  (Next leap sec (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_NEXT_LEAP_SECOND_L`   **[HIGH]**
- [x] `DSM_GPS8_LAT_DEG`  (GPS8 Lat (deg) (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_LAT_D`   **[HIGH]**
- [x] `DSM_GPS8_LON_DEG`  (GPS8 Lon (deg) (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_LON_D`   **[HIGH]**
- [x] `DSM_GPS8_ALT_FT`  (GPS8 Alt (ft) (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_ALT_F`   **[HIGH]**
- [x] `DSM_GPS8_DOP`  (DOP (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_DOP_F`   **[HIGH]**
- [x] `DSM_GPS_UTC_OFFSET`  (GPS-UTC offset (s) (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_GPS_MINUS_UTC_B`   **[HIGH]**
- [x] `DSM_GPS_NUM_SATS`  (Num sats (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:TT_NUM_SATS_S`   **[HIGH]**
- [x] `DSM_GPS_BAD_MSG_COUNT`  (Bad messages (DSM))
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_BAD_MSGS_B`   **[HIGH]**

---

## `hangar.json`

### Current Project (DSM — placeholders)

- [x] `DSM_AS_PROJECT_ID_L`  (Project ID (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_ID_L`   **[HIGH]**
      note: hal9000 = current control computer (oldhal is legacy backup with same field)
- [x] `DSM_AS_PROJECT_DESCRIPTION_C256`  (Description (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_DESCRIPTION_C256`   **[HIGH]**
- [x] `DSM_AS_PROJECT_PI_C30`  (PI (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_PI_C30`   **[HIGH]**
- [x] `DSM_AS_PROJECT_OBSERVER_C30`  (Observer (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_OBSERVER_C30`   **[HIGH]**
- [x] `DSM_HANGAR_LIGHT_L`  (Hangar Light (DSM))
      → proposed: `DSM:colossus:DSM_HANGAR_LIGHT_L`   **[HIGH]**

---

## `misc_dsm.json`

### Generator Set (DSM — placeholders)

- [ ] `DSM_GENSET_POWER_W`  (Genset power (W) (DSM))
      → proposed: `DSM:obscon:DSM_IWATCH_DATA_X:KILOWATTS_S`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected from NO MATCH — genset.c:85 reads KILOWATTS_S from the DSM_IWATCH_DATA_X structure (node obscon, not hal9000 — both carry the same live struct) for its "Kilowatts" label. KVA_F/KILOVARS_F are the apparent/reactive-power siblings
- [ ] `DSM_GENSET_STATUS`  (Genset status (DSM))
      → **NO MATCH**
      note: Same as above — no generator-specific field found

### C1DC Correlator Power (DSM — placeholders)

- [ ] `DSM_C1DC_POWER_LEVEL`  (C1DC power level (DSM))
      → proposed: `DSM:m5:C1DC_STATUS_X:IF_POWER_V3_V9_F`   **[MEDIUM]**
      note: Field is a V3xV9 vector (downconverter x antenna); only one m5 node exists so this may need per-antenna array indexing
- [ ] `DSM_C1DC_STATUS`  (C1DC status (DSM))
      → proposed: `DSM:m5:C1DC_STATUS_X:OP_ALARM_V3_V9_S`   **[MEDIUM]**
      note: Also INPUTS_V3_V9_S exists — pick correct status field

### YIG Frequencies (DSM — placeholders)

- [ ] `DSM_YIG_FREQ_GHZ`  (YIG freq (GHz) (DSM))
      → proposed: `DSM:m5:MRG_CONTROL_X:REQ_FREQ_V2_D`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected — `reference:mrg:1:*` does NOT exist anywhere in the live dump_redis.py snapshot despite smax.json defining that node (schema exists, unpopulated). mRG.c:53 reads REQ_FREQ_V2_D ("Requested Frequency") from the real, live, node-m5 structure
- [ ] `DSM_YIG_LOCK_STATUS`  (YIG lock status (DSM)) — **was checked off as HIGH/validated, but is WRONG: the display JSON currently points at a dead key**
      → proposed: `DSM:m5:MRG_CONTROL_X:YIG_LOCKED_V2_S`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: The prior "validated" note only confirmed the path exists in smax.json's schema, not that it's populated live — it isn't. mRG.c:70 reads YIG_LOCKED_V2_S ("Lock Status") from the real DSM:m5:MRG_CONTROL_X structure, confirmed live. `misc_dsm.json` and `mrg.json` currently point their "YIG lock status" cell at the dead `reference:mrg:1:yig:is_locked` key and need updating (see below)
- [ ] `DSM_YIG_TUNE_WORD`  (YIG tune word (DSM)) — **was checked off as HIGH/validated, but is WRONG: the display JSON currently points at a dead key**
      → proposed: `DSM:m5:MRG_CONTROL_X:CNTRL_VOLTAGE_V2_F`   **[MEDIUM]** `[CORRECTED 2026-07-15]`
      note: Same dead-key issue as YIG lock status. mRG.c:88 reads CNTRL_VOLTAGE_V2_F ("Tuning voltage") — an analog voltage, not a digital "tune word", so held at MEDIUM. `misc_dsm.json`/`mrg.json` need updating (see below)

### SMA Initialization (DSM — placeholders)

- [ ] `DSM_SMAINIT_STATE`  (Init state (DSM))
      → proposed: `DSM:acc1:SMAINIT_REPORT_X:PRG_STATUS_V24_V6_L`   **[LOW]**
      note: Per-computer init report, not a single global state; exists on every acc/roach2/hal9000/oldhal/m5/phasemon/obscon node — needs a decision on which computer(s) to show
- [ ] `DSM_SMAINIT_PROGRESS`  (Init progress (DSM))
      → **NO MATCH**
      note: No numeric progress field; PRG_STATUS_V24_V6_L is a 24x6 status matrix, not a simple percentage

---

## `mrg.json`

### MRG Status (DSM — placeholders)

- [ ] `DSM_MRG_LOCK_STATUS`  (Lock status (DSM)) — **was checked off HIGH/validated, but is WRONG: dead key, see YIG lock status above**
      → proposed: `DSM:m5:MRG_CONTROL_X:YIG_LOCKED_V2_S`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Same underlying field as the YIG lock-status row above (mRG.c:70) — MRG and YIG naming refer to the same physical PLL in this display. `mrg.json`/`misc_dsm.json` currently point at the dead `reference:mrg:1:yig:is_locked` key
- [ ] `DSM_MRG_FREQ_GHZ`  (Freq (GHz) (DSM))
      → proposed: `DSM:m5:MRG_CONTROL_X:REQ_FREQ_V2_D`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Duplicate of the YIG frequency row above (mRG.c:53) — `reference:mrg:1:set_frequency` does not exist live
- [ ] `DSM_MRG_TUNE_WORD`  (Tune word (DSM)) — **was checked off HIGH/validated, but is WRONG: dead key, see YIG tune word above**
      → proposed: `DSM:m5:MRG_CONTROL_X:CNTRL_VOLTAGE_V2_F`   **[MEDIUM]** `[CORRECTED 2026-07-15]`
      note: Duplicate of the YIG tune-word row above (mRG.c:88). `mrg.json`/`misc_dsm.json` currently point at the dead `reference:mrg:1:yig:v_tune` key
- [ ] `DSM_MRG_PHASE_ERROR`  (Phase err (DSM))
      → proposed: `DSM:m5:MRG_CONTROL_X:QUAD_V2_F`   **[MEDIUM]** `[CORRECTED 2026-07-15]`
      note: Corrected — `reference:mrg:1:residue` does not exist live. mRG.c:128 reads QUAD_V2_F ("PLL Quad voltage"), the closest live proxy for a phase-error signal. STRESS_V2_F (":142, "PLL Stress voltage") is an alternative
- [ ] `DSM_MRG_POWER_DBM`  (Power (dBm) (DSM))
      → proposed: `DSM:m5:MRG_CONTROL_X:LEVEL_V2_F`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected from NO MATCH — mRG.c:156 reads LEVEL_V2_F for its "YIG Power Testpoint" label, a direct match
- [ ] `DSM_MRG_TIMESTAMP`  (Last update (DSM))
      → proposed: `DSM:m5:MRG_CONTROL_X:CMD_TIME_V2_L`   **[MEDIUM]** `[CORRECTED 2026-07-15]`
      note: Corrected from NO MATCH — mRG.c:214 reads CMD_TIME_V2_L ("Last commanded at"), the closest live "last update" timestamp. LAST_TWEEK_V2_L (":227") is an alternative

---

## `project.json`

### Project Information (DSM — placeholders)

- [x] `DSM_AS_PROJECT_ID_L`  (Project ID (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_ID_L`   **[HIGH]**
      note: hal9000 = current control computer (oldhal is legacy backup with same field)
- [x] `DSM_AS_PROJECT_DESCRIPTION_C256`  (Description (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_DESCRIPTION_C256`   **[HIGH]**
- [x] `DSM_AS_PROJECT_PI_C30`  (P.I. (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_PI_C30`   **[HIGH]**
- [x] `DSM_AS_PROJECT_OBSERVER_C30`  (Observers (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_OBSERVER_C30`   **[HIGH]**
- [x] `DSM_AS_PROJECT_OPERATINGLOCATION_C256`  (Operating from (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_OPERATINGLOCATION_C256`   **[HIGH]**
- [x] `DSM_AS_PROJECT_COMMENT`  (Comment (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_COMMENT_C256`   **[HIGH]**
- [x] `DSM_AS_PROJECT_ANTENNAS`  (Antennas (DSM))
      → proposed: `DSM:hal9000:DSM_HAL_HAL_PROJECT_ANTENNAS_V11_S`   **[HIGH]**
- [x] `DSM_AS_PROJECT_SCRIPT`  (Obs script (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_SCRIPT_FILENAME_C256`   **[HIGH]**
- [x] `DSM_AS_PROJECT_SCRIPT_PID`  (Script PID (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_SCRIPT_PID_L`   **[HIGH]**
- [ ] `DSM_AS_PROJECT_MIR_FILE`  (MIR file (DSM))
      → proposed: `DSM:hcn:DSM_AS_FILE_NAME_C80`   **[HIGH]** `[CORRECTED 2026-07-15]`
      note: Corrected from NO MATCH — projectpage.c:56 reads DSM_AS_FILE_NAME_C80 from node hcn (not hal9000/oldhal) for the "MIR file:" label. Confirmed live
- [x] `DSM_AS_PROJECT_START_TIME`  (Start time UTC (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_STARTTIME_L`   **[HIGH]**
      note: NOTE: DSM_AS_PROJECT_ACTIVE_TIME (below) maps to the same field — likely a duplicate placeholder, pick one
- [ ] `DSM_AS_PROJECT_ACTIVE_TIME`  (Active time (DSM))
      → proposed: `DSM:hal9000:DSM_AS_PROJECT_STARTTIME_L`   **[MEDIUM]**
      note: Same field as DSM_AS_PROJECT_START_TIME above — likely redundant, consider removing one row

---

## `rscan.json`

### Nightly Pointing Model (DSM — placeholders)

- [x] `DSM_HAL_HAL_LAST_CPOINT_V11_L`  (Last C-point (DSM))
      → proposed: `DSM:hal9000:DSM_HAL_HAL_LAST_CPOINT_V11_L`   **[HIGH]**
- [ ] `DSM_HAL_HAL_LAST_IPOINT_V11_L`  (Last I-point (DSM))
      → **NO MATCH**
      note: No I-point field found; only LAST_CPOINT_V11_L and LAST_CPOINT_RX_V11_S exist — "I-point" may not be tracked separately from C-point
- [ ] `DSM_HAL_HAL_NIGHTLY_POINTING_S`  (Nightly pointing (DSM))
      → proposed: `DSM:hal9000:DSM_HAL_HAL_POLAR_PATTERN_REQUEST_S`   **[LOW]**
      note: No exact "nightly pointing" field; this is a loose guess

---

## `seeing.json`

### Phase Monitor Baselines (DSM — placeholders)

- [ ] `DSM_PHASEMON_BL1_RAW_PHASE`  (Baseline 1 Raw Phase (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:RAW_PHASE_V10_D`   **[MEDIUM]**
      note: Field is a 10-element vector over baselines (V10) — need array index for baseline 1, not a separate BL1-4 field per baseline
- [ ] `DSM_PHASEMON_BL2_RAW_PHASE`  (Baseline 2 Raw Phase (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:RAW_PHASE_V10_D`   **[MEDIUM]**
      note: Same vector, different index
- [ ] `DSM_PHASEMON_BL3_RAW_PHASE`  (Baseline 3 Raw Phase (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:RAW_PHASE_V10_D`   **[MEDIUM]**
      note: Same vector, different index
- [ ] `DSM_PHASEMON_BL4_RAW_PHASE`  (Baseline 4 Raw Phase (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:RAW_PHASE_V10_D`   **[MEDIUM]**
      note: Same vector, different index
- [ ] `DSM_PHASEMON_BL1_ATMOS`  (Baseline 1 Atmos (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:ATMOSPHERIC_PHASE_V10_D`   **[MEDIUM]**
      note: Same V10-vector-index issue
- [ ] `DSM_PHASEMON_BL2_ATMOS`  (Baseline 2 Atmos (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:ATMOSPHERIC_PHASE_V10_D`   **[MEDIUM]**
      note: Same V10-vector-index issue
- [ ] `DSM_PHASEMON_BL1_RMS_1S`  (Baseline 1 RMS 1s (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:RMS_PHASE_V10_V12_D`   **[MEDIUM]**
      note: Field is V10xV12 (10 baselines x 12 time windows) — needs both baseline AND window index
- [ ] `DSM_PHASEMON_BL1_RMS_16S`  (Baseline 1 RMS 16s (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:RMS_PHASE_V10_V12_D`   **[MEDIUM]**
      note: Same 2D array, different time-window index
- [ ] `DSM_PHASEMON_BL1_RMS_512S`  (Baseline 1 RMS 512s (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:RMS_PHASE_V10_V12_D`   **[MEDIUM]**
      note: Same 2D array, different time-window index

### Vault Voltages (DSM — placeholders)

- [x] `DSM_PHASEMON_VAULT_5V`  (+5V (DSM))
      → proposed: `DSM:phasemon:PHASEMON_HRDWR_STAT_X:POS_5V_RACK_F`   **[HIGH]**
      note: Also NEG_5V_RACK_F, NEG_5V_PAD_V5_F, POS_5VA/B_PAD_V5_F exist — pick correct rail
- [x] `DSM_PHASEMON_VAULT_12V`  (+12V (DSM))
      → proposed: `DSM:phasemon:PHASEMON_HRDWR_STAT_X:POS_12V_RACK_F`   **[HIGH]**
      note: Also POS_12V_PAD_V5_F exists
- [x] `DSM_PHASEMON_VAULT_25V`  (+25V (DSM))
      → proposed: `DSM:phasemon:PHASEMON_HRDWR_STAT_X:POS_25V_RACK_F`   **[HIGH]**
- [x] `DSM_PHASEMON_VAULT_M15V`  (-15V (DSM))
      → proposed: `DSM:phasemon:PHASEMON_HRDWR_STAT_X:NEG_15V_RACK_F`   **[HIGH]**
- [x] `DSM_PHASEMON_VAULT_15VA`  (+15Va (DSM))
      → proposed: `DSM:phasemon:PHASEMON_HRDWR_STAT_X:POS_15VA_RACK_F`   **[HIGH]**
- [x] `DSM_PHASEMON_VAULT_15VB`  (+15Vb (DSM))
      → proposed: `DSM:phasemon:PHASEMON_HRDWR_STAT_X:POS_15VB_RACK_F`   **[HIGH]**
- [x] `DSM_PHASEMON_SYNTH_LOCK`  (SynthLock (DSM))
      → proposed: `DSM:phasemon:PHASEMON_HRDWR_STAT_X:SYNTH_LOCK_B`   **[HIGH]**

---

## `swarm.json`

### ROACH2 Board Temperatures (C) (DSM — placeholders)

- [x] `DSM_ROACH{roach}_TEMP_AMBIENT`  (Ambient (C) (DSM))
      → proposed: `DSM:obscon:ROACH2_{roach}_TEMPS_X:AMBIENT_TEMP_V8_F`   **[HIGH]**
      note: Only ROACH2_1_TEMPS_X through ROACH2_6_TEMPS_X exist under obscon (6 boards), NOT all 48 — separate/duplicate from the DSM:roach2-01..58 __each__ hierarchy. Flag for Marc: which source is authoritative?
- [x] `DSM_ROACH{roach}_TEMP_INLET`  (Inlet (C) (DSM))
      → proposed: `DSM:obscon:ROACH2_{roach}_TEMPS_X:INLET_TEMP_V8_F`   **[HIGH]**
      note: Same 6-board-only caveat as above
- [x] `DSM_ROACH{roach}_TEMP_OUTLET`  (Outlet (C) (DSM))
      → proposed: `DSM:obscon:ROACH2_{roach}_TEMPS_X:OUTLET_TEMP_V8_F`   **[HIGH]**
      note: Same 6-board-only caveat as above
- [x] `DSM_ROACH{roach}_TEMP_PPC`  (PowerPC (C) (DSM))
      → proposed: `DSM:obscon:ROACH2_{roach}_TEMPS_X:PPC_TEMP_V8_F`   **[HIGH]**
      note: Same 6-board-only caveat as above
- [x] `DSM_ROACH{roach}_TEMP_FPGA`  (FPGA (C) (DSM))
      → proposed: `DSM:obscon:ROACH2_{roach}_TEMPS_X:FPGA_TEMP_V8_F`   **[HIGH]**
      note: Same 6-board-only caveat as above
- [ ] `DSM_ROACH{roach}_TEMP_AGE`  (Temp age (DSM))
      → **NO MATCH**
      note: No "age" field; TIMESTAMP_V8_L exists — display would need to compute age from timestamp

### Delays and Walsh Patterns (DSM — placeholders)

- [ ] `DSM_ANT{ant}_DDS_DELAY`  (DDS Delay (ns) (DSM))
      → **NO MATCH**
      note: No per-antenna DDS delay found; DSM:newdds:DDS_TO_TENZING_X:GEOM_DELAY_A/B/C_V9_D are geometry-model delays, not raw DDS delay
- [ ] `DSM_ANT{ant}_FPGA_DELAY`  (FPGA Delay (ns) (DSM))
      → proposed: `DSM:<roach2-idx>:SWARM_FIXED_OFFSETS_X:DELAY_V2_D`   **[LOW]**
      note: Field is per-SWARM-board (roach2-NN), indexed by polarization (V2) — not directly per-antenna
- [ ] `DSM_ANT{ant}_SUM_DELAY`  (Sum Delay (ns) (DSM))
      → **NO MATCH**
      note: No summed-delay field found
- [ ] `DSM_ANT{ant}_WALSH`  (Walsh pattern (DSM))
      → proposed: `DSM:newdds:DDS_TO_HAL_X:WALSH_MOD_V11_V2_S`   **[MEDIUM]**
      note: Also WALSH_DEMOD_V11_V2_S exists — field is V11 (per-antenna) x V2 (mod/demod?) vector
- [ ] `DSM_ANT{ant}_LF_LF`  (LF load factor (DSM))
      → **NO MATCH**
      note: No load-factor field found for SWARM under DSM
- [ ] `DSM_ANT{ant}_LF_HF`  (HF load factor (DSM))
      → **NO MATCH**
      note: Same — no load-factor field found

---

## `ups.json`

### UPS AC Input / Output (DSM — placeholders)

- [x] `DSM_ANT{ant}_UPS_AC_INPUT_V`  (AC Input (V) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:AC_VOLTAGE_IN_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_FREQ_HZ`  (Frequency (Hz) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:AC_FREQUENCY_IN_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_AC_OUTPUT_V`  (AC Output (V) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:AC_VOLTAGE_OUT_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_CURRENT_A`  (Current (A) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:AC_CURRENT_OUT_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_POWER_W`  (Power (W) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:AC_WATTS_IN_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_APPOWER_VA`  (App Power (VA) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:AC_VA_OUT_F`   **[HIGH]**
      note: Also AC_VA_LIMIT_F exists (a threshold, not a reading)

### UPS Battery and Thermal (DSM — placeholders)

- [x] `DSM_ANT{ant}_UPS_BATT_V`  (Battery (V) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:BATTERY_VOLTAGE_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_BATT_I`  (Batt I (A) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:BATTERY_CURRENT_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_LOAD_PCT`  (Load % (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:LOAD_PERCENTAGE_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_RUNTIME`  (Run time (min) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:RUN_TIME_AVAILABLE_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_TEMP_AMB`  (Ambient (C) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:AMBIENT_TEMPERATURE_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_TEMP_HSINK`  (HeatSink (C) (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:HEAT_SINK_TEMPERATURE_F`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_OVERLOADS`  (OverLoads (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:NUMBER_OF_OVERLOADS_S`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_POWER_OUTS`  (Power outs (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:NUMBER_OF_POWER_OUTAGES_S`   **[HIGH]**
- [x] `DSM_ANT{ant}_UPS_ALARMS`  (Active alarms (DSM))
      → proposed: `DSM:acc{ant}:UPS_DATA_X:ACTIVE_ALARMS_L`   **[HIGH]**

---

## `weather.json`

### Multi-Site Weather (DSM — placeholders)

- [x] `DSM_JCMT_TEMP`  (JCMT Temp (C) (DSM))
      → proposed: `DSM:colossus:JCMT_METEOROLOGY_X:TEMP_F`   **[HIGH]**
- [x] `DSM_JCMT_HUMIDITY`  (JCMT Humidity % (DSM))
      → proposed: `DSM:colossus:JCMT_METEOROLOGY_X:HUMIDITY_F`   **[HIGH]**
- [x] `DSM_JCMT_WINDSPEED`  (JCMT Wind (mph) (DSM))
      → proposed: `DSM:colossus:JCMT_METEOROLOGY_X:WINDSPEED_F`   **[HIGH]**
- [x] `DSM_SUBARU_TEMP`  (Subaru Temp (C) (DSM))
      → proposed: `DSM:colossus:SUBARU_METEOROLOGY_X:TEMP_F`   **[HIGH]**
- [x] `DSM_SUBARU_HUMIDITY`  (Subaru Humidity % (DSM))
      → proposed: `DSM:colossus:SUBARU_METEOROLOGY_X:HUMIDITY_F`   **[HIGH]**
- [x] `DSM_UKIRT_TEMP`  (UKIRT Temp (C) (DSM))
      → proposed: `DSM:colossus:UKIRT_METEOROLOGY_X:TEMP_F`   **[HIGH]**
- [x] `DSM_TAU225_GFS`  (Tau225 GFS (DSM))
      → proposed: `weather:forecast:gfs:tau225`   **[HIGH]**
      note: Already-validated existing smax.json entry (predates this merge)
- [x] `DSM_TAU350`  (Tau350 (DSM))
      → proposed: `DSM:colossus:DSM_CSO_350MICRON_TAU_SCALED_F`   **[HIGH]**

### Per-Antenna Skydip Age and Tau (DSM — placeholders)

- [ ] `DSM_ANT{ant}_SKYDIP_AGE`  (Skydip age (DSM))
      → **NO MATCH**
      note: No per-antenna skydip-age field found in DSM
- [ ] `DSM_ANT{ant}_TAU_FREQ`  (Tau at freq (DSM))
      → **NO MATCH**
      note: No per-antenna tau-at-frequency field found
- [ ] `DSM_ANT{ant}_TAU225`  (Tau225 (DSM))
      → **NO MATCH**
      note: ANT_WEATHER_DATA_X (per-antenna, V9) has HUMIDITY/PRESSURE/TEMPERATURE only, not tau225 — no real candidate found

---

