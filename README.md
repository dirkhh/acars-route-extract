# ACARS Route Extract

I'm so tempted to call this AI, just because it's 2025.
But no, this really is just a brute force algorithm to guess route data from ACARS messages

## Documentation

Clone the VTR standing data: `git clone https://github.com/vradarserver/standing-data`
Run prepare the input files: `python3 prep-data.py

Run the parser either against a JSON file with ACARS objects, or against the ACARS json stream from `acarshub` https://github.com/sdr-enthusiasts/docker-acarshub.
`python3 acars-route-parse.py --host localhost --port 15555`
`python3 acars-route-parse.py jsonfile`

`--showtime` will report on the time it takes to parse each message
`-v` shows the raw messages and less likely route results

## Limitations

This so far only parses VLD2 messages and has only been tested with a few hundred messages received around Portland, OR
