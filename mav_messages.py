"""Curated MAVLink message catalog and field (de)serialization helpers.

Built around pymavlink's ArduPilot dialect (v2.0), which is the dialect
ArduPilot/SITL and MAVProxy use. Field metadata (names, C types, array
lengths, associated enums) is read directly off the generated message
classes so the GUI can build input forms without hardcoding per-message
layouts.
"""
from collections import namedtuple

from pymavlink.dialects.v20 import ardupilotmega as mavlink

# Enums that are bitmasks rather than single-value choices (e.g. combined
# sensor/fault flags). A single-select dropdown doesn't fit these, so
# fields using them fall back to a plain integer entry (hex like 0x05 works).
BITMASK_ENUM_NAMES = frozenset({
    "MAV_MODE_FLAG",
    "MAV_MODE_FLAG_DECODE_POSITION",
    "MAV_SYS_STATUS_SENSOR",
    "MAV_SYS_STATUS_SENSOR_EXTENDED",
    "MAV_BATTERY_FAULT",
    "EKF_STATUS_FLAGS",
    "ESTIMATOR_STATUS_FLAGS",
})

CURATED_MESSAGES = [
    "HEARTBEAT",
    "SYS_STATUS",
    "GPS_RAW_INT",
    "GLOBAL_POSITION_INT",
    "ATTITUDE",
    "VFR_HUD",
    "BATTERY_STATUS",
    "STATUSTEXT",
    "RC_CHANNELS",
    "GPS_GLOBAL_ORIGIN",
    "EKF_STATUS_REPORT",
    "LOCAL_POSITION_NED",
    "MISSION_CURRENT",
    "HOME_POSITION",
    "RANGEFINDER",
]

FieldSpec = namedtuple("FieldSpec", ["name", "ctype", "array_len", "enum_name"])

_ALL_MESSAGES = {}
for _cls in mavlink.mavlink_map.values():
    _ALL_MESSAGES[_cls.msgname] = _cls


def get_message_class(msg_name):
    return _ALL_MESSAGES[msg_name]


def get_field_specs(msg_cls):
    """Field specs in constructor-argument order.

    fieldtypes is indexed by fieldnames (constructor order), but
    array_lengths is indexed by ordered_fieldnames (wire-pack order) -
    these two orders differ whenever field sizes are mixed, so array
    length must be looked up by name rather than by zipping positionally
    with fieldnames.
    """
    array_len_by_name = dict(zip(msg_cls.ordered_fieldnames, msg_cls.array_lengths))
    specs = []
    for name, ctype in zip(msg_cls.fieldnames, msg_cls.fieldtypes):
        enum_name = msg_cls.fieldenums_by_name.get(name)
        specs.append(FieldSpec(name, ctype, array_len_by_name.get(name, 0), enum_name))
    return specs


def is_bitmask_enum(enum_name):
    return enum_name in BITMASK_ENUM_NAMES


def get_enum_options(enum_name):
    """Sorted list of (value, display_label) for a MAVLink enum."""
    enum_dict = mavlink.enums.get(enum_name, {})
    options = [(value, entry.name) for value, entry in enum_dict.items() if isinstance(value, int)]
    options.sort(key=lambda pair: pair[0])
    return options


def default_value_str(spec):
    if spec.ctype == "char":
        return ""
    if spec.array_len:
        return ",".join(["0"] * spec.array_len)
    if spec.ctype in ("float", "double"):
        return "0.0"
    return "0"


def parse_scalar(ctype, text):
    text = text.strip()
    if ctype in ("float", "double"):
        return float(text) if text else 0.0
    return int(text, 0) if text else 0  # base 0 allows hex like 0x05


def build_message(msg_cls, field_specs, raw_values):
    """raw_values: dict of field name -> string from the GUI form."""
    kwargs = {}
    for spec in field_specs:
        raw = raw_values[spec.name]
        if spec.ctype == "char":
            kwargs[spec.name] = raw.encode("ascii", errors="replace")[: spec.array_len]
        elif spec.array_len:
            parts = raw.split(",")
            values = []
            for i in range(spec.array_len):
                part = parts[i] if i < len(parts) else "0"
                values.append(parse_scalar(spec.ctype, part))
            kwargs[spec.name] = values
        else:
            kwargs[spec.name] = parse_scalar(spec.ctype, raw)
    return msg_cls(**kwargs)
