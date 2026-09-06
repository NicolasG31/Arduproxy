# MAVProxy Vehicle Spoofer

A small Tkinter + pymavlink GUI app for testing a Ground Control Station (GCS). It connects to MAVProxy and lets you send hand-crafted MAVLink messages and commands *as if they came from the vehicle*, so you can trigger and observe GCS reactions (low battery warnings, GPS fix changes, mode changes, status text, command acknowledgements, etc.) without needing a real drone or a full SITL scenario.

## How it works

```
[This app]  --(spoofed MAVLink messages)-->  [MAVProxy]  --(forwards)-->  [Your GCS]
```

- The app opens a MAVLink connection (UDP/TCP/serial) using `pymavlink`, in the role of the vehicle — it sets its own `source_system` / `source_component` on outgoing packets.
- Once connected, it sends a `HEARTBEAT` message once per second on a background thread. Most GCS software (Mission Planner, QGroundControl, etc.) only considers a link "connected" once heartbeats start arriving, so this happens automatically and independently of anything else you send.
- The window has two tabs:
  - **Message** — pick any regular MAVLink message from a dropdown, shown as `ID - NAME` (e.g. `0 - HEARTBEAT`), fill in its fields in a form generated on the fly from `pymavlink`'s message definitions (so field names, types, and valid enum values always match what `pymavlink` actually supports), and click **Send** to fire it once.
  - **Command (MAV_CMD)** — pick any MAV_CMD command (e.g. `400 - MAV_CMD_COMPONENT_ARM_DISARM`), shown with its real description and per-parameter help text pulled straight from the MAVLink XML (so you know what `param1`..`param7` actually mean for that specific command), set the target system/component and confirmation, and click **Send Command** to fire it as a `COMMAND_LONG`.
  - Both pickers have a **Search** box that filters the dropdown live as you type, matching either a substring of the name or its numeric ID (e.g. typing `24` narrows the message picker to `GPS_RAW_INT`, whose ID is 24; typing `arm` narrows the command picker to `MAV_CMD_COMPONENT_ARM_DISARM`). If the current selection falls out of the filtered results, the picker jumps to the first match automatically; clearing the search restores the full list; if nothing matches, the dropdown empties but the current selection and form are left alone.
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

5. **Send a message:** on the **Message** tab, type in the search box (by name, e.g. `status`, or by numeric ID, e.g. `253`) to find `253 - STATUSTEXT`, fill in the fields (e.g. `severity` = `2 - MAV_SEVERITY_CRITICAL`, `text` = `Battery critical`), click **Send**. It should appear in your GCS as coming from the vehicle. Sent messages are logged at the bottom of the window.

6. **Send a command:** on the **Command (MAV_CMD)** tab, search `arm` to find `400 - MAV_CMD_COMPONENT_ARM_DISARM`, read the per-parameter help text (`param1` explains 1=arm/0=disarm), set `param1` to `1`, and click **Send Command**.

## Supported messages and commands

- **Messages:** every message in `pymavlink`'s ArduPilot (v2.0) dialect (~295 messages) is available on the **Message** tab — search by name or numeric ID to find the one you need. Form fields are generated automatically per message:
  - **Enum fields** (e.g. `fix_type`, `severity`) show as a dropdown of `value - NAME`.
  - **Bitmask-style fields** (e.g. `base_mode`, sensor health masks) are plain integer entries — enter the combined value directly (hex like `0x05` is accepted).
  - **Array fields** (e.g. `HOME_POSITION.q`, `BATTERY_STATUS.voltages`) take a comma-separated list of values.
  - **Text fields** (e.g. `STATUSTEXT.text`) are plain text entries, truncated to the MAVLink field's max length.

  Sending a `HEARTBEAT` manually (e.g. to simulate an arm/mode change) also updates the state used by the background auto-heartbeat, so it keeps reflecting that change every second afterward instead of reverting.

- **Commands:** every `MAV_CMD` (~189 commands) is available on the **Command (MAV_CMD)** tab, sent as a `COMMAND_LONG`. Selecting a command shows its real description and, for each of `param1`..`param7`, the actual per-parameter help text documented in the MAVLink XML (via `pymavlink`'s `enums['MAV_CMD'][value].param` metadata) — so you know what each parameter means for that specific command instead of guessing. `target_system`, `target_component`, and `confirmation` are set alongside the params.

## Project layout

| File | Purpose |
|---|---|
| `main.py` | Entry point — creates the Tk root window and starts the app |
| `gui.py` | Connect dialog, main window (Message tab + Command tab), the shared `SearchablePicker` search/dropdown widget, dynamic parameter forms, send/log logic |
| `mav_connection.py` | Wraps a `pymavlink` connection; runs the background heartbeat thread; thread-safe `send()` |
| `mav_messages.py` | Reads message/field/command metadata off `pymavlink`'s ArduPilot dialect and builds/parses messages and commands from form input |

## Known limitations / ideas for v2

- No repeat/streaming send — every click (besides the automatic heartbeat) sends exactly one message.
- Commands only support `COMMAND_LONG`, not `COMMAND_INT` (which uses `x`/`y`/`z` + a coordinate frame instead of `param5`-`param7`, and is mainly used for guided-mode position commands).
- Bitmask fields are raw integer entry rather than a checkbox-per-flag UI.
- No display of `COMMAND_ACK` or any other reply the GCS/MAVProxy might send back — this app only sends, it doesn't listen.

## A note on `pymavlink` field metadata

While building this, we found that in the installed `pymavlink` version, a generated message class's `fieldtypes` list is indexed by **constructor-argument order** (`fieldnames`), while its `array_lengths` list is indexed by **wire-pack order** (`ordered_fieldnames`) — the two orders differ whenever a message mixes field sizes (e.g. `BATTERY_STATUS`). `mav_messages.get_field_specs()` looks array length up by field name rather than by position to work around this; keep that in mind if you see an array field getting the wrong length after a `pymavlink` upgrade.
