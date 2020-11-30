class Effect:
  """Base class for effects"""
  name = "Base Effect"

  def __init__(self, L):
    self.L = L
    self.start()

  def start(self):
    pass

  def tick(self):
    pass

class Solid(Effect):

  name = "Solid"

  def tick(self):
    r, g, b = self.L.color
    self.L.fill(r, g, b)

class Colorful(Effect):
  """A port of the WLED colorful effect:
  https://github.com/Aircoookie/WLED/blob/79c83a96a06c59b178aa839f4de3dec8b3264e95/wled00/FX.cpp#L805
  """

  name = "Colorful"
  ticks_until_change = 20

  def start(self):
    self.ticks = 0 # counter
    self.offset = 0

  def tick(self):
    colors = [ 
        (0xFF, 0x00, 0x00),
        (0xEE, 0xBB, 0x00),
        (0x00, 0xEE, 0x00),
        (0x00, 0x77, 0xCC)
    ]

    with self.L.target.updateContext():
      for i in range(0, self.L.num_lights):
        r, g, b = colors[(i + self.offset) % len(colors)]
        self.L.set(i, r, g, b)

    self.ticks += 1
    self.ticks %= self.ticks_until_change
    if self.ticks == 0:
      self.offset += 1
      self.offset %= len(colors)



