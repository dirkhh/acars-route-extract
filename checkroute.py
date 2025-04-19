import csv
import glob


class Routes:
    def __init__(self):
        self.routes = {}
        self.airports = Airports()
        self.route_path = "./standing-data/routes/schema-01"
        self.route_files = glob.glob(self.route_path + "/**/*.csv", recursive=True)
        # open and read each csv file
        for file in self.route_files:
            with open(file, "r", newline="") as csvfile:
                reader = csv.reader(csvfile, delimiter=",", quotechar='"')
                for row in reader:
                    self.routes[row[0]] = row[4]

    def check_route(self, callsign, _route, verbose=False):
        known = self.routes.get(callsign)
        route = f"{self.airports.make_ICAO(_route[0][0])}-{self.airports.make_ICAO(_route[0][1])}"
        if not known:
            print(f"{callsign} -> {route} : was unknown")
        else:
            if route not in known:
                print(f"{callsign} -> {route} : previously known: {known}")
            elif verbose:
                print(f"{callsign} -> {route} : {known}")


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
