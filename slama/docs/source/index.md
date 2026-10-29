# SLAMA developer guide

SLAMA is the SMA monitor, fault, alarm and web-display package. It reads
telemetry that the observatory's real-time systems publish into SMAX
(a Redis/Valkey database), derives higher-level health information from it,
decides which failures matter, and serves live pages to browsers.

This guide is for a new team member. It explains how the pieces fit
together, how to run a development system on one machine, and how to test
your changes.

## Where to start

1. [Getting started](getting-started.md): install, bring up a local dev
   system, run the tests.
2. [Architecture](architecture.md): the data flow and the three long-running
   processes.
3. The subsystem guides, in the order data flows through them:
   [Monitor system](monitor-system.md), [Fault system](fault-system.md),
   [Display system](display-system.md).
4. [Replaying a snapshot with `--as-of`](replay-as-of.md): why a development
   database looks "dead", and how to work with it.
5. [Testing](testing.md): what the test suite covers and the conventions it
   follows.

```{toctree}
:maxdepth: 2
:caption: Guides

getting-started
architecture
monitor-system
monitorsystem_writer_design
fault-system
display-system
web_display_design
curses_color_validity
replay-as-of
testing
```

```{toctree}
:maxdepth: 2
:caption: Reference

api
records/index
```
