


class Interface:

    def __init__(self, name="", ipaddress="", mask="", mac_address="", type_int="1000base-tx", speed=1000):
      self.name = name
      self.ipaddress = ipaddress
      self.mask = mask
      self.mac_address = mac_address
      self.type_int = type_int
      self.speed = speed
    
    def to_dict(self):
      return {
         "name" : self.name,
         "ipaddress" : self.ipaddress,
         "mask" : self.mask,
         "mac_address" : self.mac_address,
         "type_int" : self.type_int,
         "speed" : self.speed

      }


       
       
       