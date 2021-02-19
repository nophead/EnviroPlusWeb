# -*- coding: utf-8 -*-
#
# EnviroPlusWeb Copyright Chris Palmer 2019
# nop.head@gmail.com
# hydraraptor.blogspot.com
#
# This file is part of EnviroPlusWeb.
#
# EnviroPlusWeb is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# EnviroPlusWeb is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with EnviroPlusWeb.
# If not, see <https:#www.gnu.org/licenses/>.
#
particle_sensor = True
gas_sensor = True
assert gas_sensor or not particle_sensor # cant have particle sensor without gas sensor
from flask import Flask, render_template, url_for, request
import logging
from bme280 import BME280
try:
    # Transitional fix for breaking change in LTR559
    from ltr559 import LTR559
    ltr559 = LTR559()
except ImportError:
    import ltr559
from enviroplus import gas
from pms5003 import PMS5003, ReadTimeoutError as pmsReadTimeoutError
import threading
from time import sleep, time, asctime, localtime, strftime, gmtime
from math import ceil, floor
import json
import os
import RPi.GPIO as IO
import ST7735
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus

bus = SMBus(1)
bme280 = BME280(i2c_dev=bus) # BME280 temperature, humidity and pressure sensor

pms5003 = PMS5003() # PMS5003 particulate sensor

IO.setmode(IO.BCM)   # Set pin numbering
IO.setup(4,IO.OUT)   # Fan controller on GPIO 4
pwm = IO.PWM(4,1000) # PWM frequency
pwm.start(100)       # Duty cycle

# Create ST7735 LCD display class
st7735 = ST7735.ST7735(
    port=0,
    cs=1,
    dc=9,
    backlight=12,
    rotation=270,
    spi_speed_hz=10000000
)

# Initialize display
st7735.begin()

WIDTH = st7735.width
HEIGHT = st7735.height

# Set up canvas and font
img = Image.new('RGB', (WIDTH, HEIGHT), color=(0, 0, 0))
draw = ImageDraw.Draw(img)

path = os.path.dirname(os.path.realpath(__file__)) + "/fonts"
smallfont = ImageFont.truetype(path + "/Asap/Asap-Bold.ttf", 10)
x_offset = 2
y_offset = 2

units = ["°C",
         "%",
         "mBar",
         "Lux"]
         
if gas_sensor:
    units += [
         "kΩ",
         "kΩ",
         "kΩ"]
         
if particle_sensor:
    units += [
         "/0.ll",
         "/0.1l",
         "/0.1l"]

