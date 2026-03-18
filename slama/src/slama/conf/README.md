
- smax.json is a specification of the SMA redis database. Any live version of the database may not contain all this information because the programs writing to the database are not writing all the metadata, e.g. "description"

- add 'pattern' to explain what each subsystem wildcard means

- write a program that checks the specification against the database and reports
missing on either side.  its easy to put junk (test, typos)) in the DB and it stays there forever unless removed.

- part of database validation could be set the active field. if in database and in json database file then it is considered active

- logging to postgress should also use this json and not log anything not in the json (Ram's problem)

size : []  = scalar
size : [1] = array size of one
size : [N] = array size of N

float = platform default
float64 = require 64 bits
