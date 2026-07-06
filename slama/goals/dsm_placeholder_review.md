# DSM Placeholder → Real Canonical Name Review

Generated from cross-referencing `dsm:placeholder:DSM_*` strings in
`src/slama/conf/displays/*.json` against the refreshed `conf/smax.json`
(post `smax_from_valkey.py --merge --overwrite` update).

**146 placeholder occurrences across 19 files.** Each entry below is tagged:

- **HIGH** — field name/semantics match closely, likely correct as-is
- **MEDIUM** — plausible match but multiple candidate fields exist, or a caveat applies (units, indexing, node ambiguity)
- **LOW** — weak match, likely wrong; included only as a starting point
- **NO MATCH** — no corresponding field found in current `smax.json`; may not exist in Valkey yet, or needs a different namespace

**Nothing has been changed in the display JSON files yet.** Check off or edit
each line, then let Claude know which mappings to apply.

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
      → proposed: `DSM:corcon:CORR_PACU_STATUS_X:COMPRESSOR_1_ALARM_B`   **[MEDIUM]**
      note: Also COMPRESSOR_1_STAGE_A_B / STAGE_B_B exist — pick alarm vs stage status
- [ ] `DSM_AC_COMPRESSOR2`  (Compressor 2 (DSM))
      → proposed: `DSM:corcon:CORR_PACU_STATUS_X:COMPRESSOR_2_ALARM_B`   **[MEDIUM]**
      note: Also COMPRESSOR_2_STAGE_A_B / STAGE_B_B exist
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
      → **NO MATCH**
      note: DUT1 (delta-UT) not found in DSM; may live in "reference" or "telescope" namespace, or not tracked at all
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
      → **NO MATCH**
      note: BDC_X has no VVA/VGA field (only AR1/AR2/AT20/AT21 attenuator fields)
- [ ] `DSM_BDC_8_12_ATTN`  (Attn setting (DSM))
      → proposed: `DSM:obscon:BDC_X:DSM_BDC_AR1_CTRL_READBACK_V8_F`   **[LOW]**
      note: Multiple attenuator fields exist: AR1, AR2, AT20, AT21

### BDC 10-12 GHz (DSM — placeholders)

- [ ] `DSM_BDC_10_12_DET_V_CH1`  (Det voltage ch1 (DSM))
      → proposed: `DSM:obscon:BDC1012_X:DSM_BDC_AR1_DETECTOR_READBACK_V8_F`   **[MEDIUM]**
- [ ] `DSM_BDC_10_12_DET_V_CH2`  (Det voltage ch2 (DSM))
      → proposed: `DSM:obscon:BDC1012_X:DSM_BDC_AR2_DETECTOR_READBACK_V8_F`   **[MEDIUM]**
