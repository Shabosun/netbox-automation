import logging
import os
from dotenv import load_dotenv

from pysnmp.hlapi import SnmpEngine, CommunityData, UdpTransportTarget, ContextData
from pysnmp.hlapi import ObjectType, ObjectIdentity, getCmd, nextCmd

from interface import Interface
from utils.utils import is_valid_ip, convert_mask_bit_to_decimal

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SITE = os.getenv("SITE", "DC-main")

MANUFACTURER_KEYWORDS = [
    ("mikrotik",  "Mikrotik"),
    ("routeros",  "Mikrotik"),
    ("d-link",    "D-Link"),
    ("dlink",     "D-Link"),
    ("tp-link",   "TP-Link"),
    ("tplink",    "TP-Link"),
    ("h3c",       "H3C"),
    ("comware",   "H3C"),
    ("mellanox",  "Mellanox"),
    ("onyx",      "Mellanox"),
]

SYSDESCR_CLEANUP = {
    "Mikrotik": ["MikroTik RouterOS ", "RouterOS "],
    "D-Link":   ["D-Link "],
    "TP-Link":  ["TP-Link "],
    "Mellanox": ["Mellanox Onyx ", "Onyx "],
}


def detect_manufacturer(sysdescr: str) -> str:
    lower = sysdescr.lower()
    for keyword, manufacturer in MANUFACTURER_KEYWORDS:
        if keyword in lower:
            return manufacturer
    logger.warning(f"Производитель не определён по sysDescr: '{sysdescr}'")
    return "Unknown"


def _extract_h3c_model(sysdescr: str) -> str:
    """
    Извлекает модель из sysDescr H3C через regex.

    Примеры sysDescr (строка может содержать копирайт в конце):
      "H3C Comware Platform Software ... H3C S6520X-18C-SI Copyright (c) 2004-2023 New H3C Technologies Co."
      "Comware Software, Version 5.20 ... H3C S5120-28C-EI"

    Ищем все вхождения "H3C <Слово>" и отбрасываем служебные слова.
    Модели H3C начинаются с заглавной буквы и содержат цифры (S6520X, S5120 и т.д.).
    """
    import re

    pattern = re.compile(r'\bH3C\s+([A-Z]\w+(?:-\w+)*)', re.IGNORECASE)
    exclude  = {"comware", "technologies", "platform", "copyright", "software", "new"}

    matches = pattern.findall(sysdescr)
    models  = [m for m in matches if m.lower() not in exclude]

    if models:
        return models[0]

    # Запасной вариант — последнее слово строки
    parts = sysdescr.strip().split()
    return parts[-1] if parts else sysdescr.strip()


def cleanup_sysdescr(sysdescr: str, manufacturer: str) -> str:
    """Извлекает модель устройства из строки sysDescr."""
    if manufacturer == "H3C":
        return _extract_h3c_model(sysdescr)

    result = sysdescr
    for prefix in SYSDESCR_CLEANUP.get(manufacturer, []):
        if result.startswith(prefix):
            result = result[len(prefix):]
            break
    return result.strip()


