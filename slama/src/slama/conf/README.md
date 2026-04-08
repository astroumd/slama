
- smax.json is a specification of the SMA redis database. Any live version of the database may not contain all this information because the programs writing to the database are not writing all the metadata, e.g. "description"

- Repeated subsystems can be expressed concisely with an `__each__` block
  instead of copying the same subtree under every sibling key. The reserved
  key `__each__` on a branch takes a dict with two fields:

    - `over`: a comma-separated index spec. Each token is a single value or
      a `lo-hi` numeric range (inclusive). Examples: `"1-8"`, `"1-3,5,7-9"`,
      `"H,V"`. The `:` character is reserved as the SMAX path separator and
      is not used here.
    - `template`: the subtree to instantiate once per index value, with the
      index used as the child key.

  `__each__` blocks may nest. Example:

  ```json
  "antenna": {
    "__each__": {
      "over": "1-8",
      "template": {
        "air": { "heater": { "smax_type": "int", "size": "1" } }
      }
    }
  }
  ```

  is equivalent to writing `"1": {...}, "2": {...}, ..., "8": {...}` by hand.
  Expansion happens in `MonitorSystem._build_tree` (`monitor/monitorsystem.py`).

- write a program that checks the specification against the database and reports
missing on either side.  its easy to put junk (test, typos)) in the DB and it stays there forever unless removed.

- part of database validation could be set the active field. if in database and in json database file then it is considered active

- logging to postgress should also use this json and not log anything not in the json (Ram's problem)

size : []  = scalar
size : [1] = array size of one
size : [N] = array size of N

float = platform default
float64 = require 64 bits
