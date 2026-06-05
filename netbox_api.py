from utils.utils import _slugify
import logging
import requests
import os
from dotenv import load_dotenv


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

NETBOX_URL = os.getenv("URL_NETBOX")
API_TOKEN  = os.getenv("API_TOKEN")
API_KEY    = os.getenv("API_KEY")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}.{API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

ROUTER_MANUFACTURERS = {"mikrotik"}


# ---------------------------------------------------------------------------
# Определение роли
# ---------------------------------------------------------------------------

def resolve_device_role(manufacturer: str) -> str:
    if manufacturer.strip().lower() in ROUTER_MANUFACTURERS:
        return "Router"
    return "Switch"


# ---------------------------------------------------------------------------
# Базовые HTTP-обёртки
# ---------------------------------------------------------------------------

def api_get(endpoint: str, params: dict) -> dict:
    url = f"{NETBOX_URL}/api/{endpoint}/"
    response = requests.get(url, headers=HEADERS, params=params )
    response.raise_for_status()
    return response.json()


def get_object_id(endpoint: str, filters: dict) -> int | None:
    result  = api_get(endpoint, filters)
    objects = result.get("results", [])
    return objects[0]["id"] if objects else None


def create_object(endpoint: str, data: dict, object_name: str) -> int | None:
    url      = f"{NETBOX_URL}/api/{endpoint}/"
    response = requests.post(url, headers=HEADERS, json=data )

    if response.status_code == 201:
        object_id = response.json()["id"]
        logger.info(f"{object_name} создан, ID: {object_id}")
        return object_id

    elif response.status_code == 400 and "already exists" in response.text:
        object_id = get_object_id(endpoint, {"slug": data.get("slug", "")})
        logger.info(f"{object_name} уже существует, ID: {object_id}")
        return object_id

    else:
        logger.error(f"Неожиданный ответ {response.status_code}: {response.text}")
        raise ValueError(f"Не удалось создать {object_name}: {response.text}")


def patch_object(endpoint: str, object_id: int, data: dict, object_name: str):
    url      = f"{NETBOX_URL}/api/{endpoint}/{object_id}/"
    response = requests.patch(url, headers=HEADERS, json=data )

    if response.status_code == 200:
        logger.info(f"{object_name} обновлён (ID: {object_id})")
    else:
        logger.error(f"Ошибка обновления {object_name}: {response.status_code} {response.text}")
        raise ValueError(f"Не удалось обновить {object_name}: {response.text}")


# ---------------------------------------------------------------------------
# Производитель и тип устройства
# ---------------------------------------------------------------------------

def create_or_get_manufacturer_id(device: dict) -> int:
    manufacturer_name = device.get("manufacturer")
    manufacturer_slug = _slugify(manufacturer_name)
    manufacturer_id   = get_object_id("dcim/manufacturers", {"name": manufacturer_name})

    if not manufacturer_id:
        manufacturer_id = create_object(
            "dcim/manufacturers",
            {"name": manufacturer_name, "slug": manufacturer_slug},
            f"Производитель '{manufacturer_name}'",
        )
    else:
        logger.info(f"Производитель '{manufacturer_name}' уже существует, ID: {manufacturer_id}")

    return manufacturer_id


def create_or_get_device_type_id(manufacturer_id: int, device: dict) -> int:
    model            = device.get("device_type")
    device_type_slug = _slugify(model)
    device_type_id   = get_object_id(
        "dcim/device-types",
        {"manufacturer_id": manufacturer_id, "model": model},
    )

    if not device_type_id:
        device_type_id = create_object(
            "dcim/device-types",
            {
                "manufacturer":  manufacturer_id,
                "model":         model,
                "slug":          device_type_slug,
                "is_full_depth": False,
            },
            f"Тип устройства '{model}'",
        )
    else:
        logger.info(f"Тип устройства '{model}' уже существует, ID: {device_type_id}")

    return device_type_id


# ---------------------------------------------------------------------------
# Устройство
# ---------------------------------------------------------------------------

def get_or_create_device_id(device: dict) -> int | None:
    name    = device.get("name") or f"{device.get('ipaddress')}_{device.get('device_type')}"
    site    = device.get("site")
    site_id = get_object_id("dcim/sites", {"name": site})

    existing_id = get_object_id("dcim/devices", {"name": name, "site_id": site_id})
    if existing_id:
        logger.info(f"Устройство '{name}' уже существует, ID: {existing_id}")
        return existing_id

    manufacturer    = device.get("manufacturer", "")
    role            = resolve_device_role(manufacturer)
    manufacturer_id = create_or_get_manufacturer_id(device)
    device_type_id  = create_or_get_device_type_id(manufacturer_id, device)
    role_id         = get_object_id("dcim/device-roles", {"name": role})

    logger.info(f"Роль устройства (производитель '{manufacturer}'): {role}")

    return create_object(
        "dcim/devices",
        {
            "name":        name,
            "device_type": device_type_id,
            "role":        role_id,
            "site":        site_id,
        },
        f"Устройство '{name}'",
    )


# ---------------------------------------------------------------------------
# Интерфейсы
# ---------------------------------------------------------------------------

def create_interface(interface: dict, device_id: int) -> int | None:
    interface_name = interface.get("name")
    data = {
        "device":      device_id,
        "name":        interface_name,
        "type":        interface.get("type_int", "1000base-t"),
        "mac_address": interface.get("mac_address") or None,
    }

    url      = f"{NETBOX_URL}/api/dcim/interfaces/"
    response = requests.post(url, headers=HEADERS, json=data )

    if response.status_code == 201:
        interface_id = response.json()["id"]
        logger.info(f"Интерфейс '{interface_name}' создан, ID: {interface_id}")
        return interface_id

    logger.error(
        f"Ошибка создания интерфейса '{interface_name}': "
        f"{response.status_code} {response.text}"
    )
    return None


# ---------------------------------------------------------------------------
# IP-адреса
# ---------------------------------------------------------------------------

def create_or_get_ip_id(ip_cidr: str) -> int | None:
    """Создаёт IP (CIDR формат) или возвращает ID существующего."""
    if not ip_cidr:
        return None

    existing_id = get_object_id("ipam/ip-addresses", {"address": ip_cidr})
    if existing_id:
        logger.info(f"IP {ip_cidr} уже существует, ID: {existing_id}")
        return existing_id

    return create_object(
        "ipam/ip-addresses",
        {"address": ip_cidr, "status": "active"},
        f"IP-адрес {ip_cidr}",
    )


def assign_ip_to_interface(ip_id: int, interface_id: int, ip_cidr: str):
    """Привязывает IP к интерфейсу через PATCH."""
    patch_object(
        "ipam/ip-addresses",
        ip_id,
        {
            "assigned_object_type": "dcim.interface",
            "assigned_object_id":   interface_id,
        },
        f"привязка IP {ip_cidr} → interface {interface_id}",
    )


def create_interfaces_with_ips(interfaces: list, device_id: int) -> dict[str, int]:
    """
    Для каждого интерфейса:
      1. Создаёт интерфейс
      2. Если у интерфейса есть IP — создаёт его и привязывает к интерфейсу
    Возвращает {ip_cidr: ip_id} всех назначенных IP.
    """
    assigned_ips = {}

    logger.info(f"Всего интерфейсов для обработки: {len(interfaces)}")

    for iface in interfaces:
        iface_name = iface.get("name", "???")
        ipaddress  = iface.get("ipaddress", "")
        mask       = iface.get("mask", "")

        logger.info(
            f"  Интерфейс '{iface_name}': "
            f"ip={ipaddress!r}, mask={mask!r}, mac={iface.get('mac_address')!r}"
        )

        interface_id = create_interface(iface, device_id)
        if interface_id is None:
            logger.warning(f"  '{iface_name}': интерфейс не создан, пропускаем.")
            continue

        # Проверяем наличие IP и маски
        if not ipaddress:
            logger.info(f"  '{iface_name}': IP отсутствует, пропускаем назначение.")
            continue

        if not mask:
            logger.warning(
                f"  '{iface_name}': IP={ipaddress} есть, но маска пустая — "
                f"пропускаем (NetBox требует CIDR формат)."
            )
            continue

        ip_cidr = f"{ipaddress}/{mask}"
        logger.info(f"  '{iface_name}': создаём/получаем IP {ip_cidr}")

        ip_id = create_or_get_ip_id(ip_cidr)
        if ip_id is None:
            logger.error(f"  '{iface_name}': не удалось создать IP {ip_cidr}")
            continue

        assign_ip_to_interface(ip_id, interface_id, ip_cidr)
        assigned_ips[ip_cidr] = ip_id
        logger.info(f"  '{iface_name}': IP {ip_cidr} назначен (ID: {ip_id})")

    logger.info(f"Назначено IP на интерфейсы: {list(assigned_ips.keys())}")
    return assigned_ips


# ---------------------------------------------------------------------------
# Primary IP
# ---------------------------------------------------------------------------

def set_primary_ip(device_id: int, raw_ip: str, assigned_ips: dict[str, int]):
    """
    Назначает primary_ip4 устройству через PATCH.

    Логика поиска IP (по приоритету):
      1. Точное совпадение с маской среди IP интерфейсов ('10.2.0.2/26')
      2. Совпадение только по хосту среди IP интерфейсов ('10.2.0.2' → '10.2.0.2/26')
      3. IP не назначен ни на один интерфейс (management IP из другой подсети) —
         создаём/берём его как /32 и назначаем напрямую на устройство без интерфейса
    """
    ip_id = None

    # 1. Точное совпадение
    if raw_ip in assigned_ips:
        ip_id = assigned_ips[raw_ip]
        logger.info(f"primary IP: точное совпадение {raw_ip} → ID {ip_id}")

    # 2. Совпадение по хосту (игнорируем маску)
    if ip_id is None:
        match = next(
            (cidr for cidr in assigned_ips if cidr.split("/")[0] == raw_ip),
            None,
        )
        if match:
            ip_id = assigned_ips[match]
            logger.info(f"primary IP: совпадение по хосту {raw_ip} → {match} (ID {ip_id})")

    # 3. IP не найден среди интерфейсов — создаём виртуальный mgmt-интерфейс,
    #    привязываем к нему IP /32, затем назначаем primary.
    #    NetBox требует чтобы primary IP был назначен интерфейсу этого устройства.
    if ip_id is None:
        primary_cidr = f"{raw_ip}/32"
        logger.info(
            f"primary IP {raw_ip} не найден среди IP интерфейсов — "
            f"создаём mgmt-интерфейс и привязываем {primary_cidr}"
        )

        mgmt_url  = f"{NETBOX_URL}/api/dcim/interfaces/"
        mgmt_data = {"device": device_id, "name": "mgmt", "type": "virtual"}
        mgmt_resp = requests.post(mgmt_url, headers=HEADERS, json=mgmt_data)

        if mgmt_resp.status_code != 201:
            logger.error(f"Не удалось создать mgmt-интерфейс: {mgmt_resp.status_code} {mgmt_resp.text}")
            return

        mgmt_interface_id = mgmt_resp.json()["id"]
        logger.info(f"mgmt-интерфейс создан, ID: {mgmt_interface_id}")

        ip_id = create_or_get_ip_id(primary_cidr)
        if ip_id is None:
            logger.error(f"Не удалось создать IP {primary_cidr}, primary_ip4 не установлен.")
            return

        assign_ip_to_interface(ip_id, mgmt_interface_id, primary_cidr)

    patch_object(
        "dcim/devices",
        device_id,
        {"primary_ip4": ip_id},
        f"primary_ip4 устройства (ID: {device_id})",
    )


# ---------------------------------------------------------------------------
# Главная точка входа
# ---------------------------------------------------------------------------

def create_device(device: dict):
    """
    Порядок операций (требование NetBox API):
      1. Создать устройство БЕЗ primary_ip4
      2. Создать интерфейсы → привязать IP к интерфейсам
      3. PATCH устройства → установить primary_ip4
         (NetBox проверяет что IP назначен интерфейсу этого устройства)
    """
    name   = device.get("name") or f"{device.get('ipaddress')}_{device.get('device_type')}"
    raw_ip = device.get("ipaddress", "")

    logger.info(f"{'='*60}")
    logger.info(f"Обрабатываем устройство: '{name}' ({raw_ip})")

    # Шаг 1
    logger.info(f"[1/3] Создаём устройство '{name}'")
    device_id = get_or_create_device_id(device)
    if not device_id:
        logger.error(f"Не удалось создать устройство '{name}', прерываем.")
        return

    # Шаг 2
    interfaces = device.get("interfaces", [])
    logger.info(f"[2/3] Обрабатываем интерфейсы ({len(interfaces)} шт.)")
    assigned_ips = create_interfaces_with_ips(interfaces, device_id)

    # Шаг 3
    logger.info(f"[3/3] Устанавливаем primary_ip4: {raw_ip}")
    set_primary_ip(device_id, raw_ip, assigned_ips)

    logger.info(f"Устройство '{name}' полностью обработано.")