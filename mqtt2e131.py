#!/usr/bin/python3

from paho.mqtt import client as mqtt_client
import atexit
import json
import sacn
import socket
import threading
import time

from effects import *

ALL_EFFECTS = [
    Solid,
    Colorful,
]

#TODO - allow graceful exit with all threads ending

HASS_MQTT_PREFIX = "homeassistant/light/"
FPS = 10

class SACNTarget:
  """A device with a given IP/hostname that can accept SACN packets.
     May map one or more lights."""

  def __init__(self, host, n_universes, start_universe=1, channels_per_universe=510):
    self.sender = sacn.sACNsender()
    self.sender.start()
    self.host = host
    self.channels_per_universe = channels_per_universe
    # TODO - periodically re-lookup hosts
    self.hostip = socket.gethostbyname(host)
    for u in range(start_universe, n_universes+start_universe):
      self.enableUniverses(u)
    time.sleep(1) # give sacn a chance to initialize
    print(
        "Started sACN sender to %s with universes %d to %d" % (
          self.hostip, start_universe, n_universes + start_universe - 1))

  def setUniverses(self, start_u, data):
    num_us = len(data) // 512
    if len(data) % 512 != 0:
      print("WARNING - incomplete universe given to setUniverses() (%d)" % len(data))

    if start_u not in self.sender.get_active_outputs():
      self.enableUniverses(start_u, num_us)
      
    for u in range(start_u, start_u + num_us):
      self.sender[u].dmx_data = data[(u - start_u)*512 : (u - start_u + 1)*512]

  def disableUniverses(self, start_u, num_u=1):
    for u in range(start_u, start_u + num_u):
      if u in self.sender.get_active_outputs():
        self.sender[u].dmx_data = [0]*512
        self.sender.deactivate_output(u)

  def enableUniverses(self, start_u, num_u=1):
    for u in range(start_u, start_u + num_u):
      self.sender.activate_output(u)
      self.sender[u].destination = self.hostip
      self.sender[u].multicast = False

  def updateContext(self):
    # still not sure if this is necessary to prevent stuttering on universe
    # gaps, but it doesn't seem to be having any negative impact.
    class UCtx:
      def __enter__(ss):
        self.sender.manual_flush = True
      def __exit__(ss, et, ev, tb):
        self.sender.flush()
        self.sender.manual_flush = False
    return UCtx()
    
      
class Light:
  """A light. Takes an SACN target as an argument, allowing multiple lights to
     map to different universes on the same target (or, theoretically, the same
     universes). When Home Assistant turns off the light, we send all zeros and
     then stop transmitting packets."""

  ORDER_RGB = lambda c: (c[0], c[1], c[2])
  ORDER_GRB = lambda c: (c[1], c[0], c[2])

  def __init__(self,
      name, target, mqtt_server, start_universe, num_lights,
      unique_name = None, mqtt_port=1883, mqtt_prefix=HASS_MQTT_PREFIX,
      color_order=ORDER_RGB
      ):
    self.name = name
    self.unique_name = unique_name if unique_name else name
    self.target = target
    self.start_universe = start_universe
    self.num_lights = num_lights
    self.num_universes = (num_lights // 170) + (0 if (num_lights % 170 == 0) else 1)
    self.color_mapper = color_order

    self.mqtt = mqtt_client.Client()
    self.mqtt.connect(mqtt_server, mqtt_port, 60) # TODO - what is the 60?
    self.mqtt.loop_start()

    self.prefix = mqtt_prefix + self.unique_name
    atexit.register(self.cleanup)
    self.register()
    self.setup_mqtt_callbacks()

    self.brightness = 127
    self.on = False
    self.color = (255, 255, 255)
    self.buffer = [255] * (self.num_universes * 512)
    self.effect = Solid(self)

    self.last_published_state = ""
    self.publish_state()

    # start the effect ticker
    def tick_cb():
      while True:
        self.tick()
        time.sleep(1./FPS)
    threading.Thread(target=tick_cb, name=self.unique_name+"-fx").start()

  def register(self):
    self.mqtt.publish(self.prefix + "/config", json.dumps(
      {
        "~": self.prefix,
        "name": self.name,
        "unique_id": self.unique_name,
        "cmd_t": "~/set",
        "stat_t": "~/state",
        "schema": "json",
        "brightness": True,
        "rgb": True,
        "effect": True,
        "fx_list": [ fx.name for fx in ALL_EFFECTS]
      }))
  

  def publish_state(self, force=False):
    state_str = json.dumps(
      {
        "state": "ON" if self.on else "OFF",
        "brightness": self.brightness,
        "color": {
          "r": self.color[0],
          "g": self.color[1],
          "b": self.color[2]
        },
        "effect": self.effect.name
      })
    if force or (state_str != self.last_published_state):
      self.mqtt.publish(self.prefix + "/state", state_str)
      self.last_published_state = state_str

  def setup_mqtt_callbacks(self):
    def set_callback(client, userdata, msg):
      M = json.loads(msg.payload)
      if 'state' in M:
        if M['state'] == 'ON':
          self.on = True
        else:
          self.on = False

      if 'brightness' in M:
        self.brightness = M['brightness']
      
      if 'color' in M:
        c = M['color']
        self.color = (c['r'], c['g'], c['b'])

      if 'effect' in M:
        fx = M['effect']
        for f in ALL_EFFECTS:
          if f.name == fx:
            self.effect = f(self)


    self.mqtt.message_callback_add(self.prefix + "/set", set_callback)
    self.mqtt.subscribe(self.prefix + "/set") 



  def deregister(self):
    self.mqtt.publish(self.prefix + "/config", None)

  def cleanup(self):
    self.deregister()
    self.target.sender.stop()


  def set(self, i, r, g, b, absolute=False):
    rr, gg, bb = self.color_mapper((r,g,b))
    if not absolute:
      rr = (rr * self.brightness) // 255
      gg = (gg * self.brightness) // 255
      bb = (bb * self.brightness) // 255
    self.buffer[i*3] = rr
    self.buffer[i*3+1] = gg
    self.buffer[i*3+2] = bb

  def fill(self, r, g, b):
    with self.target.updateContext():
      for i in range(self.num_lights):
        self.set(i, r, g, b)

  def show(self):
    self.target.setUniverses(self.start_universe, self.buffer)

  # called periodically by a separate thread
  def tick(self):
    self.publish_state()
    if self.on:
      self.target.enableUniverses(self.start_universe, self.num_universes)
      self.effect.tick()
      self.show()
    else:
      self.target.disableUniverses(self.start_universe, self.num_universes)
