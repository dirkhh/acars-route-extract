import csv
import re


class Callsigns:
    def __init__(self):
        self.airline_data = {}

        # read in the airlines
        try:
            airline_file = open("standing-data/airlines/schema-01/airlines.csv")
        except FileNotFoundError:
            print("standing-data/airlines/schema-01/airlines.csv not found")
        else:
            airline_reader = csv.reader(airline_file, delimiter=",")
            for entry in airline_reader:
                self.airline_data[entry[0]] = entry

    def normalize_callsign(self, _callsign: str):
        """
        normalize a callsign as described in
        https://github.com/vradarserver/standing-data/blob/main/routes/schema-01/README.md
        and break it into airline code and flight number
        :param _callsign: airline callsign from ADS-B
        :return: [code, number] of the normalized callsign
        """
        normalizer_regexp = "^(?P<code>[A-Z]{2,3}|[A-Z][0-9]|[0-9][A-Z])(?P<number>[0-9]+[A-Z]*)$"
        match = re.search(normalizer_regexp, _callsign)
        if not match:
            return ["", ""]
        code = match.group("code")
        number = match.group("number")
        if code not in self.airline_data:
            # maybe this is a IATA code?
            for airline in self.airline_data.keys():
                if self.airline_data[airline][3] == code:
                    code = self.airline_data[airline][2]
                    break
            # maybe it's a silly Delta pilot still thinking they work for Northwest?
            if code == "NW":
                code = "DAL"
        match = re.search("^0+([0-9].*)", number)
        if match:
            number = match.group(1)
        return [code, number]

    def validate_callsign(self, _callsign: str):
        """
        use the standing data to figure out which call signs to accept
        :param: str: callsign of the flight we are checking
        :rtype: str: '' if this is not a callsign we want to bother with, otherwise the normalized callsign
        """
        # first, make sure the callsign is normalized
        code, number = self.normalize_callsign(_callsign)
        if code + number == "":
            return ""
        # is this an airline the standing data knows about
        # if code not in self.airline_data:
        #    print(f"{_callsign} isn't related to known airline")
        #    return ""
        if code in self.airline_data:
            airline_entry = self.airline_data.get(code)
            if airline_entry[5] != "" and re.search(airline_entry[5], number, re.IGNORECASE):
                print(f"{_callsign} matched charter pattern {airline_entry[0]}:{airline_entry[5]}")
                return ""
            if airline_entry[4] != "" and re.search(airline_entry[4], number, re.IGNORECASE):
                print(f"{_callsign} matched position flight pattern {airline_entry[0]}:{airline_entry[4]}")
                return ""

        return code + number