# Displays all the text on the 0.96" LCD
def display_everything():
    draw.rectangle((0, 0, WIDTH, HEIGHT), (0, 0, 0))
    column_count = 2
    variables = list(record.keys())
    row_count = ceil(len(units) / column_count)
    last_values = days[-1][-1]
    for i in range(len(units)):
        variable = variables[i + 1]
        data_value = record[variable]
        last_value = last_values[variable]
        unit = units[i]
        x = x_offset + (WIDTH // column_count) * (i // row_count)
        y = y_offset + (HEIGHT // row_count) * (i % row_count)
        message = "{}: {:s} {}".format(variable[:4], str(data_value), unit)
        tol = 1.01
        rgb = (255, 0, 255) if data_value > last_value * tol  else (0, 255, 255) if data_value < last_value / tol else (0, 255, 0)
        draw.text((x, y), message, font = smallfont, fill = rgb)
    st7735.display(img)


app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
log = logging.getLogger("werkzeug")
log.disabled = True
run_flag = True

def read_data(time):
    temperature = bme280.get_temperature()
    pressure = bme280.get_pressure()
    humidity = bme280.get_humidity()
    lux = ltr559.get_lux()
    
    if gas_sensor:
        gases = gas.read_all()
        oxi = round(gases.oxidising / 1000, 1)
        red = round(gases.reducing / 1000)
        nh3 = round(gases.nh3 / 1000)
    else:
        oxi = red = nh3 = 0
        
    if particle_sensor:
        while True:
            try:
                particles = pms5003.read()
                break
            except RuntimeError as e:
                print("Particle read failed:", e.__class__.__name__)
                if not run_flag:
                    raise e
                pms5003.reset()
                sleep(30)
                
        pm100 = particles.pm_per_1l_air(10.0)
        pm50  = particles.pm_per_1l_air(5.0) - pm100
        pm25  = particles.pm_per_1l_air(2.5) - pm100 - pm50
        pm10  = particles.pm_per_1l_air(1.0) - pm100 - pm50 - pm25
        pm5   = particles.pm_per_1l_air(0.5) - pm100 - pm50 - pm25 - pm10
        pm3   = particles.pm_per_1l_air(0.3) - pm100 - pm50 - pm25 - pm10 - pm5
    else:
        pm100 = pm50 = pm25 = pm10 = pm5 = pm3 = 0
        
    record = {
        'time' : asctime(localtime(time)),
        'temp' : round(temperature,1),
        'humi' : round(humidity, 1),
        'pres' : round(pressure,1),
        'lux'  : round(lux),
        'oxi'  : oxi,
        'red'  : red,
        'nh3'  : nh3,
        'pm03' : pm3,
        'pm05' : pm5,
        'pm10' : pm10,
        'pm25' : pm25,
        'pm50' : pm50,
        'pm100': pm100,
    }
    return record

record = read_data(time()) # throw away the first readings as not accurate
data = []
days = []

def filename(t):
    return strftime("data/%Y_%j", localtime(t))

def sum_data(data):
    totals = {"time" : data[0]["time"]}
    keys = list(data[0].keys())
    keys.remove("time")
    for key in keys:
        totals[key] = 0
    for d in data:
        for key in keys:
            totals[key] += d[key]
    count = float(len(data))
    for key in keys:
        totals[key] = round(totals[key] / count, 1)
    return totals

def record_time(r):
    t = r['time'].split()[3].split(':')
    return int(t[0]) * 60 + int(t[1])

samples = 300 # Number of 1 second samples average per file record
samples_per_day = 24 * 3600 // samples

def add_record(day, record):
    if record_time(record) > 0:  # If not the first record of the day
        while len(day) == 0 or record_time(day[-1]) < record_time(record) - samples // 60: # Is there a gap
            if len(day):
                filler = dict(day[-1]) # Duplicate the last record to forward fill
                t = record_time(filler) + samples // 60
            else:
                filler = dict(record) # Need to back fill
                t = 0                 # Only happens if the day is empty so most be the first entry
            old_time = filler["time"] # Need to fix the time field
            colon_pos = old_time.find(':')
            filler["time"] = old_time[:colon_pos - 2] + ("%02d:%02d" % (t / 60, t % 60)) + old_time[colon_pos + 3:]
            day.append(filler)
    day.append(record)

def background():
    global record, data
    sleep(2)
    last_file = None
    while run_flag:
        t = int(floor(time()))
        record = read_data(t)
        data = data[-(samples - 1):] + [record]         # Keep five minutes
        if t % samples == samples - 1 and len(data) == samples: # At the end of a 5 minute period?
            totals = sum_data(data)
            fname = filename(t - (samples - 1))
            with open(fname, "a+") as f:
                f.write(json.dumps(totals) + '\n')
            # Handle new day
            if not days or (last_file and last_file != fname):
                days.append([])
            last_file = fname
            add_record(days[-1], totals)        # Add to today, filling any gap from last reading if been stopped
        if days:
            display_everything()
        sleep(max(t + 1 - time(), 0.1))

background_thread = threading.Thread(target = background)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/readings')
def readings():
    arg = request.args["fan"]
    pwm.ChangeDutyCycle(int(arg))
    return render_template('readings.html' if particle_sensor else 'readings_np.html' if gas_sensor else 'readings_ng.html', **record) 

def compress_data(ndays, nsamples):
    cdata = []
    for day in days[-(ndays + 1):]:
        for i in range(0, len(day), nsamples):
            cdata.append(sum_data(day[i : i + nsamples]))
    length = ndays * samples_per_day // nsamples
    return json.dumps(cdata[-length:])

# 300 @ 1s = 5m
# 288 @ 5m = 24h
# 336 @ 30m = 1w
# 372 @ 2h = 31d
# 365 @ 1d = 1y
@app.route('/graph')
def graph():
    arg = request.args["time"]
    if arg == 'day':
        last2 = []
        for day in days[-2:]:
            last2 += day
        return json.dumps(last2[-samples_per_day:])
    if arg == 'week':
        return compress_data(7, 30 * 60 // samples)
    if arg == 'month':
        return compress_data(31, 120 * 60 // samples)
    if arg == 'year':
        return compress_data(365, samples_per_day)
    return json.dumps(data)

def read_day(fname):
    day = []
    print("reading " + fname)
    with open(fname, 'r') as f:
        for line in f.readlines():
            record = json.loads(line)
            add_record(day, record)
    return day

if __name__ == '__main__':
    if not os.path.isdir('data'):
        os.makedirs('data')
    files =  sorted(os.listdir('data'))
    for f in files:
        days.append(read_day('data/' + f))
    background_thread.start()
    try:
        app.run(debug = False, host = '0.0.0.0', port = 80, use_reloader = False)
    except Exception as e:
        print(e)
        pass
    run_flag = False
    print("Waiting for background to quit")
    background_thread.join()
