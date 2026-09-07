"""MAVLink message/command catalog and field (de)serialization helpers.

Built around pymavlink's ArduPilot dialect (v2.0), which is the dialect
ArduPilot/SITL and MAVProxy use. Field metadata (names, C types, array
lengths, associated enums) is read directly off the generated message
classes so the GUI can build input forms without hardcoding per-message
layouts. Every message in the dialect is exposed via MESSAGE_NAMES; MAV_CMD
commands (sent as COMMAND_LONG) are exposed separately via
get_command_options()/build_command_long(), since they need per-command
param help text rather than generic field specs. build_command_ack() and
format_incoming_message() support the GUI's incoming-message handling
(logging + auto-ACK of commands received from MAVProxy/the GCS).
"""
import re
from collections import namedtuple

from pymavlink.dialects.v20 import ardupilotmega as mavlink

_INT_CTYPE_RE = re.compile(r"^(u?)int(8|16|32|64)_t$")

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

FieldSpec = namedtuple("FieldSpec", ["name", "ctype", "array_len", "enum_name"])

_ALL_MESSAGES = {}
for _cls in mavlink.mavlink_map.values():
    _ALL_MESSAGES[_cls.msgname] = _cls

# Every message in the dialect, sorted by MAVLink message ID.
MESSAGE_NAMES = sorted(_ALL_MESSAGES.keys(), key=lambda name: _ALL_MESSAGES[name].id)


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


def get_bitmask_flag_options(enum_name):
    """Sorted list of (bit_value, name) for a bitmask enum's individual flags.

    Only single-bit (power-of-two) entries are included, since those are the
    ones that make sense as independent checkboxes to OR together; a
    zero-valued "NONE" entry or a composite/reserved value wouldn't.
    """
    options = get_enum_options(enum_name)
    return [(value, name) for value, name in options if value and (value & (value - 1)) == 0]


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


def int_ctype_bits(ctype):
    """Bit width of a fixed-width integer ctype (e.g. 32 for "int32_t" or
    "uint32_t"), or None if ctype isn't one of those (float/double/char)."""
    m = _INT_CTYPE_RE.match(ctype)
    return int(m.group(2)) if m else None


def wrap_int_to_ctype(value, ctype):
    """Mask value down to ctype's bit width and, for signed ctypes, re-apply
    two's complement - so typing the full raw bit pattern (e.g. 0xFFFFFFFF
    for an int32_t field, to mean -1) works instead of struct.pack rejecting
    it as out of range."""
    bits = int_ctype_bits(ctype)
    if bits is None:
        return value
    value &= (1 << bits) - 1
    if ctype.startswith("int") and value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def parse_scalar(ctype, text):
    text = text.strip()
    if ctype in ("float", "double"):
        return float(text) if text else 0.0
    value = int(text, 0) if text else 0  # base 0 allows hex like 0x05
    return wrap_int_to_ctype(value, ctype)


def get_command_options():
    """Sorted list of (command_value, MAV_CMD_NAME) for every known command."""
    return get_enum_options("MAV_CMD")


def get_command_description(command_value):
    entry = mavlink.enums["MAV_CMD"].get(command_value)
    return entry.description if entry else ""


def get_command_name(command_value):
    entry = mavlink.enums["MAV_CMD"].get(command_value)
    return entry.name if entry else f"UNKNOWN_COMMAND_{command_value}"


def get_command_param_help(command_value):
    """dict of {1..7: help text} for a MAV_CMD's param1..param7, as documented
    in the MAVLink XML. Missing/unused params come back as an empty string."""
    entry = mavlink.enums["MAV_CMD"].get(command_value)
    param_help = dict(getattr(entry, "param", None) or {}) if entry else {}
    return {i: param_help.get(i, "").strip() for i in range(1, 8)}


def build_command_long(command_value, target_system, target_component, confirmation, params):
    """params: sequence of 7 floats (param1..param7)."""
    msg_cls = get_message_class("COMMAND_LONG")
    kwargs = {
        "target_system": target_system,
        "target_component": target_component,
        "command": command_value,
        "confirmation": confirmation,
    }
    for i, value in enumerate(params, start=1):
        kwargs[f"param{i}"] = value
    return msg_cls(**kwargs)


def build_command_ack(command_value, result_value, target_system, target_component):
    msg_cls = get_message_class("COMMAND_ACK")
    return msg_cls(
        command=command_value,
        result=result_value,
        target_system=target_system,
        target_component=target_component,
    )


def format_incoming_message(msg):
    """Compact single-line field summary for the log, excluding bookkeeping keys."""
    fields = msg.to_dict()
    fields.pop("mavpackettype", None)
    return ", ".join(f"{key}={value}" for key, value in fields.items())


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
