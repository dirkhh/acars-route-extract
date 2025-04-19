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
import json
import socket
import sys
import time
from callsign import Callsigns
from checkroute import Routes


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
                if f[1] == f0[1]:
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
                    d = abs(t[0] - t0[0])
                    if d == 3 or d == 4:
                        route.append([t0[1], t[1], d])
                threes = threes[1:]

        # find the airport symbol pairs that are closest
        if not route == []:
            closest_pair = min(route, key=lambda x: x[2])
            route = [[r[0], r[1]] for r in route if r[2] == closest_pair[2]]

        if self.showtime:
            print(f"checked in {time.time() - now}")
        return route


class ACARS:
    def __init__(self, verbose=False, showtime=False):
        self.gbuf = ""
        self.parser = Parser(showtime)
        self.c = Callsigns()
        self.r = Routes()
        self.verbose = verbose
        # open the file route-pairs.txt and read the pairs
        # that are comma separated in the file into an array of pairs
        with open("route-pairs.txt", "r") as f:
            self.routepairs = set(r.strip() for r in f)

    def handle_json(self, js):
        try:
            jo = json.loads(js)
        except Exception as e:
            if self.verbose:
                print(f"json.loads failed: {e} -- {js}")
            return
        route_array = []
        # print(f"json.loads gets us {jo}")
        if "vdl2" in jo:
            search_string = json.dumps(jo.get("vdl2").get("avlc"))
            if self.verbose:
                print(f"--> {search_string}")
            route_array = self.parser.check_for_route(search_string)
            a = {}
            flight = "no callsign / hex"
            dst_airport = ""
            if "avlc" in jo.get("vdl2"):
                avlc = jo.get("vdl2").get("avlc")
                src = avlc.get("src")
                flight = f"hex:{src.get('addr')}"
                if "acars" in avlc:
                    a = jo.get("vdl2").get("avlc").get("acars")
                    if "flight" in a:
                        flight = a.get("flight")
                        callsign = self.c.validate_callsign(flight)
                        if callsign:
                            flight = callsign
                    if "xid" in a:
                        vp = a.get("xid").get("vdl_params")
                        if vp:
                            for [k, v] in vp.items():
                                if k == "dst_airport":
                                    dst_airport = f"declared destination: {v}"
        route_set = set(f"{r[0]},{r[1]}" for r in route_array)
        known_routes = route_set.intersection(self.routepairs)
        if len(known_routes) > 0:
            route_array = [r for r in route_array if f"{r[0]},{r[1]}" in known_routes]
            if self.verbose or len(route_array) > 1:
                print(f"{flight}: route {route_array} {dst_airport} from label {a.get('label')}")
            if len(route_array) == 1:
                self.r.check_route(flight, route_array, self.verbose)
        elif self.verbose and len(route_array) > 0:
            print(f"{flight}: unlikely route {route_array} {dst_airport} from label {a.get('label')}")

    def add_data(self, d):
        self.gbuf += d
        # this assumes well formed json
        i = self.gbuf.find("{")
        if i == -1:
            print("no opening { -- that's weird")
            return
        elif i > 0:
            self.gbuf = self.gbuf[i:]
        # find the matching closing '}' in order to hand of one json object
        open = 1
        i = 0
        while open > 0:
            oi = self.gbuf.find("{", i + 1)
            ci = self.gbuf.find("}", i + 1)
            if oi == -1 and ci == -1:
                # print("partial json, keep waiting")
                return
            if -1 < oi and oi < ci:
                open += 1
                i = oi
                continue
            if -1 < ci:
                open -= 1
                i = ci
                continue

        # print(f"this should be a valid json expression {self.gbuf[0:i+1]}")
        self.handle_json(self.gbuf[0 : i + 1])
        self.gbuf = self.gbuf[i + 1 :] if len(self.gbuf) > i + 1 else ""


if __name__ == "__main__":
    acarshost = ""
    acarsport = 15555
    verbose = False
    showtime = False
    for arg in sys.argv:
        if arg.startswith("--host="):
            acarshost = arg.split("=")[1]
        if arg.startswith("--port="):
            acarsport = arg.split("=")[1]
        if arg == "-v":
            verbose = True
        if arg == "--showtime":
            showtime = True
        if arg == "--help":
            print(f"Usage: {sys.argv[0]} [--host=acars_host] [--port=acars_port] [-v] [--showtime] [--help]")
            exit(0)
    a = ACARS(verbose, showtime)
    if acarshost != "":
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ip = socket.gethostbyname(acarshost)
        client.connect((ip, acarsport))
        # loop over the data from the JSON socket
        while True:
            data = client.recv(1024)
            a.add_data(data.decode())
    else:
        # loop over the data from stdin
        for line in sys.stdin:
            a.add_data(line)
