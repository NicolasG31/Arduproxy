"""Tkinter GUI: connect dialog + main window with a message picker,
a dynamically generated parameter form, and a send log.
"""
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import mav_messages as mm
from mav_connection import ConnectionManager

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
    """A vertically scrollable container for the parameter form."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = ttk.Frame(canvas)

        self.inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("MAVProxy Vehicle Spoofer")
        self.root.geometry("620x560")

        self.conn_mgr = ConnectionManager()
        self.conn_mgr.on_status = self._threadsafe_log
        self.conn_mgr.on_disconnect = self._threadsafe_on_disconnect

        self.field_getters = {}  # field name -> callable returning raw string
        self.current_msg_name = None

        self._build_layout()
        self._update_connection_ui()
        self._on_message_selected()

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

        picker = ttk.Frame(self.root, padding=(8, 0))
        picker.pack(fill="x")
        ttk.Label(picker, text="Search:").pack(side="left")
        self.search_var = tk.StringVar(value="")
        ttk.Entry(picker, textvariable=self.search_var, width=16).pack(side="left", padx=(4, 12))
        self.search_var.trace_add("write", lambda *args: self._on_search_changed())

        ttk.Label(picker, text="Message:").pack(side="left")
        self.msg_var = tk.StringVar(value=self._format_choice(mm.CURATED_MESSAGES[0]))
        self.msg_combo = ttk.Combobox(
            picker, textvariable=self.msg_var, values=self._all_choices(), state="readonly", width=30
        )
        self.msg_combo.pack(side="left", padx=6)
        self.msg_combo.bind("<<ComboboxSelected>>", lambda e: self._on_message_selected())

        self.form_container = ScrollableFrame(self.root, padding=8)
        self.form_container.pack(fill="both", expand=True, padx=8, pady=4)

        bottom = ttk.Frame(self.root, padding=8)
        bottom.pack(fill="x")
        self.send_btn = ttk.Button(bottom, text="Send", command=self._on_send_clicked)
        self.send_btn.pack(side="left")

        log_frame = ttk.Frame(self.root, padding=(8, 0, 8, 8))
        log_frame.pack(fill="both", expand=False)
        ttk.Label(log_frame, text="Log:").pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True)

    # ---- connection ---------------------------------------------------
    def _on_connect_clicked(self):
        if show_connect_dialog(self.root, self.conn_mgr):
            self.log(f"Connected ({self.conn_mgr.conn_string}); sending HEARTBEAT every 1s.")
        self._update_connection_ui()

    def _on_disconnect_clicked(self):
        self.conn_mgr.disconnect()
        self.log("Disconnected.")
        self._update_connection_ui()

    def _threadsafe_on_disconnect(self):
        self.root.after(0, self._update_connection_ui)

    def _update_connection_ui(self):
        connected = self.conn_mgr.connected
        self.status_var.set("Connected" if connected else "Disconnected")
        self.connect_btn.configure(state="disabled" if connected else "normal")
        self.disconnect_btn.configure(state="normal" if connected else "disabled")
        self.send_btn.configure(state="normal" if connected else "disabled")

    # ---- message picker / search ---------------------------------------
    @staticmethod
    def _format_choice(name):
        return f"{mm.get_message_class(name).id} - {name}"

    @staticmethod
    def _parse_choice(choice):
        return choice.split(" - ", 1)[1] if " - " in choice else choice

    @staticmethod
    def _all_choices():
        return [App._format_choice(name) for name in mm.CURATED_MESSAGES]

    def _on_search_changed(self):
        query = self.search_var.get().strip().lower()
        if not query:
            matches = mm.CURATED_MESSAGES
        else:
            matches = [
                name
                for name in mm.CURATED_MESSAGES
                if query in name.lower() or query in str(mm.get_message_class(name).id)
            ]

        choices = [self._format_choice(name) for name in matches]
        self.msg_combo.configure(values=choices)
        if not choices:
            return
        if self._parse_choice(self.msg_var.get()) not in matches:
            self.msg_var.set(choices[0])
            self._on_message_selected()

    # ---- message form ---------------------------------------------------
    def _on_message_selected(self):
        for child in self.form_container.inner.winfo_children():
            child.destroy()
        self.field_getters = {}

        msg_name = self._parse_choice(self.msg_var.get())
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

    # ---- logging ---------------------------------------------------
    def log(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _threadsafe_log(self, text):
        self.root.after(0, lambda: self.log(text))
