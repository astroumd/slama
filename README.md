# slama

Bootstrap repo for SMA monitoring, fault, alarm, and web display systems.
There are two parts included, a section for those who need to run their own valkey database, a
and a section for the actual code. 

# Repos of Interest
 
## Required by the code 

These will be installed with ``uv sync``:

* https://github.com/Smithsonian/smax-python
* https://github.com/Smithsonian/smax-json

## Required if running your own valkey server
* https://github.com/Smithsonian/smax-server  (only for the lua files!)
* https://github.com/valkey-io/valkey (the OSS redis)

### Other
Not required but may be of interest.

* https://github.com/Smithsonian/SMA-Software
* https://github.com/Smithsonian/redisx
* https://github.com/Smithsonian/SuperNOVAS
* https://github.com/Smithsonian/supernovas-rpm-spec
* QL reduction pipeline (teuben)
* pyuvdata:  https://github.com/RadioAstronomySoftwareGroup/pyuvdata

### related

* https://github.com/redis/hiredis (the original redis)


## Installation

Installation is covered in INSTALL.md

