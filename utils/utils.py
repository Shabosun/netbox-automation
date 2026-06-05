import re
import ipaddress

def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r'[^\w\s-]', '', value)  # убираем всё кроме букв/цифр/пробелов/дефиса
    value = re.sub(r'[\s_]+', '-', value)   # пробелы и подчёркивания → дефис
    value = re.sub(r'-+', '-', value)       # схлопываем двойные дефисы
    value = value.strip('-')                # убираем дефисы по краям
    return value[:100]                      # NetBox ограничивает slug 100 символами

def is_valid_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return ip not in ("0.0.0.0", "")
    except ValueError:
        return False

def convert_mask_bit_to_decimal(mask: str) -> str:
    """Конвертирует маску 255.255.255.0 → 24. Если уже число — возвращает как есть."""
    try:
        int(mask)
        return mask
    except ValueError:
        pass
    try:
        return str(ipaddress.IPv4Network(f"0.0.0.0/{mask}", strict=False).prefixlen)
    except Exception:
        return mask