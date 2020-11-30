#!/usr/bin/python3

from paho.mqtt import client as mqtt_client
import json

import sacn
import socket


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

  def __init__(self, name, target, start_universe, num_lights):
    self.name = name
    self.target = target
    self.start_universe = start_universe
    self.num_lights = num_lights

  def set(self, i, r, g, b):
    self.target.setRGB(self.start_universe, i, r, g, b)

  def fill(self, r, g, b):
    with self.target.updateContext():
      for i in range(self.num_lights):
        self.set(i, r, g, b)

def main():
  #mqtt = mqtt_client.Client()
  #mqtt.connect("theserver", 1883, 60)
  #mqtt.publish("test/test", "payload")
  #mqtt.loop_forever()
  pass

  
