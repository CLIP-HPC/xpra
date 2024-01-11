# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import subprocess
from collections.abc import Callable

from xpra.gtk.window import add_close_accel, add_window_accel
from xpra.gtk.widget import imagebutton, label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.os_util import gi_import
from xpra.util.env import IgnoreWarningsContext
from xpra.exit_codes import exit_str
from xpra.common import NotificationID, noop
from xpra.platform.paths import get_xpra_command
from xpra.log import Logger

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")
Gio = gi_import("Gio")

log = Logger("util")


def exec_command(cmd) -> subprocess.Popen:
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    proc = subprocess.Popen(cmd, env=env)
    log("exec_command(%s)=%s", cmd, proc)
    return proc


def button(tooltip: str, icon_name: str, callback: Callable) -> Gtk.Button:
    btn = Gtk.Button()
    icon = Gio.ThemedIcon(name=icon_name)
    image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
    btn.add(image)
    btn.set_tooltip_text(tooltip)

    def clicked(*_args):
        callback(btn)
    btn.connect("clicked", clicked)
    return btn


class BaseGUIWindow(Gtk.Window):

    def __init__(self,
                 title="Xpra",
                 icon_name="xpra.png",
                 wm_class=("xpra-gui", "Xpra-GUI"),
                 default_size=(640, 300),
                 header_bar=(True, True, False),
                 parent : Gtk.Window | None = None,
                 ):
        self.exit_code = 0
        super().__init__()
        if header_bar:
            self.add_headerbar(*header_bar)
        self.set_title(title)
        self.set_border_width(10)
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.icon_name = icon_name
        icon = get_icon_pixbuf(icon_name)
        if icon:
            self.set_icon(icon)
        if parent:
            self.set_transient_for(parent)
            self.set_modal(True)
            self.do_dismiss = self.hide
        else:
            self.do_dismiss = self.quit
        self.connect("delete_event", self.dismiss)
        add_close_accel(self, self.dismiss)
        add_window_accel(self, 'F1', self.show_about)
        with IgnoreWarningsContext():
            self.set_wmclass(*wm_class)
        self.vbox = Gtk.VBox(homogeneous=False, spacing=10)
        self.set_box_margin()
        self.vbox.set_vexpand(True)
        self.add(self.vbox)
        self.populate()
        self.vbox.show_all()
        self.set_default_size(*default_size)
        self.connect("focus-in-event", self.focus_in)
        self.connect("focus-out-event", self.focus_out)

    def set_box_margin(self, start=40, end=40, top=0, bottom=20) -> None:
        self.vbox.set_margin_start(start)
        self.vbox.set_margin_end(end)
        self.vbox.set_margin_top(top)
        self.vbox.set_margin_bottom(bottom)

    def clear_vbox(self) -> None:
        for x in self.vbox.get_children():
            self.vbox.remove(x)

    def populate_form(self, lines: tuple[str, ...] = (), *buttons) -> None:
        self.clear_vbox()
        self.add_widget(label(self.get_title(), font="sans 20"))
        text = "\n".join(lines)
        lbl = label(text, font="Sans 14")
        lbl.set_line_wrap(True)
        self.add_widget(lbl)
        self.add_buttons(*buttons)

    def add_buttons(self, *buttons) -> list[Gtk.Button]:
        hbox = Gtk.HBox()
        hbox.set_vexpand(False)
        self.add_widget(hbox)
        btnlist = []
        for button_label, callback in buttons:
            btn = Gtk.Button.new_with_label(button_label)
            btn.connect("clicked", callback)
            btnlist.append(btn)
            hbox.pack_start(btn, True, True)
        self.show_all()
        return btnlist

    def dismiss(self, *args) -> None:
        log(f"dismiss{args} calling {self.do_dismiss}")
        self.do_dismiss()

    def add_headerbar(self, about=True, toolbox=True, configure=False) -> None:
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "Xpra"
        if about:
            hb.add(button("About", "help-about", self.show_about))

        def add_gui(text: str, icon_name: str, gui_class):

            def show_gui(*_args):
                w = None

                def hide(*_args):
                    w.hide()

                gui_class.quit = hide
                w = gui_class()
                w.show()

            hb.add(button(text, icon_name, show_gui))

        if toolbox:
            try:
                from xpra.gtk.dialogs.toolbox import ToolboxGUI
            except ImportError:
                pass
            else:
                add_gui("Toolbox", "applications-utilities", ToolboxGUI)
        if configure:
            try:
                from xpra.gtk.configure.main import ConfigureGUI
            except ImportError:
                pass
            else:
                add_gui("Configure", "applications-system", ConfigureGUI)
        hb.show_all()
        self.set_titlebar(hb)

    def ib(self, title="", icon_name="browse.png", tooltip="", callback: Callable = noop, sensitive=True) -> Gtk.Button:
        label_font = "sans 16"
        icon = get_icon_pixbuf(icon_name)
        btn = imagebutton(
            title=title, icon=icon,
            tooltip=tooltip, clicked_callback=callback,
            icon_size=48, label_font=label_font,
        )
        btn.set_sensitive(sensitive)
        self.add_widget(btn)
        return btn

    def add_widget(self, widget) -> None:
        self.vbox.add(widget)

    def focus_in(self, window, event) -> None:
        log("focus_in(%s, %s)", window, event)

    def focus_out(self, window, event) -> None:
        log("focus_out(%s, %s)", window, event)
        self.reset_cursors()

    def app_signal(self, signum: int | signal.Signals) -> None:
        if self.exit_code is None:
            self.exit_code = 128 + int(signum)
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        GLib.idle_add(self.quit)

    def hide(self, *args) -> None:
        log("hide%s", args)
        super().hide()

    def quit(self, *args) -> None:
        log("quit%s", args)
        self.do_quit()

    def do_quit(self) -> None:
        log("do_quit()")
        Gtk.main_quit()

    def show_about(self, *_args) -> None:
        from xpra.gtk.dialogs.about import about
        about(parent=self)

    def get_xpra_command(self, *args) -> list[str]:
        return get_xpra_command()+list(args)

    def button_command(self, btn, *args) -> None:
        cmd = self.get_xpra_command(*args)
        proc = exec_command(cmd)
        if proc.poll() is None:
            self.busy_cursor(btn)
            from xpra.util.child_reaper import getChildReaper
            getChildReaper().add_process(proc, "subcommand", cmd, ignore=True, forget=True,
                                         callback=self.command_ended)

    def command_ended(self, proc) -> None:
        self.reset_cursors()
        log(f"command_ended({proc})")
        if proc.returncode:
            self.may_notify(NotificationID.FAILURE,
                            "Subcommand Failed",
                            "The subprocess terminated abnormally\n\rand returned %s" % exit_str(proc.returncode)
                            )

    def busy_cursor(self, widget) -> None:
        from xpra.gtk.cursors import cursor_types
        watch = cursor_types.get("WATCH")
        if watch:
            display = Gdk.Display.get_default()
            cursor = Gdk.Cursor.new_for_display(display, watch)
            widget.get_window().set_cursor(cursor)
            GLib.timeout_add(5*1000, self.reset_cursors)

    def reset_cursors(self, *_args) -> None:
        for widget in self.vbox.get_children():
            widget.get_window().set_cursor(None)

    def exec_subcommand(self, subcommand, *args) -> None:
        log("exec_subcommand(%s, %s)", subcommand, args)
        cmd = get_xpra_command()
        cmd.append(subcommand)
        cmd += list(args)
        proc = exec_command(cmd)
        if proc.poll() is None:
            self.hide()

            def may_exit():
                if proc.poll() is None:
                    self.quit()
                else:
                    self.show()
            # don't ask me why,
            # but on macos we can get file descriptor errors
            # if we exit immediately after we spawn the `attach` command
            GLib.timeout_add(2000, may_exit)

    def may_notify(self, nid: NotificationID, summary: str, body: str) -> None:
        log.info(summary)
        log.info(body)
        from xpra.platform.gui import get_native_notifier_classes
        nc = get_native_notifier_classes()
        if not nc:
            return
        from xpra.util.types import make_instance
        notifier = make_instance(nc)
        if not notifier:
            return
        from xpra.platform.paths import get_icon_filename
        from xpra.notifications.common import parse_image_path
        icon_filename = get_icon_filename(self.icon_name)
        icon = parse_image_path(icon_filename)
        notifier.show_notify(0, None, nid,
                             "xpra GUI Window", 0, self.icon_name,
                             summary, body, {}, {}, 10, icon)
