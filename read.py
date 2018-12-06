import argparse
import board
import busio
from datetime import datetime
from dotmap import DotMap
from os.path import exists
from pprint import pformat
from pytz import timezone
from socket import gethostname
from sys import stderr
from time import sleep
from urllib.parse import urlparse

from influxdb import InfluxDBClient


parser = argparse.ArgumentParser()

parser.add_argument('--si7', action='store_true', help='Read from SI7021 sensor; default: HTU21D')
parser.add_argument('n', nargs='?', type=int, help='Number of iterations to run for; default: 0 (⟹infinite)')
parser.add_argument('--hist', dest='hist_interval', type=int, help='Sleep interval between printing points-per-server-request histograms, in seconds')
parser.add_argument('-c', '--create-db', dest='create_db', action='store_true', help='When set, attempt to create the database (--db) at startup')
parser.add_argument('-f', '--file', type=str, help='Config file to read values from')
parser.add_argument('-i', '--interval', type=int, help='Sleep interval between polls, in seconds')
parser.add_argument('-r', '--report-interval', type=int, help='Sleep interval between reporting points to server, in seconds')
parser.add_argument('-d', '--device', help='Device ID')
parser.add_argument('--db', help='Database to log metrics to, inside the InfluxDB instance given by --server')
parser.add_argument('-s', '--server', help='InfluxDB server to log metrics to')
parser.add_argument('-n', '--dry-run', action='store_true', help='When set, only log output, but don\'t report to a database')

args_dict = vars(parser.parse_args())

args = DotMap({
	'create_db': False,
  'db': 'temps',
  'device': gethostname(),
  'dry_run': False,
	'file': '/etc/temps/config.json',
  'hist_interval': 60,
	'interval': 1,
  'n': 0,
	'report_interval': 1,
	'report_interval_backoff': 1.2,
	'report_interval_max': 300,
	'server': 'localhost:8086',
  'si7': False,
  'tags': []
})


def update(ctx, base, delta):
	for k, v in delta.items():
		if v == None or v == False:
			continue
		if not k in base:
			raise IOError('Invalid config key "%s": %s' % (k, json.dumps(delta)))
		print('setting from %s: %s → %s' % (ctx, k, v))
		base[k] = v


file = args.file
if exists(file):
	import json
	with open(file, 'r') as f:
		file_config = json.load(f)
		update(file, args, file_config)


update('command-line', args, args_dict)


print('config:\n%s' % pformat(args, indent=2))

device = args.device
dry_run = args.dry_run

i2c = busio.I2C(board.SCL, board.SDA)

sensor = None
if args.si7:
	from adafruit_si7021 import SI7021
	sensor = SI7021(i2c)
else:
	from adafruit_htu21d import HTU21D
	sensor = HTU21D(i2c)

from queue import Empty, Queue
from threading import Thread

q = Queue()
log_msgs = Queue()

running = True

def drain(q):
	elems = []
	while True:
		try:
			elems.append(q.get_nowait())
		except Empty:
			break
	return elems


def now_str(micros = False):
	fmt = '%Y/%m/%d %H:%M:%S.%f' if micros else '%Y/%m/%d %H:%M:%S'
	return datetime.now(timezone('UTC')).strftime(fmt)


def sensor_reader():
	interval = args.interval
	since_error = 0
	points = []
	n = 0
	while (not args.n or n < args.n):
		now = now_str(micros = True)
		try:
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

			q.put(point)

			if since_error < 60 or since_error % 10 == 0:
				print("%d: %s %0.1f C %0.1f%%" % (n, now, temp, humidity))

			since_error += 1

		except OSError as e:
			if e.errno == 121:
				stderr.write('Failed to read from sensor! %s\n' % e)

		sleep(interval)
		n += 1

	global running
	running = False


def influx_writer():
	from influxdb.exceptions import InfluxDBServerError
	from requests.exceptions import ConnectionError

	interval = args.report_interval
	backoff = 1.2
	max_interval = 300
	failing_since = None
	server = urlparse('tcp://%s' % args.server)
	def make_client():
		return InfluxDBClient(
		host = server.hostname,
		port = server.port if server.port else 8086,
		username = server.username,
		password = server.password,
		database = args.db
	)
	client = make_client()

	if args.create_db:
		client.create_database(args.db)
		print('Made database %s' % args.db)

	while running:
		points = drain(q)
		if points:
			try:
				if client.write_points(points):
					log_msgs.put({ 'size': len(points) })
					interval = args.report_interval
				else:
					if not failing_since:
						failing_since = points[0]['time']

					stderr.write('%d failed points (influx library failure; since %s)' % (len(points), failing_since))
			except Exception as e:
				[ q.put(point) for point in points ]
				if not failing_since:
					failing_since = points[0]['time']

				stderr.write('%d failed points (since %s):\n%s' % (len(points), failing_since, e))

				tpe = type(e)
				if tpe == InfluxDBServerError or tpe == ConnectionError:
					interval = min(max_interval, interval * backoff)
					stderr.write('resetting client; new interval: %ds\n' % int(interval))
					client.close()
					client = make_client()

		sleep(int(interval))


def points_size_hist_printer():
	hist = {}
	while running:
		cur = {}
		msgs = drain(log_msgs)
		n = 0
		for msg in msgs:
			if 'size' in msg:
				size = msg['size']
				n += size
				if not size in cur:
					cur[size] = 0
				cur[size] += 1
				if not size in hist:
					hist[size] = 0
				hist[size] += 1

		def hist_str(hist):
			items = list(hist.items())
			items.sort(key=lambda t: t[0])
			return ' '.join([ '%dx%d' % (k, v) for k, v in items ])

		print(
			'%d reported points: recent %s, all time %s' % (
				n,
				hist_str(cur),
				hist_str(hist)
			)
		)

		sleep(args.hist_interval)


msg = \
	'Logging metrics to %s/%s as %s%s' % (
		args.server,
		args.db,
		device,
		' (dry run)' if dry_run else ''
	)

print('(stdout) %s' % msg)
stderr.write('(stderr) %s\n' % msg)

threads = [ Thread(target=sensor_reader) ]
if not args.dry_run:
	threads += [
		Thread(target=influx_writer),
		Thread(target=points_size_hist_printer)
	]

for t in threads:
	t.start()

for t in threads:
	t.join()
