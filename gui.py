"""Tkinter GUI: connect dialog + main window with two tabs -
"Message" (regular MAVLink telemetry/status messages) and
"Command (MAV_CMD)" (COMMAND_LONG) - each with a searchable picker,
a dynamically generated parameter form, and a repeat-send control; plus a
shared "Repeating" panel and send log.
"""
import itertools
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import mav_messages as mm
from mav_connection import ConnectionManager
from repeat_manager import RepeatManager

REPEAT_STATUS_REFRESH_MS = 500

DEFAULT_CONN_STRING = "udpout:127.0.0.1:14550"

CONNECTION_HELP = (
    "Examples:\n"
    "  udpout:127.0.0.1:14550   connect out to a MAVProxy master listening on UDP\n"
    "  tcp:127.0.0.1:5760       connect out to a MAVProxy TCP master\n"
    "  udpin:127.0.0.1:14550    bind and wait for MAVProxy to connect to us\n"
    "  COM3                     serial link (set baud rate below)\n\n"
    "To feed a running MAVProxy, add an extra input link on its side, e.g.\n"
    "  --master=udpin:127.0.0.1:14550\n"
    "and point this app at it with udpout:127.0.0.1:14550."
)


class ConnectDialog(tk.Toplevel):
    """Modal dialog that collects connection settings and connects."""

    def __init__(self, parent, conn_mgr: ConnectionManager):
        super().__init__(parent)
        self.conn_mgr = conn_mgr
        self.connected = False

        self.title("Connect to MAVProxy")
        self.resizable(False, False)
        self.transient(parent)

        form = ttk.Frame(self, padding=12)
        form.grid(row=0, column=0, sticky="nsew")

        ttk.Label(form, text="Connection string:").grid(row=0, column=0, sticky="w", pady=3)
        self.conn_var = tk.StringVar(value=DEFAULT_CONN_STRING)
        ttk.Entry(form, textvariable=self.conn_var, width=36).grid(row=0, column=1, pady=3)

        ttk.Label(form, text="Source system ID:").grid(row=1, column=0, sticky="w", pady=3)
        self.sysid_var = tk.StringVar(value="1")
        ttk.Entry(form, textvariable=self.sysid_var, width=10).grid(row=1, column=1, sticky="w", pady=3)

        ttk.Label(form, text="Source component ID:").grid(row=2, column=0, sticky="w", pady=3)
        self.compid_var = tk.StringVar(value="1")
        ttk.Entry(form, textvariable=self.compid_var, width=10).grid(row=2, column=1, sticky="w", pady=3)

        ttk.Label(form, text="Baud (serial only):").grid(row=3, column=0, sticky="w", pady=3)
        self.baud_var = tk.StringVar(value="115200")
        ttk.Entry(form, textvariable=self.baud_var, width=10).grid(row=3, column=1, sticky="w", pady=3)

        help_label = ttk.Label(form, text=CONNECTION_HELP, foreground="#555", justify="left")
        help_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 4))

        self.error_var = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.error_var, foreground="red").grid(
            row=5, column=0, columnspan=2, sticky="w"
        )

        btns = ttk.Frame(form)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Connect", command=self._on_connect).grid(row=0, column=1, padx=4)

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.wait_visibility()
        self.focus()

    def _on_connect(self):
        try:
            sysid = int(self.sysid_var.get())
            compid = int(self.compid_var.get())
            baud = int(self.baud_var.get())
        except ValueError:
            self.error_var.set("System ID, component ID and baud must be integers.")
            return

        conn_string = self.conn_var.get().strip()
        if not conn_string:
            self.error_var.set("Connection string is required.")
            return

        try:
            self.conn_mgr.connect(conn_string, sysid, compid, baud)
        except Exception as exc:
            self.error_var.set(f"Connection failed: {exc}")
            return

        self.connected = True
        self.destroy()


