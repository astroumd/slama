#!/usr/bin/env python
import os
import redis
import argparse

_DEFAULT_HOST = os.environ.get("SMAX_HOST", "localhost")
_DEFAULT_PORT = int(os.environ.get("SMAX_PORT", 6380))


def _decode(b):
    """Decode bytes to str, replacing invalid UTF-8 bytes with '?'."""
    if isinstance(b, bytes):
        return b.decode('utf-8', errors='replace')
    return str(b)


def filter_leaves(paths):
    """Return only paths that are true leaves (not a prefix of any other path).

    A path P is a branch if any other path Q starts with P + ':'. This function
    builds the set of all such branch prefixes in O(n * d) time (where d is the
    maximum path depth) and returns the paths that are not in that set.

    Parameters
    ----------
    paths : list of str
        Colon-separated path strings (e.g. ``["a:b", "a:b:c"]``).

    Returns
    -------
    list of str
        Subset of *paths* containing only true leaves, in original order.
    """
    branches = set()
    for p in paths:
        parts = p.split(":")
        for i in range(1, len(parts)):
            branches.add(":".join(parts[:i]))
    return [p for p in paths if p not in branches]


if __name__ == "__main__":
    progname = "SMA monitor system simulator"

    parser = argparse.ArgumentParser(prog=progname, description="Dump the full keys and, optionally, values of the SMA database")
    parser.add_argument("--flat", "-f", action="store_true", help="write flat list of monitor points", default=False)
    parser.add_argument("--strip", "-s", action="store_true", help="strip the top table enclosed in <> if it is present", default=False)
    parser.add_argument("--values", "-v", action="store_true", help="also print the values of the leaves", default=False)
    parser.add_argument("--host", default=_DEFAULT_HOST, help="Redis/SMAX host (default: $SMAX_HOST or localhost)")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help="Redis/SMAX port (default: $SMAX_PORT or 6380)")
    args = parser.parse_args()

    r = redis.Redis(host=args.host, port=args.port, db=0)
    dump = {}

    # Use SCAN cursor to iterate safely
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, count=1000)
        for key in keys:
            key_type = r.type(key)
            if key_type == b'string':
                dump[key] = r.get(key)
            elif key_type == b'hash':
                dump[key] = r.hgetall(key)
            elif key_type == b'list':
                dump[key] = r.lrange(key, 0, -1)
            elif key_type == b'set':
                dump[key] = r.smembers(key)
            elif key_type == b'zset':
                dump[key] = r.zrange(key, 0, -1, withscores=True)

        if cursor == 0:
            break

    if args.flat:
        # Collect all (path, value_str) pairs first, then filter to true leaves.
        flat = {}  # path -> display value string
        for k, v in sorted(dump.items()):
            top = _decode(k)
            if args.strip:
                start = top.find('<')
                if start != -1:
                    stop = top.find('>')
                    top = top[stop+2:]  # remove '>:'

            if isinstance(v, dict):
                for kk, vv in sorted(v.items()):
                    middle = _decode(kk)
                    path = f"{top}:{middle}" if top.strip() else middle
                    flat[path] = _decode(vv)
            else:
                flat[top] = _decode(v)

        for path in filter_leaves(list(flat.keys())):
            if args.values:
                print(f"{path}={flat[path]}")
            else:
                print(path)

    else:
        for k, v in dict(sorted(dump.items())).items():
            top = _decode(k)
            if args.strip:
                start = top.find('<')
                if start != -1:
                    stop = top.find('>')
                    top = top[stop+2:]  # remove '>:'
            print(top)
            if type(v) == dict:
                for kk, vv in dict(sorted(v.items())).items():
                    print(f'\t{_decode(kk)}')
                    if type(vv) == dict:
                        for kkk, vvv in dict(sorted(v.items())).items():
                            print(f'\t\t{_decode(kkk)}')
