import csv
import glob
import itertools

# specify the directory path
airport_path = "./standing-data/airports/schema-01"
route_path = "./standing-data/routes/schema-01"

# find all csv files in the directory tree
airport_files = glob.glob(airport_path + "/**/*.csv", recursive=True)

airports = set()
lookup = {}
# open and read each csv file
for file in airport_files:
    with open(file, "r", newline="") as csvfile:
        reader = csv.reader(csvfile, delimiter=",", quotechar='"')
        for row in reader:
            airports.add(row[2])
            airports.add(row[3])
            lookup[row[2]] = row[3]

airports.remove("ICAO")
airports.remove("IATA")
airports.remove("")
airports = list(airports)
airports.sort()
print(f"found {len(airports)} airports")

with open("airports.txt", "w") as f:
    for a in airports:
        f.write(f"{a}\n")

route_files = glob.glob(route_path + "/**/*.csv", recursive=True)

routes = set()
route_airports = set()
routepairs = set()
# open and read each csv file
for file in route_files:
    with open(file, "r", newline="") as csvfile:
        reader = csv.reader(csvfile, delimiter=",", quotechar='"')
        for row in reader:
            route = row[4]
            for airport in route.split("-"):
                route_airports.add(airport)
                route_airports.add(lookup.get(airport, ""))
            for pair in itertools.combinations(route.split("-"), 2):
                routepairs.add(",".join(pair))
                if lookup.get(pair[0]) and lookup.get(pair[1]):
                    routepairs.add(",".join([lookup.get(pair[0]), lookup.get(pair[1])]))

            routes.add(",".join(row))

routes = list(routes)
routes.sort()
print(f"found {len(routes)} routes")

route_airports.remove("")
route_airports.remove("AIR")
if "Airportcodes" in route_airports:
    route_airports.remove("Airportcodes")
route_airports = list(route_airports)
route_airports.sort()
print(f"found {len(route_airports)} route airports")
with open("route-airports.txt", "w") as f:
    for r in route_airports:
        f.write(f"{r}\n")

routepairs = list(routepairs)
routepairs.sort()
print(f"found {len(routepairs)} route pairs")
with open("route-pairs.txt", "w") as f:
    for r in routepairs:
        f.write(f"{r}\n")
