#
# brute force extraction of aircraft routes from ACARS traffic
# we could also call it "AI" to make it sound cooler
#
# because of lack of data to play with, so far this is only looking
# at VDL2 messages - having looked at messages online I'm guessing
# that this would work on other types as well, but I haven't tried

# SPDX-License-Identifier: AGPL-3.0
# Copyright 2025 Dirk Hohndel

import ahocorasick
import orjson as json
import os
import redis
import socket
import sys
import threading
import time
from callsign import Callsigns
from checkroute import Routes
from dotenv import load_dotenv


# a simple Aho-Corasick search class
class Parser:
    def __init__(self, showtime=False):
        # import the airport list (extracted from VRS standing data) and initialize
        # the Aho-Corasick automaton
        self.showtime = showtime
        if self.showtime:
            now = time.time()
        self.automaton = automaton = ahocorasick.Automaton()
        with open("./route-airports.txt", "r") as f:
            for line in f:
                self.automaton.add_word(line.strip(), line.strip())
        self.automaton.make_automaton()
        if self.showtime:
            print(f"prepared in {time.time() - now}")

    def check_for_route(self, s):
        if self.showtime:
            now = time.time()
        res = []
        route = []
        # find all instances of 3 or 4 letter airport codes in the raw text
        for m, v in self.automaton.iter(s):
            res.append((m, v))
        # we assume that both origin and destination will be either 3 or 4 letter codes, but
        # not mixed. And if we find two 4 letter codes close to each other, we don't even
        # bother looking for 3 letter codes.
        # in all the data I looked at where the routes seemed to be obvious to the human eye,
        # the pattern was KPDXKSEA (so directly next to each other), KPDX#KSEA (or some other
        # single character separator), or in rare cases KPDX, KSEA (two character separator)
        # that last type seems to create a lot of false positives, so it might be worth ignoring
        # those unless the characters between appear to be separators
        # The position values returned by the automaton are for the last character of the
        # search string, so the distance value are adjusted accordingly
        fours = [r for r in res if len(r[1]) == 4]
        while len(fours) > 1:
            f0 = fours[0]
            for f in fours[1:]:
                # no flights just back to where you came from
                if f[1] == f0[1]:
                    continue
                # if the first airport is prefixed with /WR this appears to be some warning about
                # the continuing legs after the current flight (seen this on several AAL flights)
                if f0[0] > 7 and s[f0[0] - 6 : f0[0] - 3] == "/WR":
                    continue
                d = abs(f[0] - f0[0])
                if d == 4 or d == 5:
                    route.append([f0[1], f[1], d])
                if d == 6:
                    # questionable - but let's take it if the two characters between aren't letters
                    sample = s[f0[0] - 3 : f[0]]
                    if not sample[4].isalpha() and not sample[5].isalpha():
                        # print(f"took questionable: {sample}")
                        route.append([f0[1], f[1], d])
                    # else:
                    #     print(f"rejected questionable: {sample}")
            fours = fours[1:]
        # if we didn't find any 4 letter codes, we look for 3 letter codes
        # for these we only look for zero or one character between the codes
        # way too many false positives with two characters between them
        if len(route) == 0:
            threes = [r for r in res if len(r[1]) == 3]
            while len(threes) > 1:
                t0 = threes[0]
                for t in threes[1:]:
                    if t[1] == t0[1]:
                        continue
                    # same removal of /WR prefixed readings. They appear to usually be in ICAO
                    # notation, but stupidly /WRKSFO,KOAK can be read as SFO,KOA (so interpreted as
                    # three letter airport codes which gets you to Kona, instead of Oakland)
                    if t0[0] > 7 and s[t0[0] - 6 : t0[0] - 3] == "/WR":
                        continue
                    d = abs(t[0] - t0[0])
                    if d == 3 or d == 4:
                        route.append([t0[1], t[1], d])
                threes = threes[1:]

        # find the airport symbol pairs that are closest
        if not route == []:
            closest_pair = min(route, key=lambda x: x[2])
            route = [[r[0], r[1]] for r in route if r[2] == closest_pair[2]]

        if self.showtime:
            print(f"checked in {(time.time() - now):.6f}")
        return route


