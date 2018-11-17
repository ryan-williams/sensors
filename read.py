import board
import busio
from datetime import datetime
from pytz import timezone
from socket import gethostname
from sys import stderr
from time import mktime, sleep

from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBServerError

from requests.exceptions import ConnectionError

import argparse
parser = argparse.ArgumentParser()

parser.add_argument('--si7', default=False, action='store_true', help='Read from SI7021 sensor; default: HTU21D')
parser.add_argument('n', default=0, nargs='?', type=int, help='Number of iterations to run for; default: 0 (⟹infinite)')
parser.add_argument('-i', '--interval', default=1, type=float, help='Sleep interval between polls, in seconds')
parser.add_argument('-d', '--device', default=gethostname(), help='Device ID')

args = parser.parse_args()

client = InfluxDBClient('raspberrypi', 8086, database='temps')

i2c = busio.I2C(board.SCL, board.SDA)

sensor = None
if args.si7:
	from adafruit_si7021 import SI7021
	sensor = SI7021(i2c)
else:
	from adafruit_htu21d import HTU21D
	sensor = HTU21D(i2c)

interval = args.interval
device = args.device

points = []

def loop():
	global points
	now = datetime.now(timezone('UTC')).strftime('%Y/%m/%d %H:%M:%S.%f')
	temp = sensor.temperature
	humidity = sensor.relative_humidity
	point = \
		{
			"measurement": "temps",
			"time": now,
			"tags": { "device": device	},
			"fields": {
				"temp": temp,
				"humidity": humidity
			}
		}

	points += [ point ]

	try:
		if not client.write_points(points):
			stderr.write('Failed point (x%d): %s\n' % (len(points), point))
		else:
			print("time: %s, temp: %0.1f C, humidity: %0.1f" % (now, temp, humidity))
			points = []
	except InfluxDBServerError as e:
		stderr.write('Failed point (x%d; server): %s\n%s' % (len(points), point, e))
	except ConnectionError as e:
		stderr.write('Failed point (x%d; server connection): %s\n%s' % (len(points), point, e))

	sleep(interval)

print('(stdout) Logging metrics as %s' % device)
stderr.write('(stderr) Logging metrics as %s\n' % device)

n = args.n
if not n:
	while (True):
		loop()
else:
	for i in range(n):
		loop()