def show_connect_dialog(parent, conn_mgr: ConnectionManager) -> bool:
    dialog = ConnectDialog(parent, conn_mgr)
    parent.wait_window(dialog)
    return dialog.connected


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable container for a parameter form or list.

    canvas_height fixes the visible height (e.g. for the Repeating panel, so
    it doesn't grow unbounded with entries); omit it to size to the parent.
    """

    def __init__(self, parent, canvas_height=None, **kwargs):
        super().__init__(parent, **kwargs)
        canvas_kwargs = {"borderwidth": 0, "highlightthickness": 0}
        if canvas_height is not None:
            canvas_kwargs["height"] = canvas_height
        canvas = tk.Canvas(self, **canvas_kwargs)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)

        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)


class SearchablePicker(ttk.Frame):
    """A search box + readonly combobox filtering a list of (id, name) choices.

    Used for both the message picker and the command picker, which behave
    identically: type to filter by id or name substring, dropdown shows
    "id - NAME", and the selection jumps to the first match whenever the
    current one falls outside the filtered results.
    """

    def __init__(self, parent, choices, on_change, item_label="Item:", combo_width=36):
        super().__init__(parent)
        self._choices = choices  # list of (id, name)
        self._on_change = on_change

        ttk.Label(self, text="Search:").pack(side="left")
        self.search_var = tk.StringVar(value="")
        ttk.Entry(self, textvariable=self.search_var, width=16).pack(side="left", padx=(4, 12))
        self.search_var.trace_add("write", lambda *args: self._on_search_changed())

        ttk.Label(self, text=item_label).pack(side="left")
        initial = self._format(choices[0]) if choices else ""
        self.value_var = tk.StringVar(value=initial)
        self.combo = ttk.Combobox(
            self, textvariable=self.value_var, values=self._all_formatted(), state="readonly", width=combo_width
        )
        self.combo.pack(side="left", padx=6)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self._on_change())

    @staticmethod
    def _format(choice):
        item_id, name = choice
        return f"{item_id} - {name}"

    def _all_formatted(self):
        return [self._format(c) for c in self._choices]

    def current_name(self):
        text = self.value_var.get()
        return text.split(" - ", 1)[1] if " - " in text else text

    def current_id(self):
        text = self.value_var.get()
        return int(text.split(" - ", 1)[0])

    def _on_search_changed(self):
        query = self.search_var.get().strip().lower()
        if not query:
            matches = self._choices
        else:
            matches = [c for c in self._choices if query in c[1].lower() or query in str(c[0])]

        formatted = [self._format(c) for c in matches]
        self.combo.configure(values=formatted)
        if not formatted:
            return
        if self.current_name() not in [name for _, name in matches]:
            self.value_var.set(formatted[0])
            self._on_change()


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("MAVProxy Vehicle Spoofer")
        self.root.geometry("760x780")
        self.root.minsize(640, 560)

        self.conn_mgr = ConnectionManager()
        self.conn_mgr.on_status = self._threadsafe_log
        self.conn_mgr.on_disconnect = self._threadsafe_on_disconnect
        self.conn_mgr.on_message = self._threadsafe_on_message
        self.repeat_mgr = RepeatManager(self.conn_mgr)
        self.repeat_status_vars = {}  # entry id -> StringVar, refreshed periodically

        self.field_getters = {}  # field name -> callable returning raw string
        self.current_msg_name = None
        self.cmd_field_getters = {}  # "param1".."param7" -> callable returning raw string
        self.current_cmd_value = None

        self._build_layout()
        self._update_connection_ui()
        self._on_message_selected()
        self._on_command_selected()
        self._rebuild_repeat_rows()
        self._refresh_repeat_status()

    # ---- layout -----------------------------------------------------
    def _build_layout(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")

        self.connect_btn = ttk.Button(top, text="Connect...", command=self._on_connect_clicked)
        self.connect_btn.pack(side="left")
        self.disconnect_btn = ttk.Button(top, text="Disconnect", command=self._on_disconnect_clicked)
        self.disconnect_btn.pack(side="left", padx=(6, 0))

        self.status_var = tk.StringVar(value="Disconnected")
        ttk.Label(top, textvariable=self.status_var).pack(side="left", padx=12)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        msg_tab = ttk.Frame(notebook)
        notebook.add(msg_tab, text="Message")
        self._build_message_tab(msg_tab)

        cmd_tab = ttk.Frame(notebook)
        notebook.add(cmd_tab, text="Command (MAV_CMD)")
        self._build_command_tab(cmd_tab)

        repeat_frame = ttk.Frame(self.root, padding=(8, 0))
        repeat_frame.pack(fill="x", padx=8, pady=(0, 4))
        self.repeat_expanded = False
        self.repeat_count = 0
        self.repeat_toggle_btn = ttk.Button(repeat_frame, command=self._toggle_repeat_panel)
        self.repeat_toggle_btn.pack(fill="x")
        self.repeat_list_frame = ttk.Frame(repeat_frame)  # shown/hidden by the toggle; not packed = collapsed
        self.repeat_list = ScrollableFrame(self.repeat_list_frame, canvas_height=130)
        self.repeat_list.pack(fill="both", expand=True)

        log_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        log_frame.pack(fill="both", expand=False)
        log_header = ttk.Frame(log_frame)
        log_header.pack(fill="x")
        ttk.Label(log_header, text="Log (SENT / RECV):").pack(side="left", anchor="w")
        ttk.Button(log_header, text="Clear Log", command=self._clear_log).pack(side="right")
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _build_message_tab(self, parent):
        message_choices = [(mm.get_message_class(name).id, name) for name in mm.MESSAGE_NAMES]
        self.msg_picker = SearchablePicker(
            parent, message_choices, self._on_message_selected, item_label="Message:"
        )
        self.msg_picker.pack(fill="x", padx=8, pady=8)

        self.form_container = ScrollableFrame(parent, padding=8)
        self.form_container.pack(fill="both", expand=True, padx=8)

        bottom = ttk.Frame(parent, padding=8)
        bottom.pack(fill="x")
        self.send_btn = ttk.Button(bottom, text="Send", command=self._on_send_clicked)
        self.send_btn.pack(side="left")

        self.msg_repeat_rate_var, self.msg_repeat_unit_var, self.msg_repeat_btn = self._build_repeat_controls(
            bottom, self._on_start_message_repeat
        )

    def _build_command_tab(self, parent):
        self.cmd_picker = SearchablePicker(
            parent, mm.get_command_options(), self._on_command_selected, item_label="Command:"
        )
        self.cmd_picker.pack(fill="x", padx=8, pady=8)

        self.cmd_desc_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.cmd_desc_var, foreground="#555", wraplength=640, justify="left").pack(
            fill="x", padx=8
        )

        meta = ttk.Frame(parent, padding=8)
        meta.pack(fill="x")
        ttk.Label(meta, text="Target system:").grid(row=0, column=0, sticky="w")
        self.cmd_target_system_var = tk.StringVar(value="1")
        ttk.Entry(meta, textvariable=self.cmd_target_system_var, width=6).grid(row=0, column=1, sticky="w", padx=(4, 16))
        ttk.Label(meta, text="Target component:").grid(row=0, column=2, sticky="w")
        self.cmd_target_component_var = tk.StringVar(value="1")
        ttk.Entry(meta, textvariable=self.cmd_target_component_var, width=6).grid(row=0, column=3, sticky="w", padx=(4, 16))
        ttk.Label(meta, text="Confirmation:").grid(row=0, column=4, sticky="w")
        self.cmd_confirmation_var = tk.StringVar(value="0")
        ttk.Entry(meta, textvariable=self.cmd_confirmation_var, width=6).grid(row=0, column=5, sticky="w")

        self.cmd_form_container = ScrollableFrame(parent, padding=8)
        self.cmd_form_container.pack(fill="both", expand=True, padx=8)

        bottom = ttk.Frame(parent, padding=8)
        bottom.pack(fill="x")
        self.cmd_send_btn = ttk.Button(bottom, text="Send Command", command=self._on_send_command_clicked)
        self.cmd_send_btn.pack(side="left")

        self.cmd_repeat_rate_var, self.cmd_repeat_unit_var, self.cmd_repeat_btn = self._build_repeat_controls(
            bottom, self._on_start_command_repeat
        )

        incoming = ttk.LabelFrame(parent, text="Incoming commands", padding=8)
        incoming.pack(fill="x", padx=8, pady=(0, 8))
        self.auto_ack_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(incoming, text="Auto-ACK incoming COMMAND_LONG with result:", variable=self.auto_ack_var).pack(
            side="left"
        )
        result_options = [f"{val} - {name}" for val, name in mm.get_enum_options("MAV_RESULT")]
        self.ack_result_var = tk.StringVar(value=result_options[0] if result_options else "0")
        ttk.Combobox(
            incoming, textvariable=self.ack_result_var, values=result_options, width=28, state="readonly"
        ).pack(side="left", padx=(4, 0))

    @staticmethod
    def _build_repeat_controls(parent, start_command):
        ttk.Label(parent, text="Repeat every:").pack(side="left", padx=(16, 4))
        rate_var = tk.StringVar(value="1.0")
        ttk.Entry(parent, textvariable=rate_var, width=8).pack(side="left")
        unit_var = tk.StringVar(value="s")
        ttk.Combobox(parent, textvariable=unit_var, values=["s", "Hz"], width=4, state="readonly").pack(
            side="left", padx=(2, 8)
        )
        btn = ttk.Button(parent, text="Start Repeating", command=start_command)
        btn.pack(side="left")
        return rate_var, unit_var, btn

    @staticmethod
    def _parse_rate(rate_text, unit):
        try:
            value = float(rate_text)
        except ValueError:
            raise ValueError("Rate must be a number.")
        if value <= 0:
            raise ValueError("Rate must be greater than zero.")
        return (1.0 / value) if unit == "Hz" else value

    # ---- connection ---------------------------------------------------
    def _on_connect_clicked(self):
        if show_connect_dialog(self.root, self.conn_mgr):
            self.log(f"Connected ({self.conn_mgr.conn_string}); sending HEARTBEAT every 1s.")
        self._update_connection_ui()

    def _on_disconnect_clicked(self):
        self.conn_mgr.disconnect()
        self._stop_all_repeats("Disconnected.")
        self._update_connection_ui()

    def _threadsafe_on_disconnect(self):
        def handle():
            self._stop_all_repeats("Link dropped; all repeating sends stopped.")
            self._update_connection_ui()
        self.root.after(0, handle)

    def _stop_all_repeats(self, log_message):
        had_entries = bool(self.repeat_mgr.entries)
        self.repeat_mgr.stop_all()
        self._rebuild_repeat_rows()
        self.log(log_message if not had_entries else f"{log_message} (repeats cleared)")

    def _update_connection_ui(self):
        connected = self.conn_mgr.connected
        self.status_var.set("Connected" if connected else "Disconnected")
        self.connect_btn.configure(state="disabled" if connected else "normal")
        self.disconnect_btn.configure(state="normal" if connected else "disabled")
        self.send_btn.configure(state="normal" if connected else "disabled")
        self.cmd_send_btn.configure(state="normal" if connected else "disabled")
        self.msg_repeat_btn.configure(state="normal" if connected else "disabled")
        self.cmd_repeat_btn.configure(state="normal" if connected else "disabled")

    # ---- message form ---------------------------------------------------
    def _on_message_selected(self):
        for child in self.form_container.inner.winfo_children():
            child.destroy()
        self.field_getters = {}

        msg_name = self.msg_picker.current_name()
        self.current_msg_name = msg_name
        msg_cls = mm.get_message_class(msg_name)
        specs = mm.get_field_specs(msg_cls)

        for row, spec in enumerate(specs):
            label_text = spec.name
            if spec.array_len and spec.ctype != "char":
                label_text += f" ({spec.ctype}[{spec.array_len}], comma-separated)"
            elif spec.ctype == "char":
                label_text += f" (text, max {spec.array_len} chars)"
            ttk.Label(self.form_container.inner, text=label_text).grid(
                row=row, column=0, sticky="w", pady=2, padx=(0, 8)
            )

            if spec.enum_name and not mm.is_bitmask_enum(spec.enum_name):
                options = mm.get_enum_options(spec.enum_name)
                values = [f"{val} - {name}" for val, name in options]
                var = tk.StringVar(value=values[0] if values else "0")
                combo = ttk.Combobox(self.form_container.inner, textvariable=var, values=values, width=40, state="readonly")
                combo.grid(row=row, column=1, sticky="w", pady=2)
                self.field_getters[spec.name] = self._make_enum_getter(var)
            else:
                var = tk.StringVar(value=mm.default_value_str(spec))
                entry = ttk.Entry(self.form_container.inner, textvariable=var, width=42)
                entry.grid(row=row, column=1, sticky="w", pady=2)
                self.field_getters[spec.name] = var.get

    @staticmethod
    def _make_enum_getter(var):
        def getter():
            text = var.get()
            return text.split(" - ", 1)[0]
        return getter

    # ---- command form ---------------------------------------------------
    def _on_command_selected(self):
        for child in self.cmd_form_container.inner.winfo_children():
            child.destroy()
        self.cmd_field_getters = {}

        cmd_value = self.cmd_picker.current_id()
        self.current_cmd_value = cmd_value
        self.cmd_desc_var.set(mm.get_command_description(cmd_value))
        param_help = mm.get_command_param_help(cmd_value)

        for i in range(1, 8):
            help_text = param_help.get(i, "")
            label_text = f"param{i}" + (f": {help_text}" if help_text else "")
            ttk.Label(self.cmd_form_container.inner, text=label_text, wraplength=640, justify="left").grid(
                row=i - 1, column=0, sticky="w", pady=2, padx=(0, 8)
            )
            var = tk.StringVar(value="0")
            entry = ttk.Entry(self.cmd_form_container.inner, textvariable=var, width=15)
            entry.grid(row=i - 1, column=1, sticky="w", pady=2)
            self.cmd_field_getters[f"param{i}"] = var.get

    # ---- send ---------------------------------------------------
    def _on_send_clicked(self):
        msg_name = self.current_msg_name
        msg_cls = mm.get_message_class(msg_name)
        specs = mm.get_field_specs(msg_cls)
        raw_values = {name: getter() for name, getter in self.field_getters.items()}

        try:
            msg = mm.build_message(msg_cls, specs, raw_values)
        except Exception as exc:
            messagebox.showerror("Invalid parameters", str(exc))
            return

        try:
            self.conn_mgr.send(msg)
        except Exception as exc:
            messagebox.showerror("Send failed", str(exc))
            return

        if msg_name == "HEARTBEAT":
            # Keep the background auto-heartbeat consistent with the last
            # manually-sent state (e.g. a simulated mode change or arming),
            # otherwise it would be overwritten a second later.
            self.conn_mgr.heartbeat_type = msg.type
            self.conn_mgr.heartbeat_autopilot = msg.autopilot
            self.conn_mgr.heartbeat_base_mode = msg.base_mode
            self.conn_mgr.heartbeat_custom_mode = msg.custom_mode
            self.conn_mgr.heartbeat_system_status = msg.system_status

        self.log(f"Sent {msg_name}: {raw_values}")

    def _on_send_command_clicked(self):
        cmd_value = self.current_cmd_value
        cmd_name = self.cmd_picker.current_name()

        try:
            target_system = int(self.cmd_target_system_var.get())
            target_component = int(self.cmd_target_component_var.get())
            confirmation = int(self.cmd_confirmation_var.get())
            params = [mm.parse_scalar("float", self.cmd_field_getters[f"param{i}"]()) for i in range(1, 8)]
        except ValueError as exc:
            messagebox.showerror("Invalid parameters", str(exc))
            return

        msg = mm.build_command_long(cmd_value, target_system, target_component, confirmation, params)

        try:
            self.conn_mgr.send(msg)
        except Exception as exc:
            messagebox.showerror("Send failed", str(exc))
            return

        self.log(
            f"Sent COMMAND_LONG {cmd_name} ({cmd_value}) to {target_system}.{target_component}: params={params}"
        )

    # ---- repeat: starting a new one ---------------------------------
    def _on_start_message_repeat(self):
        try:
            interval = self._parse_rate(self.msg_repeat_rate_var.get(), self.msg_repeat_unit_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid rate", str(exc))
            return

        msg_name = self.current_msg_name
        msg_cls = mm.get_message_class(msg_name)
        specs = mm.get_field_specs(msg_cls)
        raw_values = {name: getter() for name, getter in self.field_getters.items()}

        try:
            mm.build_message(msg_cls, specs, raw_values)  # validate now, fail fast
        except Exception as exc:
            messagebox.showerror("Invalid parameters", str(exc))
            return

        def builder(cls=msg_cls, sp=specs, rv=dict(raw_values)):
            return mm.build_message(cls, sp, rv)

        label = f"{msg_name} ({msg_cls.id})"
        self.repeat_mgr.add(label, "message", builder, interval)
        self._rebuild_repeat_rows()
        self.log(f"Started repeating {label} every {interval:g}s")

    def _on_start_command_repeat(self):
        try:
            interval = self._parse_rate(self.cmd_repeat_rate_var.get(), self.cmd_repeat_unit_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid rate", str(exc))
            return

        cmd_value = self.current_cmd_value
        cmd_name = self.cmd_picker.current_name()
        try:
            target_system = int(self.cmd_target_system_var.get())
            target_component = int(self.cmd_target_component_var.get())
            confirmation_start = int(self.cmd_confirmation_var.get())
            params = [mm.parse_scalar("float", self.cmd_field_getters[f"param{i}"]()) for i in range(1, 8)]
        except ValueError as exc:
            messagebox.showerror("Invalid parameters", str(exc))
            return

        # Auto-increment confirmation on each repeat, like a real GCS retrying
        # a command, instead of resending byte-identical packets forever.
        confirmation_counter = itertools.count(confirmation_start)

        def builder(cv=cmd_value, ts=target_system, tc=target_component, p=params, counter=confirmation_counter):
            return mm.build_command_long(cv, ts, tc, next(counter) % 256, p)

        label = f"{cmd_name} ({cmd_value})"
        self.repeat_mgr.add(label, "command", builder, interval)
        self._rebuild_repeat_rows()
        self.log(
            f"Started repeating COMMAND_LONG {label} every {interval:g}s "
            f"(confirmation auto-incrementing from {confirmation_start})"
        )

    # ---- repeat: the shared "Repeating" panel ------------------------
    def _toggle_repeat_panel(self):
        self.repeat_expanded = not self.repeat_expanded
        if self.repeat_expanded:
            self.repeat_list_frame.pack(fill="both", expand=True, pady=(4, 0))
        else:
            self.repeat_list_frame.pack_forget()
        self._update_repeat_header()

    def _update_repeat_header(self):
        arrow = "▼" if self.repeat_expanded else "▶"
        text = f"{arrow} Repeating"
        if self.repeat_count:
            text += f" ({self.repeat_count} active)"
        self.repeat_toggle_btn.configure(text=text)

    def _rebuild_repeat_rows(self):
        for child in self.repeat_list.inner.winfo_children():
            child.destroy()
        self.repeat_status_vars = {}

        entries = sorted(self.repeat_mgr.entries.values(), key=lambda e: e.id)
        self.repeat_count = len(entries)
        self._update_repeat_header()
        if not entries:
            ttk.Label(self.repeat_list.inner, text="(none - use \"Start Repeating\" on a tab above)", foreground="#888").grid(
                row=0, column=0, sticky="w"
            )
            return

        for row, entry in enumerate(entries):
            kind_tag = "MSG" if entry.kind == "message" else "CMD"
            ttk.Label(self.repeat_list.inner, text=f"[{kind_tag}] {entry.label}").grid(
                row=row, column=0, sticky="w", padx=(0, 8), pady=2
            )

            rate_var = tk.StringVar(value=f"{entry.interval_seconds:g}")
            unit_var = tk.StringVar(value="s")
            ttk.Entry(self.repeat_list.inner, textvariable=rate_var, width=7).grid(row=row, column=1, sticky="w")
            ttk.Combobox(
                self.repeat_list.inner, textvariable=unit_var, values=["s", "Hz"], width=4, state="readonly"
            ).grid(row=row, column=2, sticky="w", padx=(2, 4))

            def apply_rate(entry_id=entry.id, rate_var=rate_var, unit_var=unit_var):
                try:
                    new_interval = self._parse_rate(rate_var.get(), unit_var.get())
                except ValueError as exc:
                    messagebox.showerror("Invalid rate", str(exc))
                    return
                self.repeat_mgr.set_interval(entry_id, new_interval)

            ttk.Button(self.repeat_list.inner, text="Apply", command=apply_rate).grid(row=row, column=3, padx=4)

            status_var = tk.StringVar(value="")
            ttk.Label(self.repeat_list.inner, textvariable=status_var, foreground="#555").grid(
                row=row, column=4, sticky="w", padx=8
            )
            self.repeat_status_vars[entry.id] = status_var

            def toggle_pause(entry_id=entry.id):
                current = self.repeat_mgr.entries.get(entry_id)
                if current is not None:
                    self.repeat_mgr.set_paused(entry_id, not current.paused)
                    self._rebuild_repeat_rows()

            ttk.Button(
                self.repeat_list.inner, text="Resume" if entry.paused else "Pause", command=toggle_pause
            ).grid(row=row, column=5, padx=4)

            def remove_entry(entry_id=entry.id):
                self.repeat_mgr.remove(entry_id)
                self._rebuild_repeat_rows()

            ttk.Button(self.repeat_list.inner, text="Remove", command=remove_entry).grid(row=row, column=6, padx=4)

    def _refresh_repeat_status(self):
        for entry_id, status_var in self.repeat_status_vars.items():
            entry = self.repeat_mgr.entries.get(entry_id)
            if entry is None:
                continue
            if entry.paused:
                status_var.set(f"paused (sent {entry.send_count}x)")
            elif entry.last_error:
                status_var.set(f"ERROR: {entry.last_error}")
            elif entry.last_sent is not None:
                age = time.time() - entry.last_sent
                status_var.set(f"sent {entry.send_count}x, last {age:.1f}s ago")
            else:
                status_var.set("not sent yet")
        self.root.after(REPEAT_STATUS_REFRESH_MS, self._refresh_repeat_status)

    # ---- incoming traffic ---------------------------------------------
    def _threadsafe_on_message(self, msg):
        self.root.after(0, lambda: self._handle_incoming_message(msg))

    def _handle_incoming_message(self, msg):
        self.log(
            f"RECV {msg.get_type()} from sys{msg.get_srcSystem()}.comp{msg.get_srcComponent()}: "
            f"{mm.format_incoming_message(msg)}"
        )
        if msg.get_type() == "COMMAND_LONG" and self.auto_ack_var.get():
            self._send_auto_ack(msg)

    def _send_auto_ack(self, command_long_msg):
        result_value = int(self.ack_result_var.get().split(" - ", 1)[0])
        ack = mm.build_command_ack(
            command_long_msg.command, result_value, command_long_msg.get_srcSystem(), command_long_msg.get_srcComponent()
        )
        try:
            self.conn_mgr.send(ack)
        except Exception as exc:
            self.log(f"Auto-ACK failed: {exc}")
            return
        cmd_name = mm.get_command_name(command_long_msg.command)
        result_name = self.ack_result_var.get().split(" - ", 1)[1]
        self.log(f"Auto-ACK sent for {cmd_name} ({command_long_msg.command}): {result_name}")

    # ---- logging ---------------------------------------------------
    def log(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _threadsafe_log(self, text):
        self.root.after(0, lambda: self.log(text))
