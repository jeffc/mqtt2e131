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

  def setRGB(self, start_universe, pix_offset, r, g, b):
    def offset(start, o):
      u = start + (o // self.channels_per_universe)
      i = o - ((u-start) * self.channels_per_universe)
      return (u, i)

    def setDMXVal(u, i, v):
      """Tuples aren't assignable, so this helper handles the conversion and
      update"""
      L = list(self.sender[u].dmx_data)
      L[i] = v
      self.sender[u].dmx_data = L

    u,i = offset(start_universe, pix_offset*3)
    setDMXVal(u, i, r)
    u,i = offset(start_universe, pix_offset*3+1)
    setDMXVal(u, i, g)
    u,i = offset(start_universe, pix_offset*3+2)
    setDMXVal(u, i, b)

  def disableUniverses(self, start_u, num_u=1):
    for u in range(start_u, start_u + num_u):
      self.sender.deactivate_output(u)

  def enableUniverses(self, start_u, num_u=1):
    for u in range(start_u, start_u + num_u):
      self.sender.activate_output(u)
      self.sender[u].destination = self.hostip
      self.sender[u].multicast = False

  def updateContext(self):
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

    self.brightness = 255
    self.on = False
    self.color = (255, 255, 255)
    self.effect = Solid(self)

    self.last_published_state = ""
    self.publish_state()

    # start the effect ticker
    def tick_cb():
      while True:
        self.tick()
        time.sleep(1./FPS)
    threading.Thread(target=tick_cb).run()

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


    print("setting callback for %s" % (self.prefix + "/set"))
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
    self.target.setRGB(self.start_universe, i, rr, gg, bb)

  def fill(self, r, g, b):
    with self.target.updateContext():
      for i in range(self.num_lights):
        self.set(i, r, g, b)

  # called periodically by a separate thread
  def tick(self):
    self.publish_state()
    if self.on:
      self.target.enableUniverses(self.start_universe, self.num_universes)
      self.effect.tick()
    else:
      try: # might fail if universes are disabled
        self.fill(0,0,0)
      except:
        pass
      self.target.disableUniverses(self.start_universe, self.num_universes)