class ACARS:
    def __init__(self, verbose, showtime, valkey):
        self.gbuf = ""
        self.parser = Parser(showtime)
        self.c = Callsigns()
        self.r = Routes(valkey, verbose)
        self.verbose = verbose
        self.valkey = valkey
        # open the file route-pairs.txt and read the pairs
        # that are comma separated in the file into an array of pairs
        with open("route-pairs.txt", "r") as f:
            self.routepairs = set(r.strip() for r in f)

    def handle_json(self, js, nats):
        try:
            jo = json.loads(js)
        except Exception as e:
            if self.verbose:
                print(f"json.loads failed: {e} -- {js}")
            return
        if self.verbose > 2:
            print(jo)
        route_array = []
        search_string = ""
        if nats and "payload" in jo:
            search_string = jo.get("payload")
            if not search_string.startswith("{"):
                # some plain text message -- ignore for now
                return
            try:
                jo = json.loads(search_string)
            except:
                if self.verbose:
                    print(f"can't parse {jo}")
                return
        if "vdl2" in jo:
            avlc = jo.get("vdl2").get("avlc")
            if not search_string:
                search_string = json.dumps(avlc)
            if self.verbose:
                print(f"--> {search_string}")
            route_array = self.parser.check_for_route(search_string)
            a = {}
            flight = "no callsign / hex"
            dst_airport = ""
            src = avlc.get("src")
            if not src:
                return
            hex = src.get("addr")
            if not hex:
                return
            flight = f"hex:{hex}"
            if "acars" in avlc:
                a = jo.get("vdl2").get("avlc").get("acars")
                if "flight" in a:
                    flight = a.get("flight")
                    callsign = self.c.validate_callsign(flight)
                    if callsign:
                        flight = callsign
                    else:
                        # no point if we don't have a valid callsign
                        return
                else:
                    return
        route_set = set(f"{r[0]},{r[1]}" for r in route_array)
        known_routes = route_set.intersection(self.routepairs)
        if len(known_routes) > 0:
            route_array = [r for r in route_array if f"{r[0]},{r[1]}" in known_routes]
            if self.verbose and len(route_array) > 1:
                print(f"{flight}: route {route_array} {dst_airport} from label {a.get('label')}")
            if len(route_array) == 1:
                self.r.check_route(flight, hex, route_array)
        elif self.verbose and len(route_array) > 0:
            print(f"{flight}: unlikely route {route_array} {dst_airport} from label {a.get('label')}")

    def add_data(self, d, nats):
        self.gbuf += d
        # this assumes well formed json
        i = self.gbuf.find("{")
        if i == -1:
            print(f"no opening {{ -- that's weird -- {self.gbuf}")
            return
        elif i > 0:
            self.gbuf = self.gbuf[i:]
        # objects should be coming in one json object per line
        try:
            jo = json.loads(self.gbuf)
        except:
            if self.verbose:
                print(f"can't parse {self.gbuf} -- trying to recover")
            self.gbuf = ""
            return

        # print(f"this should be a valid json expression {self.gbuf[0:i+1]}")
        self.handle_json(self.gbuf, nats)
        self.gbuf = ""


if __name__ == "__main__":
    acarshost = ""
    acarsport = 15555
    verbose = 0
    showtime = False
    nats = False
    for arg in sys.argv[1:]:
        if arg.startswith("--host="):
            acarshost = arg.split("=")[1]
        elif arg.startswith("--port="):
            acarsport = arg.split("=")[1]
        elif arg == "--nats":
            nats = True
        elif arg == "-v":
            verbose += 1
        elif arg == "--showtime":
            showtime = True
        elif arg == "--help":
            print(f"Usage: {sys.argv[0]} [--host=acars_host] [--port=acars_port] [-v] [--showtime] [--help]")
            exit(0)
        else:
            print(f"unknown argument {arg}")
            print(f"Usage: {sys.argv[0]} [--host=acars_host] [--port=acars_port] [-v] [--showtime] [--help]")
            exit(1)

    load_dotenv()
    valkey_url = os.getenv("VALKEY", "redis://localhost:6379")
    valkey = redis.Redis.from_url(valkey_url)

    a = ACARS(verbose, showtime, valkey)
    if acarshost != "":
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ip = socket.gethostbyname(acarshost)
        client.connect((ip, acarsport))
        # loop over the data from the JSON socket
        while True:
            data = client.recv(4096)
            if verbose:
                print(f"received {len(data)} bytes")
            a.add_data(data.decode())
    else:
        # loop over the data from stdin
        for line in sys.stdin:
            if line.strip() == "":
                continue
            a.add_data(line, nats)
