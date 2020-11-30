#!/usr/bin/python3

from paho.mqtt import client as mqtt_client
import json
import atexit

import sacn
import socket

MQTT_SERVER = "theserver"
MQTT_PREFIX = "homeassistant/light/"

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

  def __init__(self,
      name, mqtt, target, start_universe, num_lights,
      unique_name = None
      ):
    self.name = name
    self.unique_name = unique_name if unique_name else name
    self.target = target
    self.start_universe = start_universe
    self.num_lights = num_lights
    self.num_universes = (num_lights // 170) + (0 if (num_lights % 170 == 0) else 1)
    self.mqtt = mqtt
    self.prefix = MQTT_PREFIX + self.unique_name
    atexit.register(self.cleanup)
    self.register()
    self.setup_mqtt_callbacks()

    self.brightness = 255
    self.on = False
    self.color = (255, 255, 255)

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
        "rgb": True
      }))
  

  def publish_state(self):
    self.mqtt.publish(self.prefix + "/state", json.dumps(
      {
        "state": "ON" if self.on else "OFF",
        "brightness": self.brightness,
        "color": {
          "r": self.color[0],
          "g": self.color[1],
          "b": self.color[2]
        }
      }))

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

      self.update_state()

    print("setting callback for %s" % (self.prefix + "/set"))
    self.mqtt.message_callback_add(self.prefix + "/set", set_callback)
    self.mqtt.subscribe(self.prefix + "/set")



  def deregister(self):
    self.mqtt.publish(self.prefix + "/config", None)

  def cleanup(self):
    self.deregister()
    self.target.sender.stop()


  def set(self, i, r, g, b):
    self.target.setRGB(self.start_universe, i, r, g, b)

  def fill(self, r, g, b):
    with self.target.updateContext():
      for i in range(self.num_lights):
        self.set(i, r, g, b)

  def update_state(self):
      self.publish_state()
      if self.on:
        self.target.enableUniverses(self.start_universe, self.num_universes)
        self.fill(
            (self.brightness * self.color[0]) // 255,
            (self.brightness * self.color[1]) // 255,
            (self.brightness * self.color[2]) // 255)
      else:
        self.fill(0,0,0)
        self.target.disableUniverses(self.start_universe, self.num_universes)

      

def main():
  mqtt = mqtt_client.Client()
  mqtt.connect("theserver", 1883, 60)
  mqtt.loop_start()

  s = SACNTarget("craftwindow", 2)
  l = Light("crafttest", mqtt, s, 1, 284)
  return l

  
