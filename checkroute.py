import csv
import glob
import math
import os
import orjson as json
import random
import redis
import requests
import sys
import threading
import time
from dotenv import load_dotenv


def print_err(*args, **kwargs):
    prefix = (
        f"thrid:{threading.get_native_id()}-"
        + time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        + ".{0:03.0f}Z".format(math.modf(time.time())[0] * 1000)
    )
    print(*((prefix,) + args), file=sys.stderr, **kwargs)


class Routes:
    def __init__(self, valkey, verbose):
        if verbose > 0:
            print_err("setting up Routes class")
        self.valkey = valkey
        self.verbose = verbose
        self.routes = {}
        self.airports = Airports()
        self.route_path = "./standing-data/routes/schema-01"
        self.route_files = glob.glob(self.route_path + "/**/*.csv", recursive=True)
        self.callsignCache = {}
        self.lock = threading.Lock()
        self.last_api_call = 0
        # open and read each csv file
        for file in self.route_files:
            with open(file, "r", newline="") as csvfile:
                reader = csv.reader(csvfile, delimiter=",", quotechar='"')
                for row in reader:
                    self.routes[row[0]] = row[4]
        worker = threading.Thread(target=self.run)
        worker.start()

    def run(self):
        if self.verbose > 0:
            print_err("starting checkroute worker")
        while True:
            hexset = set()
            num_routes = min(20, self.valkey.llen("checkroute"))
            if num_routes > 0:
                now = time.time()
                routes = []
                # get rid of duplicate entries
                routestrings = list(set(self.valkey.lpop("checkroute", num_routes)))
                if self.verbose > 1:
                    print_err(f"got {len(routestrings)} routes to check {routestrings}")
                for routestring in routestrings:
                    # first loop through the routes figure out which callsigns we
                    # already have cached the correct flight/callsign for and
                    # which we need to call the api for
                    try:
                        route_object = json.loads(routestring)
                    except:
                        print_err(f"can't parse {routestring}")
                        continue
                    # did we recently look at this? don't do it again
                    found_callsign = route_object.get("found_callsign")
                    hex = route_object["hex"]
                    cached = self.valkey.get(f"{found_callsign}-{hex}")
                    if cached:
                        if self.verbose > 1:
                            print_err(
                                f"checking {found_callsign}-{hex} with route {route_object.get('route')} -- {cached.decode('utf-8')}"
                            )
                        if cached.decode("utf-8") == route_object.get("route"):
                            continue
                    routes.append(route_object)
                    flight, validUntil = self.callsignCache.get(hex, (None, 0))
                    if validUntil < now:
                        hexset.add(hex)
                if len(hexset) > 0:
                    # look up the current callsigns from the adsb.fi api with one single call
                    while time.time() - self.last_api_call < 5:
                        time.sleep(1)
                    with self.lock:
                        ac = self.get_callsign_for_hex_list(",".join(hexset))
                        self.last_api_call = time.time()
                    for aircraft in ac:
                        callsign = aircraft.get("flight")
                        if callsign:
                            callsign = callsign.strip().upper()
                        else:
                            continue
                        hex = aircraft.get("hex").strip().upper()
                        if self.verbose > 1:
                            print_err(f"got {aircraft} with callsign {callsign} for {hex}")
                        # 15 minutes seems like a very short time for the callsign to change
                        self.callsignCache[hex] = (callsign, now + 60 * 15)
                for route_object in routes:
                    # second time around with the routes
                    # we don't check the validUntil because we don't want to
                    # see the situation where between the first loop and this one
                    # a cache entry just expired...
                    hex = route_object["hex"]
                    callsign, _ = self.callsignCache.get(hex, (None, 0))
                    if callsign == None:
                        print_err(f"no callsign for {hex}")
                        continue
                    route = route_object["route"]
                    known = self.routes.get(callsign)
                    if not known:
                        print_err(f"{callsign} -> {route} : was unknown")
                    elif route not in known:
                        print_err(f"{callsign} -> {route} : previously known: {known}")
                    else:
                        if self.verbose:
                            print_err(f"{callsign} -> {route} : ok")
                    # remember this for 15 minutes
                    if self.verbose > 1:
                        print_err(f"remember {route_object.get('found_callsign')}-{hex} == {route} for 15 minutes")
                    self.valkey.set(f"{route_object.get('found_callsign')}-{hex}", route, ex=60 * 15)
            else:
                if self.verbose > 1:
                    print_err("no routes to check")
            # now let's wait for five second so we don't run afoul of the adsb.fi rate limit
            time.sleep(5)

    def get_callsign_for_hex_list(self, hexlist):
        if self.verbose > 1:
            print_err(f"calling adsb.fi for {hexlist.count(',') + 1} hexes")
        response = requests.get(
            f"https://opendata.adsb.fi/api/v2/icao/{hexlist}", headers={"User-Agent": "RouteChecker/adsb.im/v1.0.0"}
        )
        if response.status_code != 200:
            print_err(
                f"error calling adsb.fi on {hexlist} : {response.status_code} - {response.reason} - {response.text}"
            )
            return []
        try:
            jo = response.json()
        except:
            print_err(f"calling adsb.fi on {hexlist} : json error")
            return []
        ac = jo.get("ac")
        if not ac:
            print_err(f"calling adsb.fi on {hexlist} : no ac")
            return []
        return ac

    def check_route(self, callsign, hex, _route):
        known = self.routes.get(callsign)
        route = f"{self.airports.make_ICAO(_route[0][0])}-{self.airports.make_ICAO(_route[0][1])}"
        if not known or route not in known:
            # if we don't have a match, add this to the work queue
            # we first need to check if the callsign is correct for this hex, and
            # we want to do this without blocking the main thread and without running
            # into the adsb.fi rate limit
            if self.verbose > 1:
                print_err(f"{callsign} -> {route} : don't match known routes: {known} -- adding to work queue")
            self.valkey.lpush("checkroute", json.dumps({"found_callsign": callsign, "hex": hex, "route": route}))


class Airports:
    def __init__(self):
        self.airports = {}
        self.airport_path = "./standing-data/airports/schema-01"
        self.airport_files = glob.glob(self.airport_path + "/**/*.csv", recursive=True)
        # open and read each csv file
        for file in self.airport_files:
            with open(file, "r", newline="") as csvfile:
                reader = csv.reader(csvfile, delimiter=",", quotechar='"')
                for row in reader:
                    self.airports[row[3]] = row[2]

    def make_ICAO(self, airport):
        if len(airport) == 3:
            return self.airports.get(airport)
        return airport
