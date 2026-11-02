# `site/`: offsite mirror of `/global` and `/otherInstances`

The SMA C code reads site files at fixed absolute paths such as
`/global/configFiles/rxtype.conf`. On-site those are live mounts; offsite
they don't exist. This directory is a partial copy laid out as a fake
filesystem root, so `/global/configFiles/rxtype.conf` lives at
`site/global/configFiles/rxtype.conf`.

Code never opens these files directly. It calls
`slama.site_paths.site_path("/global/...")` (or `"/otherInstances/..."`),
which re-roots the path, and
the parsers in `slama.sitefiles` port the C readers (and their quirks).

## Which root is used

Chosen once per process for each tree (`slama.site_paths.site_root(tree)`),
logged at INFO:

1. `$SLAMA_SITE_ROOT` if set (`/` = live), for both trees. The compute CLI
   and web server also take `--site-root DIR`, which sets it.
2. `/` if the tree's marker is a directory: `/global/configFiles` for
   `/global`, `/otherInstances/acc` for `/otherInstances` (on-site).
3. This directory.

The test suite always pins the root to this directory (`conftest.py`), so
results don't depend on the live files when run on-site.

If the two trees end up with different roots (e.g. a host that mounts
`/global` but not `/otherInstances`), a WARNING is logged: on-site it
means these mirror copies are standing in for live files.

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
| `global/configFiles/fire/ignoreAntSmoking.txt` | `@smokeIgnore:` | All zeros (no antenna ignored). A missing file means nothing is ignored. |
| `global/polar/ser7.dat` | not yet | Only the mtime matters |
| `global/projects/antennasInArray` | not yet | Empty at copy time (no project running) |
| `otherInstances/acc/{1..8}/configFiles/pointingModel` | `@tiltDefault:` | `TiltFlag 0 0` on every antenna. A missing file means default 0, with a warning. |
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

The `@rxtype:` / `@loadtype:` / `@dewarTemp:` / `@wselect:` /
`@smokeIgnore:` / `@tiltDefault:` tokens are specified in `docs/source/monitorsystem_writer_design.md`
§9. A config that reads a file through one of them fails to load if that
file is missing, instead of silently dropping antennas. The exceptions are
`@smokeIgnore:`, which falls back to "ignore nothing", and `@tiltDefault:`,
which falls back to a default of 0.