- [ ] `DSM_BDC_10_12_ATTN`  (Attn setting (DSM))
      → proposed: `DSM:obscon:BDC1012_X:DSM_BDC_AR1_CTRL_READBACK_V8_F`   **[LOW]**
      note: Multiple attenuators exist: AR1, AR2, AT20, AT21

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
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:CORR_AMPLITUDE_V10_D`   **[MEDIUM]**
      note: Field is a 10-element vector (one per baseline, V10) — need to pick index or aggregate
- [ ] `DSM_FRINGE_PHASE`  (Fringe phase (deg) (DSM))
      → proposed: `DSM:phasemon:PHASEMON_DATA_X:RAW_PHASE_V10_D`   **[MEDIUM]**
      note: Same V10-vector issue as above
- [ ] `DSM_COHERENCE_PCT`  (Coherence (%) (DSM))
      → **NO MATCH**
      note: No direct coherence-percent field found under phasemon
- [ ] `DSM_BASELINE_M`  (Baseline (m) (DSM))
      → **NO MATCH**
      note: Baseline length in meters not found in DSM; likely a static/geometric value from telescope or antenna namespace, not phasemon
- [ ] `DSM_COHERENCE_INTEG`  (Integration (s) (DSM))
      → **NO MATCH**
      note: No integration-time field found for coherence
- [ ] `DSM_FRINGE_TIMESTAMP`  (Last update (DSM))
      → **NO MATCH**
      note: No timestamp field under phasemon:PHASEMON_DATA_X

---

## `croom_iflo.json`

### iFLO LO Lock and IF Power (DSM — placeholders)

- [ ] `DSM_ANT{ant}_IFLO_LO_LOCK`  (LO lock status (DSM))
      → proposed: `DSM:hal9000:DSM_AS_IFLO_ANT2YIG_V2_V11_B`   **[LOW]**
      note: Field is a V11 vector (antenna-indexed within one value), not naturally a per-{ant} template point — may need array indexing support
- [ ] `DSM_ANT{ant}_IFLO_IF_POWER`  (IF power (DSM))
      → proposed: `DSM:m5:C1DC_STATUS_X:IF_POWER_V3_V9_F`   **[MEDIUM]**
      note: Field is per-downconverter (V3xV9), not simply per-antenna; needs index mapping
- [ ] `DSM_ANT{ant}_IFLO_LO_FREQ`  (LO freq (GHz) (DSM))
      → proposed: `DSM:hal9000:DSM_AS_IFLO_REST_FR_V2_D`   **[LOW]**
      note: Rest frequency, global not per-antenna; alternative: antenna:{ant}:lo:1:ref_109_mhz or ref_200_mhz structures
- [ ] `DSM_ANT{ant}_IFLO_TIMESTAMP`  (Last update (DSM))
      → **NO MATCH**
      note: No per-antenna IFLO timestamp found

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
      → proposed: `DSM:colossus:GPSD_REPORT_X:GPS8_CTL_STATUS_B`   **[MEDIUM]**
      note: Also GPS8_OUT_STATUS_B, GPS8_PHASE_FREQ_STATUS_B exist — pick correct lock indicator
- [ ] `DSM_TRUETIME_LOCK_STATUS`  (TrueTime lock (DSM))
      → proposed: `DSM:m5:MRG_STATUS_X:52MHZ_LOCK_S`   **[LOW]**
      note: No TrueTime-specific field found; MRG lock status is a loose proxy
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
      → **NO MATCH**
      note: "Genset" (diesel generator) not found in DSM; DSM:colossus:PACU_INST_POWER_X:W_S / PACU_POWER_STATS_X exist but those are AC-unit power draw, not a generator — confirm terminology with team
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
      → proposed: `reference:mrg:1:set_frequency`   **[MEDIUM]**
      note: Field is in Hz (int32), not GHz — needs unit conversion in display code
- [x] `DSM_YIG_LOCK_STATUS`  (YIG lock status (DSM))
      → proposed: `reference:mrg:1:yig:is_locked`   **[HIGH]**
      note: Validated existing smax.json entry (not new from Valkey); alternative per-antenna: antenna:{ant}:lo:1:yig:is_locked
- [x] `DSM_YIG_TUNE_WORD`  (YIG tune word (DSM))
      → proposed: `reference:mrg:1:yig:v_tune`   **[HIGH]**
      note: "Tune word" = "tuning voltage" field; alternative per-antenna: antenna:{ant}:lo:1:yig:v_tune

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

- [x] `DSM_MRG_LOCK_STATUS`  (Lock status (DSM))
      → proposed: `reference:mrg:1:yig:is_locked`   **[HIGH]**
      note: Validated existing smax.json entry
- [ ] `DSM_MRG_FREQ_GHZ`  (Freq (GHz) (DSM))
      → proposed: `reference:mrg:1:set_frequency`   **[MEDIUM]**
      note: Field is in Hz (int32), not GHz — needs unit conversion (divide by 1e9)
- [x] `DSM_MRG_TUNE_WORD`  (Tune word (DSM))
      → proposed: `reference:mrg:1:yig:v_tune`   **[HIGH]**
      note: "Tune word" = "tuning voltage"
- [ ] `DSM_MRG_PHASE_ERROR`  (Phase err (DSM))
      → proposed: `reference:mrg:1:residue`   **[MEDIUM]**
      note: "Sub-Hertz residue to be tracked by DDS" — plausible proxy for phase error, needs Marc confirmation
- [ ] `DSM_MRG_POWER_DBM`  (Power (dBm) (DSM))
      → **NO MATCH**
      note: No dBm power reading found at the global MRG level (antenna:{ant}:lo:1:yig:rf_power exists per-antenna but this cell is not templated)
- [ ] `DSM_MRG_TIMESTAMP`  (Last update (DSM))
      → **NO MATCH**
      note: No timestamp field found for MRG status

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
      → **NO MATCH**
      note: No MIR-file field found under hal9000/oldhal
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

