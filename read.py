import board
import busio
from time import sleep

import argparse
parser = argparse.ArgumentParser()

parser.add_argument('--si7', default=False, action='store_true', help='Read from SI7021 sensor; default: HTU21D')
parser.add_argument('n', default=0, nargs='?', type=int, help='Number of iterations to run for; default: 0 (⟹infinite)')
parser.add_argument('-i', '--interval', default=1, type=float, help='Sleep interval between polls, in seconds')

args = parser.parse_args()

i2c = busio.I2C(board.SCL, board.SDA)

sensor = None
if args.si7:
	from adafruit_si7021 import SI7021
	sensor = SI7021(i2c)
else:
	from adafruit_htu21d import HTU21D
	sensor = HTU21D(i2c)

interval = args.interval

def loop():
     print("temp: %0.1f C, humidity: %0.1f" % (sensor.temperature, sensor.relative_humidity))
     sleep(interval)

n = args.n
if not n:
	while (True):
		loop()
else:
	for i in range(n):
		loop()
