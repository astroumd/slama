#!/usr/bin/env python
import redis
import argparse
progname = "SMA monitor system simulator"

parser = argparse.ArgumentParser(prog=progname, description="Dump the full keys and, optionally, values of the SMA database")
parser.add_argument("--flat", "-f", action="store_true", help="write flat list of monitor points", default=False)
parser.add_argument("--strip", "-s", action="store_true", help="strip the top table enclosed in <> if it is present", default=False)
parser.add_argument("--values", "-v", action="store_true", help="also print the values of the leaves", default=False)
args = parser.parse_args()


r = redis.Redis(host='localhost', port=6380, db=0)
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
    for k, v in sorted(dump.items()):
        top = '%s' % k.decode()
        if args.strip:
            start = top.find('<')
            if start != -1:
                stop = top.find('>')
                top = top[stop+2:]  # remove '>:'

        if type(v) == dict:
            for kk, vv in sorted(v.items()):
                middle = '%s' % kk.decode()
                if type(vv) == dict:
                    for kkk, vvv in sorted(v.items()):
                        bottom = '%s' % kkk.decode()
                        if bottom.startswith(':'):
                            bottom = bottom[1:]
                        if top.strip() != "":
                            if args.values:
                                print('%s:%s:%s=%s' % (top, middle, bottom, vvv.decode()))
                            else:
                                print('%s:%s:%s' % (top, middle, bottom))
                        else:
                            if args.values:
                                print('%s:%s=%s' % (middle, bottom, vvv.decode()))
                            else:
                                print('%s:%s' % (middle, bottom))
                else:
                    if top.strip() != "":
                        if args.values:
                            print('%s:%s=%s' % (top, middle, vv.decode()))
                        else:
                            print('%s:%s' % (top, middle))
                    else:
                        if args.values:
                            print('%s=%s' % (middle, vv.decode()))
                        else:
                            print('%s' % middle)
        else:
            if args.values:
                print('%s=%s' % (top, v.decode()))
            else:
                print(top)
else:
    for k, v in sorted(dump.items()):
        top = '%s' % k.decode()
        if args.strip:
            start = top.find('<')
            if start != -1:
                stop = top.find('>')
                top = top[stop+2:]  # remove '>:'
        print(top)
        if type(v) == dict:
            for kk, vv in sorted(v.items()):
                print('\t%s' % kk.decode())
                if type(vv) == dict:
                    for kkk, vvv in sorted(v.items()):
                        print('\t\t%s' % kkk.decode())
