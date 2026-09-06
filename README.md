# MAVProxy Vehicle Spoofer

A small Tkinter + pymavlink GUI app for testing a Ground Control Station (GCS). It connects to MAVProxy and lets you send hand-crafted MAVLink messages *as if they came from the vehicle*, so you can trigger and observe GCS reactions (low battery warnings, GPS fix changes, mode changes, status text, etc.) without needing a real drone or a full SITL scenario.

## How it works

```
[This app]  --(spoofed MAVLink messages)-->  [MAVProxy]  --(forwards)-->  [Your GCS]
```

- The app opens a MAVLink connection (UDP/TCP/serial) using `pymavlink`, in the role of the vehicle — it sets its own `source_system` / `source_component` on outgoing packets.
- Once connected, it sends a `HEARTBEAT` message once per second on a background thread. Most GCS software (Mission Planner, QGroundControl, etc.) only considers a link "connected" once heartbeats start arriving, so this happens automatically and independently of anything else you send.
- You pick a message type from a dropdown — each entry shown as `ID - NAME` (e.g. `0 - HEARTBEAT`) — fill in its fields in a form that's generated on the fly from `pymavlink`'s message definitions (so field names, types, and valid enum values always match what `pymavlink` actually supports), and click **Send** to fire it once.
- A **Search** box next to the picker filters that dropdown live as you type, matching either a substring of the message name or its numeric ID (e.g. typing `24` narrows to `GPS_RAW_INT`, whose ID is 24). If the currently selected message falls out of the filtered results, the picker jumps to the first match automatically; clearing the search restores the full list. If nothing matches, the dropdown empties but the current selection and form are left alone.
- MAVProxy receives these packets on its input link and forwards them to every output it's configured with — including your real GCS connection — exactly as if they'd come from the vehicle.

### Connecting to MAVProxy

The connect dialog takes a free-form pymavlink connection string (same syntax you'd use with `mavutil.mavlink_connection`). To feed a running MAVProxy:

1. Give MAVProxy an extra input link that binds/listens, e.g. start it with:
   ```
   --master=udpin:127.0.0.1:14550
   ```
   (in addition to whatever link it already uses to talk to your real GCS or SITL).
2. In this app's connect dialog, use a client connection pointed at that same address:
   ```
   udpout:127.0.0.1:14550
   ```

Other supported forms:

| String | Meaning |
|---|---|
| `udpout:127.0.0.1:14550` | Connect out to a MAVProxy master listening on UDP (typical case) |
| `tcp:127.0.0.1:5760` | Connect out to a MAVProxy TCP master |
| `udpin:127.0.0.1:14550` | Bind and wait for MAVProxy to connect to us instead |
| `COM3` | Serial link — set the baud rate field in the dialog |

## Quickstart

1. **Install dependencies** (a virtualenv with this already done is included under `venv/`; skip to step 2 if using it):
   ```
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```

2. **Start MAVProxy** with an extra input link for this app to connect to, e.g.:
   ```
   mavproxy.py --master=<your SITL/vehicle link> --out=<your GCS address> --master=udpin:127.0.0.1:14550
   ```

3. **Run the app:**
   ```
   venv\Scripts\python.exe main.py
   ```

4. **Connect:** click **Connect...**, leave the default `udpout:127.0.0.1:14550` (or edit to match your setup), and click **Connect**. The status bar should switch to "Connected" and HEARTBEATs start flowing.

5. **Send a message:** type in the search box (by name, e.g. `status`, or by numeric ID, e.g. `253`) to find `253 - STATUSTEXT`, fill in the fields (e.g. `severity` = `2 - MAV_SEVERITY_CRITICAL`, `text` = `Battery critical`), click **Send**. It should appear in your GCS as coming from the vehicle. Sent messages are logged at the bottom of the window.

## Supported messages (v1)

A curated set of the most commonly-needed telemetry/status messages:

`HEARTBEAT`, `SYS_STATUS`, `GPS_RAW_INT`, `GLOBAL_POSITION_INT`, `ATTITUDE`, `VFR_HUD`, `BATTERY_STATUS`, `STATUSTEXT`, `RC_CHANNELS`, `GPS_GLOBAL_ORIGIN`, `EKF_STATUS_REPORT`, `LOCAL_POSITION_NED`, `MISSION_CURRENT`, `HOME_POSITION`, `RANGEFINDER`.

Form fields are generated automatically per message:
- **Enum fields** (e.g. `fix_type`, `severity`) show as a dropdown of `value - NAME`.
- **Bitmask-style fields** (e.g. `base_mode`, sensor health masks) are plain integer entries — enter the combined value directly (hex like `0x05` is accepted).
- **Array fields** (e.g. `HOME_POSITION.q`, `BATTERY_STATUS.voltages`) take a comma-separated list of values.
- **Text fields** (e.g. `STATUSTEXT.text`) are plain text entries, truncated to the MAVLink field's max length.

Sending a `HEARTBEAT` manually (e.g. to simulate an arm/mode change) also updates the state used by the background auto-heartbeat, so it keeps reflecting that change every second afterward instead of reverting.

## Project layout

| File | Purpose |
|---|---|
| `main.py` | Entry point — creates the Tk root window and starts the app |
| `gui.py` | Connect dialog, main window, dynamic parameter form, send/log logic |
| `mav_connection.py` | Wraps a `pymavlink` connection; runs the background heartbeat thread; thread-safe `send()` |
| `mav_messages.py` | Reads message/field metadata off `pymavlink`'s ArduPilot dialect and builds/parses messages from form input |

## Known limitations / ideas for v2

- No repeat/streaming send — every click (besides the automatic heartbeat) sends exactly one message.
- Only the 15 curated messages above are available, not the full MAVLink dialect (~300+ messages).
- Bitmask fields are raw integer entry rather than a checkbox-per-flag UI.

## A note on `pymavlink` field metadata

While building this, we found that in the installed `pymavlink` version, a generated message class's `fieldtypes` list is indexed by **constructor-argument order** (`fieldnames`), while its `array_lengths` list is indexed by **wire-pack order** (`ordered_fieldnames`) — the two orders differ whenever a message mixes field sizes (e.g. `BATTERY_STATUS`). `mav_messages.get_field_specs()` looks array length up by field name rather than by position to work around this; keep that in mind if you extend the curated message list and see array fields getting the wrong length.
