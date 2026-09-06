# Arduproxy — MAVProxy Vehicle Spoofer

A Tkinter + pymavlink GUI that connects to MAVProxy and sends spoofed MAVLink messages as if they came from the vehicle, to test GCS reactions. Full docs, architecture, and quickstart: see `README.md`.

## Rule: keep README.md in sync

Whenever you modify this app's behavior, structure, dependencies, or how to run/connect it, update `README.md` in the same change so it stays an accurate description of the app — not just a snapshot from when it was first built. This includes: adding/removing supported messages, changing the connection dialog or connection-string handling, changing file layout, adding dependencies, or fixing behavior-affecting bugs worth a user knowing about (e.g. the `array_lengths`/`fieldtypes` indexing quirk already documented there).
