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
from flask import Flask, render_template, url_for, request
from bme280 import BME280
import ltr559
from enviroplus import gas
from pms5003 import PMS5003, ReadTimeoutError as pmsReadTimeoutError
import threading
from time import sleep, time, asctime, localtime, strftime, gmtime
from math import ceil, floor
import json
import os

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus

bus = SMBus(1)
bme280 = BME280(i2c_dev=bus) # BME280 temperature, humidity and pressure sensor

pms5003 = PMS5003() # PMS5003 particulate sensor

app = Flask(__name__)
run_flag = True

def read_data(time):
    temperature = bme280.get_temperature()
    pressure = bme280.get_pressure()
    humidity = bme280.get_humidity()
    lux = ltr559.get_lux()
    gases = gas.read_all()
    while True:
        try:
            particles = pms5003.read()
            break
        except:
            print("Particle read failed")
    pm100 = particles.pm_per_1l_air(10.0);
    pm50 = particles.pm_per_1l_air(5.0) - pm100;
    pm25 = particles.pm_per_1l_air(2.5) - pm100 - pm50;
    pm10 = particles.pm_per_1l_air(1.0) - pm100 - pm50 - pm25;
    pm5 = particles.pm_per_1l_air(0.5) - pm100 - pm50 - pm25 - pm10;
    pm3 = particles.pm_per_1l_air(0.3) - pm100 - pm50 - pm25 - pm10 - pm5;
    record = {
        'time' : asctime(localtime(time)),
        'temp' : round(temperature,1),
        'humi' : round(humidity, 1),
        'pres' : round(pressure,1),
        'lux'  : round(lux),
        'oxi'  : round(gases.oxidising / 1000, 1),
        'red'  : round(gases.reducing / 1000),
        'nh3'  : round(gases.nh3 / 1000),
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
            if last_file and last_file != fname:
                days.append([])
            last_file = fname
            add_record(days[-1], totals)        # Add to today, filling any gap from last reading if been stopped
        sleep(max(t + 1 - time(), 0.1))
    
background_thread = threading.Thread(target = background)

@app.route('/')
def index():
    return render_template('index.html') 

@app.route('/readings')
def readings():
    return render_template('readings.html', **record)

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
        return json.dumps((days[-2] + days[-1])[-samples_per_day:])
    if arg == 'week':
        return compress_data(7, 30 * 60 // samples)
    if arg == 'month':
        return compress_data(31, 120 * 60 // samples)
    if arg == 'year':
        return compress_data(365, samples_per_day)
    return json.dumps(data)
   
def read_day(fname):
    day = []
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
    while len(days) < 2:
        days.insert(0,[])
    background_thread.start()
    try:
        app.run(debug = True, host = '0.0.0.0', port = 5000, use_reloader = False)
    except:
        pass
    run_flag = False
    print("Waiting for background to quit")
    background_thread.join()
