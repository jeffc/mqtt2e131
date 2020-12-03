#!/usr/bin/python3
# If you're using docker with the provided Dockerfile,
# name this file run.py and COPY or bind-mount it as /code/run.py
# (I use bind mounting for easy tweaks, but YMMV)
from mqtt2e131 import *
import time

MQTT_SERVER = "myserver" # you can set the port with the mqtt_port kwarg

HOST = "hostname_or_ip"
NUM_UNIVERSES_ON_HOST = 3
NUM_LIGHTS = 381

def main():
  target = SACNTarget(HOST, NUM_UNIVERSES_ON_HOST)
  L = Light("light_name_in_hass", target, MQTT_SERVER, 1, NUM_LIGHTS, color_order=Light.ORDER_RGB)

  while True:
    time.sleep(1)

if __name__ == "__main__":
  main()