class Device:

    def __init__(self, ipaddress: str, interfaces: list = None):
        self.ipaddress    = ipaddress
        self.name         = ""
        self.device_type  = ""
        self.manufacturer = "Unknown"
        self.site         = SITE
        self.interfaces   = interfaces if interfaces is not None else []

    # ------------------------------------------------------------------
    # Публичный метод
    # ------------------------------------------------------------------

    def scan(self, snmp_engine: SnmpEngine, community: str):
        """Считывает все данные устройства по SNMP."""
        self._scan_system_info(snmp_engine, community)

        # Сначала получаем таблицу IP {ifIndex: (ip, mask)},
        # потом walk по интерфейсам — соединяем по ifIndex
        ip_table = self._scan_ip_table(snmp_engine, community)
        self._scan_interfaces(snmp_engine, community, ip_table)

        logger.info(
            f"[{self.ipaddress}] Готово — name='{self.name}', "
            f"manufacturer='{self.manufacturer}', "
            f"device_type='{self.device_type}', "
            f"interfaces={len(self.interfaces)}"
        )

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    def _scan_system_info(self, snmp_engine: SnmpEngine, community: str):
        """Hostname и модель одним getCmd."""
        iterator = getCmd(
            snmp_engine,
            CommunityData(community, mpModel=1),
            UdpTransportTarget((self.ipaddress, 161)),
            ContextData(),
            ObjectType(ObjectIdentity('.1.3.6.1.2.1.1.5.0')),         # sysName
            ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0)),  # sysDescr
        )

        for errorIndication, errorStatus, errorIndex, varBinds in iterator:
            if errorIndication:
                logger.error(f"[{self.ipaddress}] SNMP error: {errorIndication}")
            elif errorStatus:
                logger.error("[{}] {} at {}".format(
                    self.ipaddress,
                    errorStatus.prettyPrint(),
                    errorIndex and varBinds[int(errorIndex) - 1][0] or "?",
                ))
            else:
                self.name         = str(varBinds[0][1])
                raw_sysdescr      = varBinds[1][1].prettyPrint()
                self.manufacturer = detect_manufacturer(raw_sysdescr)
                self.device_type  = cleanup_sysdescr(raw_sysdescr, self.manufacturer)

    def _scan_ip_table(self, snmp_engine: SnmpEngine, community: str) -> dict[int, tuple[str, str]]:
        """
        Walk по ipAddrTable (1.3.6.1.2.1.4.20).
        Возвращает словарь {ifIndex: (ip, mask)}.

        Таблица индексируется по IP, а не по ifIndex — поэтому её нельзя
        совмещать с ifTable в одном nextCmd. Делаем отдельный запрос.

        OID-ы:
          4.20.1.1 — ipAdEntAddr   (сам IP, он же суффикс OID)
          4.20.1.2 — ipAdEntIfIndex (ifIndex интерфейса)
          4.20.1.3 — ipAdEntNetMask (маска)
        """
        ip_table: dict[int, tuple[str, str]] = {}

        iterator = nextCmd(
            snmp_engine,
            CommunityData(community, mpModel=1),
            UdpTransportTarget((self.ipaddress, 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.2.1.4.20.1.1')),  # ipAdEntAddr
            ObjectType(ObjectIdentity('1.3.6.1.2.1.4.20.1.2')),  # ipAdEntIfIndex
            ObjectType(ObjectIdentity('1.3.6.1.2.1.4.20.1.3')),  # ipAdEntNetMask
            lexicographicMode=False,
        )

        for errorIndication, errorStatus, errorIndex, varBinds in iterator:
            if errorIndication:
                logger.error(f"[{self.ipaddress}] ip_table SNMP error: {errorIndication}")
                break
            elif errorStatus:
                logger.error(f"[{self.ipaddress}] ip_table ошибка: {errorStatus.prettyPrint()}")
                break
            else:
                ip       = varBinds[0][1].prettyPrint()
                ifindex  = int(varBinds[1][1])
                mask_raw = varBinds[2][1].prettyPrint()
                mask     = convert_mask_bit_to_decimal(mask_raw)

                if is_valid_ip(ip):
                    ip_table[ifindex] = (ip, mask)
                    logger.debug(f"[{self.ipaddress}] ip_table: ifIndex={ifindex} → {ip}/{mask}")

        logger.info(f"[{self.ipaddress}] IP-таблица: {ip_table}")
        return ip_table

    def _scan_interfaces(self, snmp_engine: SnmpEngine, community: str, ip_table: dict):
        """
        Walk по ifTable + ifXTable.
        IP и маска берутся из ip_table по ifIndex.

        OID-ы:
          31.1.1.1.1  — ifName
           2.2.1.3    — ifType (6 = physical ethernetCsmacd)
          31.1.1.1.15 — ifHighSpeed
           2.2.1.6    — ifPhysAddress (MAC)
        """
        iterator = nextCmd(
            snmp_engine,
            CommunityData(community, mpModel=1),
            UdpTransportTarget((self.ipaddress, 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.2.1.31.1.1.1.1')),   # ifName
            ObjectType(ObjectIdentity('1.3.6.1.2.1.2.2.1.3')),       # ifType
            ObjectType(ObjectIdentity('1.3.6.1.2.1.31.1.1.1.15')),  # ifHighSpeed
            ObjectType(ObjectIdentity('1.3.6.1.2.1.2.2.1.6')),       # ifPhysAddress
            lexicographicMode=False,
        )

        ifindex = 0  # ifIndex нумеруется с 1, инкрементируем сами по порядку строк

        for errorIndication, errorStatus, errorIndex, varBinds in iterator:
            if errorIndication:
                logger.error(f"[{self.ipaddress}] interfaces SNMP error: {errorIndication}")
                break
            elif errorStatus:
                logger.error(f"[{self.ipaddress}] interfaces ошибка: {errorStatus.prettyPrint()}")
                break
            else:
                ifindex += 1

                if int(varBinds[1][1]) != 6:  # только физические
                    continue

                ifname      = str(varBinds[0][1])
                ifspeed     = str(varBinds[2][1])
                mac_address = ':'.join(f'{b:02x}' for b in bytes(varBinds[3][1]))

                # Берём IP и маску из ip_table по ifIndex
                ip, mask = ip_table.get(ifindex, ("", ""))

                self.interfaces.append(Interface(
                    name=ifname,
                    ipaddress=ip,
                    mask=mask,
                    mac_address=mac_address,
                    speed=ifspeed,
                ))

    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "ipaddress":    self.ipaddress,
            "name":         self.name,
            "device_type":  self.device_type,
            "manufacturer": self.manufacturer,
            "site":         self.site,
            "interfaces":   [x.to_dict() for x in self.interfaces],
        }