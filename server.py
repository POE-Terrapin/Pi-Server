#!/usr/bin/python

from flask import Flask, render_template, Response, request, jsonify
from calib import calibrate

import serial
import threading
import logging

from turtle import Turtle
from status import Status

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__, static_url_path='/static') # This directiory
t = Turtle('/dev/ttyACM0', 9600)
lock = threading.Lock()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/data', methods=['POST'])
def status():
    with lock:
        global t
        res = t.status[:]
        # Format : [self.LS['front'], self.LS['back'], self.IR['front'], self.IR['right'], self.IR['left'], self.TS, self.SM, self.behavior]
        res[2], res[3], res[4] = calibrate(res[2] / 1024 * 5.0), calibrate(res[3] / 1024 * 5.0), calibrate(res[4] / 1024 * 5.0) # Convert Voltage to Distance
        print res
        return jsonify(t.status)

if __name__ == "__main__":

    # Start Turtle Interaction
    turtle_control = threading.Thread(target = t.run, args = [lock])
    turtle_control.setDaemon(True)
    turtle_control.start()

    ## Now run the server
    app.run(host='0.0.0.0', debug=True)
