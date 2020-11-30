#!/usr/bin/python3
# If you're using docker, name this file run.py
from mqtt2e131 import *
import time

MQTT_SERVER = "myserver" # you can set the port with the mqtt_port kwarg

HOST = "hostname_or_ip"
NUM_UNIVERSES_ON_HOST = 3
NUM_LIGHTS = 381

target = SACNTarget(HOST, NUM_UNIVERSES_ON_HOST)
L = Light("light_name_in_hass", target, MQTT_SERVER, 1, NUM_LIGHTS)

while True:
  time.sleep(1)
