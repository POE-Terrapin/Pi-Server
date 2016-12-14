#!/usr/bin/python

from flask import Flask, render_template, Response, request, jsonify
import serial
import threading
import logging

from turtle import Turtle

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__, static_url_path='') # This directiory


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/data', methods=['POST'])
def status():
    return jsonify(turtle.status())

if __name__ == "__main__":

    # Start Turtle Interaction
    turtle = Turtle('/dev/ttyACM0', 9600)
    turtle_control = threading.Thread(target = turtle.run)
    turtle_control.setDaemon(True)
    turtle_control.start()

    ## Now run the server
    app.run(host='0.0.0.0', debug=True)
