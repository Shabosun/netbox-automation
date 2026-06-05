import os
import sys
import json
import logging
from dotenv import load_dotenv

from device import Device
from snmp_engine import get_snmp_engine
from netbox_api import create_device

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Конфигурация запуска — меняй эти две переменные перед запуском
# ---------------------------------------------------------------------------

#HOSTS_FILE = "mikrotik.list"                    # файл со списком IP-адресов
#COMMUNITY  = os.getenv("MIKROTIK_COMMUNITY")    # SNMP community для этого запуска

# Для коммутаторов:
HOSTS_FILE = os.getenv("HOSTS_FILE")
COMMUNITY  = os.getenv("COMMUNTIY")

# ---------------------------------------------------------------------------


def load_hosts(filepath: str) -> list[str]:
    """Читает файл со списком IP-адресов, по одному на строку. # — комментарий."""
    if not os.path.exists(filepath):
        logger.error(f"Файл '{filepath}' не найден.")
        sys.exit(1)

    hosts = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                hosts.append(line)

    logger.info(f"Загружено {len(hosts)} хостов из '{filepath}'")
    return hosts


def scan_and_push(ipaddress: str, community: str, snmp_engine) -> dict | None:
    """Сканирует одно устройство и добавляет его в NetBox."""
    logger.info(f"--- Обрабатываем {ipaddress} ---")
    device = Device(ipaddress=ipaddress)

    try:
        device.scan(snmp_engine=snmp_engine, community=community)
    except Exception as e:
        logger.error(f"[{ipaddress}] Ошибка сканирования: {e}")
        return None

    logger.info(f"[{ipaddress}] sysDescr → manufacturer='{device.manufacturer}', model='{device.device_type}'")

    try:
        create_device(device.to_dict())
    except Exception as e:
        logger.error(f"[{ipaddress}] Ошибка добавления в NetBox: {e}")
        return None

    return device.to_dict()


def main():
    hosts       = load_hosts(HOSTS_FILE)
    snmp_engine = get_snmp_engine()
    results     = []

    for ip in hosts:
        result = scan_and_push(ip, COMMUNITY, snmp_engine)
        if result:
            results.append(result)

    # Сохраняем итоговый отчёт
    report_file = HOSTS_FILE.replace(".list", "_report.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    logger.info(
        f"Готово. Обработано {len(results)}/{len(hosts)} устройств. "
        f"Отчёт сохранён в '{report_file}'"
    )


if __name__ == "__main__":
    main()