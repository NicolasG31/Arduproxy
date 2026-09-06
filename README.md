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
  - Next to **Send** / **Send Command** is a **"Repeat every: [rate] [s/Hz] [Start Repeating]"** control — fill in a message/command's fields as usual, pick a rate (either an interval in seconds like `0.5`, or a frequency in Hz like `2`), and click it to have that exact message/command resent on a background timer instead of just once.
- Every active repeat shows up in the **▶ Repeating** panel below the tabs (visible regardless of which tab is active) — collapsed by default, showing just a count (e.g. `▶ Repeating (2 active)`); click it to expand and see each entry, with its rate editable in place, a **Pause**/**Resume** toggle, a **Remove** button, and a live status line (send count and time since last send, or the last error if sends started failing).
- MAVProxy receives these packets on its input link and forwards them to every output it's configured with — including your real GCS connection — exactly as if they'd come from the vehicle.
- The app also **listens**: anything MAVProxy forwards back down that same link (e.g. a `COMMAND_LONG` your GCS issues — arm, mode change, takeoff, ...) is logged as a `RECV` line. By default it also **auto-replies with `COMMAND_ACK`** to any incoming `COMMAND_LONG`, via the **"Incoming commands"** controls at the bottom of the **Command (MAV_CMD)** tab (checkbox + result dropdown) — without this, GCS actions that wait for an acknowledgement would just hang against this app instead of showing you a reaction.

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

7. **Repeat a message:** on the **Message** tab, pick e.g. `ATTITUDE`, set "Repeat every" to `10` with unit `Hz`, and click **Start Repeating**. The **▶ Repeating** bar below now reads `▶ Repeating (1 active)`; click it to expand and watch the send count tick up, then try **Pause**, **Resume**, changing the rate and clicking **Apply**, and finally **Remove**.

8. **See it listen:** trigger anything in your real GCS that sends a command to the vehicle (e.g. its arm button). You should see a `RECV COMMAND_LONG ...` line in the log almost immediately followed by `Auto-ACK sent for ...`, and your GCS should show the command as accepted instead of timing out.

## Listening and auto-ACK

The app doesn't just send — the same link is read continuously in the background:

- Every message received is logged as `RECV <TYPE> from sys<X>.comp<Y>: <fields>`.
- Any incoming `COMMAND_LONG` gets an automatic `COMMAND_ACK` reply when the **"Auto-ACK incoming COMMAND_LONG with result:"** checkbox, in the **Incoming commands** box at the bottom of the **Command (MAV_CMD)** tab, is ticked — **on by default**. The ack is addressed back to whoever sent the command (its `target_system`/`target_component` are set from the incoming message's source, not the app's own identity), with `command` matching what was requested and `result` taken from the dropdown next to the checkbox (any `MAV_RESULT` value — `ACCEPTED`, `DENIED`, `TEMPORARILY_REJECTED`, etc. — so you can test how your GCS handles a rejected command, not just the happy path).
- Turn the checkbox off to test what your GCS does when a command is never acknowledged (e.g. a timeout/retry path), since that's now a deliberate choice rather than this app's only mode.
- A **Clear Log** button (top-right of the log panel) is provided since RECV lines can add up quickly if your GCS polls frequently.

### A Windows-specific gotcha we hit building this

pymavlink's UDP *client* sockets (`udpout:`, or `udp:` without `input=True`) are only bound to a local port implicitly, by the OS, on their first outgoing `sendto()`. On Windows, calling `recvfrom()` on the socket before that first send has happened raises `WSAEINVAL` ("An invalid argument was supplied") — and since the receive thread and the heartbeat thread both start immediately on connect, the receive thread could win that race. `mav_connection._bind_udp_client_socket()` binds the socket explicitly and synchronously right after connecting, before either thread touches it, closing the race. This only matters for UDP client mode; UDP server (`udpin:`) and other connection types were never affected.

## Repeating sends

Any message or command can be sent on a repeating timer instead of once:

- The **Repeating** panel starts **collapsed** (just a `▶ Repeating` bar, or `▶ Repeating (N active)` once something is running) so it stays out of the way when you're not using it; click the bar to expand/collapse. Starting or stopping a repeat updates the count immediately whether or not the panel is expanded.
- **Rate:** enter a number and choose the unit — **s** (interval in seconds, e.g. `0.5` = twice a second) or **Hz** (times per second, e.g. `2`). Both are accepted everywhere a rate is entered, including when editing an existing repeat's rate in the panel.
- **Field values are snapshotted** at the moment you click **Start Repeating** — editing the form afterward does not affect an already-running repeat; start a new one (or remove and re-add) to change what's being sent.
- **Commands auto-increment `confirmation`** on every repeat (starting from whatever value was in the Confirmation field when you clicked Start Repeating, wrapping at 256), mirroring how a real GCS marks retries of the same command rather than resending byte-identical packets forever.
- **Pause** stops sending without losing the entry or its send count; **Resume** continues from where it left off. **Remove** stops and deletes it.
- Rate changes made via the panel's **Apply** button take effect from the entry's *next* send cycle onward (a change mid-wait doesn't cut the current wait short).
- **Disconnecting stops and clears every active repeat** (both the explicit Disconnect button and an automatic disconnect from a failed heartbeat) — repeats aren't paused-and-resumable across a reconnect, they're gone; start them again after reconnecting. This is a deliberate simplification, not a limitation we plan to lift automatically, since silently resuming background sends on reconnect seemed more surprising than convenient.
- The `HEARTBEAT` auto-sent every 1s by the connection itself (see above) is independent of this feature — you *can* also add a repeating `HEARTBEAT` from the Message tab (e.g. at a different rate), but note that would mean two separate heartbeat streams running at once.

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
| `gui.py` | Connect dialog, main window (Message tab + Command tab + Repeating panel + incoming-traffic controls), the shared `SearchablePicker` search/dropdown widget, dynamic parameter forms, send/receive/log logic |
| `mav_connection.py` | Wraps a `pymavlink` connection; runs the background heartbeat and receive threads; thread-safe `send()`; the Windows UDP-client bind workaround |
| `mav_messages.py` | Reads message/field/command metadata off `pymavlink`'s ArduPilot dialect and builds/parses messages, commands, and command acks from form input |
| `repeat_manager.py` | One background thread per active repeat (rate, pause, send count, last error); independent of the connection's own heartbeat loop |

## Known limitations / ideas for v2

- Commands only support `COMMAND_LONG`, not `COMMAND_INT` (which uses `x`/`y`/`z` + a coordinate frame instead of `param5`-`param7`, and is mainly used for guided-mode position commands). Repeating inherits this limitation too.
- Bitmask fields are raw integer entry rather than a checkbox-per-flag UI.
- Auto-ACK only handles `COMMAND_LONG`; other request/response protocols a real GCS might expect (`PARAM_REQUEST_LIST`→`PARAM_VALUE` streaming, mission upload/download) aren't emulated, so GCS screens relying on those will still hang against this app.
- Repeats don't survive a disconnect/reconnect (see "Repeating sends" above) — this was a deliberate v1 choice, not an oversight.
- Incoming messages are only logged as text, not shown in a structured/filterable view — with a chatty GCS this can scroll fast (use **Clear Log**).

## A note on `pymavlink` field metadata

While building this, we found that in the installed `pymavlink` version, a generated message class's `fieldtypes` list is indexed by **constructor-argument order** (`fieldnames`), while its `array_lengths` list is indexed by **wire-pack order** (`ordered_fieldnames`) — the two orders differ whenever a message mixes field sizes (e.g. `BATTERY_STATUS`). `mav_messages.get_field_specs()` looks array length up by field name rather than by position to work around this; keep that in mind if you see an array field getting the wrong length after a `pymavlink` upgrade.
