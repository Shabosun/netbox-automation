from pysnmp.hlapi import SnmpEngine

_engine = None

def get_snmp_engine():
    """Get global SnmpEngine instance"""
    global _engine
    if _engine is None:
        _engine = SnmpEngine()
    return _engine


# Использование в других модулях:
# from snmp_engine import get_snmp_engine
# engine = get_snmp_engine()