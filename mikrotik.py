from pysnmp.hlapi import *

import logging
import json
from interface import Interface
from utils.utils import *


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)




class Mikrotik:

    # role = Router, site = DC-main
    def __init__(self, ipaddress="", name="", device_type="", mac_address="", interfaces=[], role="Router", site="DC-main", manufacturer="Mikrotik"):  # возможно добавить serial number
        self.ipaddress = ipaddress
        self.name = name
        self.device_type = device_type
        self.mac_address = mac_address
        self.interfaces = interfaces
        self.manufacturer = manufacturer
        self.site = site
        self.role = role

    def scan(self, snmp_engine: SnmpEngine, community: str):
        """Считывает все данные устройства по SNMP: hostname, модель и список интерфейсов."""
        self._scan_system_info(snmp_engine, community)
        self._scan_interfaces(snmp_engine, community)

    # --- Приватные методы ---

    def _scan_system_info(self, snmp_engine: SnmpEngine, community: str):
        """Получает hostname и модель устройства одним getCmd-запросом."""
        iterator = getCmd(
            snmp_engine,
            CommunityData(community, mpModel=0),
            UdpTransportTarget((self.ipaddress, 161)),
            ContextData(),
            ObjectType(ObjectIdentity('.1.3.6.1.2.1.1.5.0')),          # sysName  - hostname
            ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0)),   # sysDescr - модель
        )

        for errorIndication, errorStatus, errorIndex, varBinds in iterator:
            if errorIndication:
                logger.error(f"[{self.ipaddress}] SNMP error: {errorIndication}")
            elif errorStatus:
                logger.error(
                    "[{}] {} at {}".format(
                        self.ipaddress,
                        errorStatus.prettyPrint(),
                        errorIndex and varBinds[int(errorIndex) - 1][0] or "?",
                    )
                )
            else:
                self.name = str(varBinds[0][1])
                self.device_type = str(varBinds[1][1].prettyPrint()).removeprefix("RouterOS ")

    def _scan_interfaces(self, snmp_engine: SnmpEngine, community: str):
        """Получает список физических интерфейсов через nextCmd (SNMP walk)."""
        iterator = nextCmd(
            snmp_engine,
            CommunityData(community, mpModel=0),
            UdpTransportTarget((self.ipaddress, 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.2.1.31.1.1.1.1')),    # ifName      - название интерфейса
            ObjectType(ObjectIdentity('1.3.6.1.2.1.2.2.1.3')),        # ifType      - тип интерфейса
            ObjectType(ObjectIdentity('1.3.6.1.2.1.31.1.1.1.15')),   # ifHighSpeed - скорость
            ObjectType(ObjectIdentity('.1.3.6.1.2.1.2.2.1.6')),       # ifPhysAddress - MAC
            ObjectType(ObjectIdentity('1.3.6.1.2.1.4.20.1.1 ')),      # ipAdEntAddr   - IP-адрес
            ObjectType(ObjectIdentity('1.3.6.1.2.1.4.20.1.3 ')),      # ipAdEntNetMask - маска
            lexicographicMode=False,
        )

        for errorIndication, errorStatus, errorIndex, varBinds in iterator:
            if errorIndication:
                logger.error(f"[{self.ipaddress}] SNMP error: {errorIndication}")
                break
            elif errorStatus:
                logger.error(f"[{self.ipaddress}] Ошибка: {errorStatus.prettyPrint()}")
                break
            else:
                if int(varBinds[1][1]) != 6:  # пропускаем не-физические интерфейсы
                    continue

                ifname = str(varBinds[0][1])
                ifspeed = str(varBinds[2][1])
                mac_address = ':'.join(f'{b:02x}' for b in bytes(varBinds[3][1]))
                ipaddress = varBinds[4][1].prettyPrint() if is_valid_ip(varBinds[4][1].prettyPrint()) else ""
                mask = convert_mask_bit_to_decimal(varBinds[5][1].prettyPrint())

                self.interfaces.append(
                    Interface(
                        name=ifname,
                        ipaddress=ipaddress,
                        mask=mask,
                        mac_address=mac_address,
                        speed=ifspeed,
                    )
                )

    def to_dict(self):
        return {
            "ipaddress": self.ipaddress,
            "name": self.name,
            "device_type": self.device_type,
            "interfaces": [x.to_dict() for x in self.interfaces],
            "role": self.role,
            "manufacturer": self.manufacturer,
            "site": self.site,
        }