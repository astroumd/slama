# `site/`: offsite mirror of `/global` and `/otherInstances`

The SMA C code reads site files at fixed absolute paths such as
`/global/configFiles/rxtype.conf`. On-site those are live mounts; offsite
they don't exist. This directory is a partial copy laid out as a fake
filesystem root, so `/global/configFiles/rxtype.conf` lives at
`site/global/configFiles/rxtype.conf`.

Code never opens these files directly. It calls
`slama.site_paths.site_path("/global/...")`, which re-roots the path, and
the parsers in `slama.sitefiles` port the C readers (and their quirks).

## Which root is used

Chosen once per process (`slama.site_paths.site_root()`), logged at INFO:

1. `$SLAMA_SITE_ROOT` if set (`/` = live). The compute CLI and web server
   also take `--site-root DIR`, which sets it.
2. `/` if `/global/configFiles` is a directory (on-site).
3. This directory.

The test suite always pins the root to this directory (`conftest.py`), so
results don't depend on the live files when run on-site.

**Known limitation:** detection checks `/global` only. A host that mounts
`/global` but not `/otherInstances` would look for `/otherInstances` at
the live path. Nothing reads `/otherInstances` yet.

## Contents and provenance

Live copies taken by Marc on 2026-10-20 (file mtimes preserved).

| File | Read by SLAMA | Notes |
|---|---|---|
| `global/configFiles/rxtype.conf` | `@rxtype:` | wSMA on 1, 7, 8; Tune6 on 2–6 |
| `global/configFiles/loadtype.conf` | `@loadtype:` | Same as `rxtype.conf`; antenna 3 is commented "load assembly offline" but coded 0 (Tune6) |
| `global/configFiles/dewarTemp.conf` | `@dewarTemp:` | 4K limit 5.2 K on every antenna |
| `global/configFiles/wselect.conf` | `@wselect:` | Antennas 1, 7, 8: positions G H D L |
| `global/configFiles/phaseMonitorBaselinesSorted` | not yet | SAO seeing |
| `global/configFiles/badPhasemonBaselines` | not yet | SAO seeing |
| `global/configFiles/fire/ignoreAntSmoking.txt` | not yet | All zeros (no antenna ignored) |
| `global/polar/ser7.dat` | not yet | Only the mtime matters |
| `global/projects/antennasInArray` | not yet | Empty at copy time (no project running) |
| `otherInstances/acc/{1..8}/configFiles/pointingModel` | not yet | Tilt-flag defaults |
| `global/configFiles/{choppertype,servo}.conf` | not yet | Extras, not used by arrayMonitor.c |

Kept out of git (`site/.gitignore`): `projects/antennaUser` (people's
names), and the existence-only markers `configFiles/fullPolarization` and
`hiloOverTemperatureAlarm` (neither was present at copy time), and
`configFiles/ups-central.conf` (internal network addresses; this repo is
public).

## Refreshing from the live system

Copy with `cp -p` so modification times survive (some checks, e.g. the
`ser7.dat` age, use only the mtime), then update the table above:

```sh
cp -p /global/configFiles/rxtype.conf site/global/configFiles/
```

A config that reads a file through an `@rxtype:` / `@loadtype:` /
`@dewarTemp:` / `@wselect:` token fails to load if that file is missing, instead of
silently dropping antennas.
