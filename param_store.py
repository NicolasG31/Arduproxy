"""In-memory table of vehicle parameters, plus the message-building side of
the MAVLink parameter protocol (PARAM_REQUEST_LIST / PARAM_REQUEST_READ /
PARAM_SET -> PARAM_VALUE). This app answers these as the vehicle would, the
same spirit as the existing auto-ACK of COMMAND_LONG - it lets a GCS's
"refresh parameters" / "write parameters" screens work against Arduproxy
instead of hanging, while you control exactly what values it reports.

Parameter values are always carried on the wire as the MAVLink PARAM_VALUE
float field holding the parameter's actual numeric value (the ArduPilot/
QGroundControl "cast" convention), never a bit-reinterpretation of an int -
param_type only tells the GCS how to *display* it.
"""
from collections import OrderedDict

from pymavlink.dialects.v20 import ardupilotmega as mavlink

DEFAULT_PARAM_TYPE = mavlink.MAV_PARAM_TYPE_REAL32
MAX_PARAM_ID_LEN = 16


class ParamStore:
    def __init__(self):
        self._params = OrderedDict()  # name -> {"value": float, "type": int}

    def __len__(self):
        return len(self._params)

    def __contains__(self, name):
        return name in self._params

    def get(self, name):
        return self._params.get(name)

    def items(self):
        return list(self._params.items())

    def name_at(self, index):
        names = list(self._params.keys())
        return names[index] if 0 <= index < len(names) else None

    def set(self, name, value, param_type=DEFAULT_PARAM_TYPE):
        name = name[:MAX_PARAM_ID_LEN]
        self._params[name] = {"value": float(value), "type": param_type}
        return name

    def remove(self, name):
        self._params.pop(name, None)

    def build_param_value(self, name):
        """A PARAM_VALUE message for one known parameter, or None if name
        isn't in the table."""
        entry = self._params.get(name)
        if entry is None:
            return None
        names = list(self._params.keys())
        return mavlink.MAVLink_param_value_message(
            param_id=name.encode("ascii", errors="replace")[:MAX_PARAM_ID_LEN],
            param_value=entry["value"],
            param_type=entry["type"],
            param_count=len(names),
            param_index=names.index(name),
        )

    def build_all_param_values(self):
        """One PARAM_VALUE per known parameter, in table order - the reply
        to a PARAM_REQUEST_LIST."""
        return [self.build_param_value(name) for name in self._params]
