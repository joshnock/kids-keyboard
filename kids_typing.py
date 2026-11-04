#!/usr/bin/env python3
"""Kids Keyboard: infant key smash, and toddler spelling.

The window stays open until Shift, Ctrl, Command, Space, and Return are
pressed in that order and held together for two seconds. A ring in the
corner fills clockwise during those two seconds. Letting go once that
chord is held opens settings instead.

Letter sounds overlap, so a fast run of keys is still heard. The mix keeps
a little headroom and stays only a few frames ahead of the speakers, so a
new letter does not wait behind a long buffer or pile up after a stall.
Startup loads a random ten voices and stays on a Grok Voice loading page
until those letter and number clips are decoded. Toddler words stay out of
that cache. Picking a word chooses one voice and loads that voice's word
and letter sounds into memory before it speaks. Typing stays locked, with
the letters dim and a progress bar under the word, until every one of
those Grok clips is ready. The robot voice is not used for a toddler word.
When the word is finished, its clips are dropped from memory.
Space in toddler mode picks a new voice and says the displayed word again,
without the progress bar. Holding that Space press for a second shows a
quiet laptop keyboard. The next key is solid. The other keys are fainter,
and only letters and numbers are labeled.
"""

import cairo
import math
import os
import random
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

import kids_voice
from kids_mix import Speaker
from kids_ring import paint_hold_ring

from kids_logic import (
    EXIT_STEPS,
    HOLD_MS,
    LETTER_NAMES,
    hold_fraction,
    letter_speech,
    WATERMARK,
    WORDS,
    ExitChord,
    ToddlerLesson,
    word_voice_phrases,
)

ADVANCE_MS = 1600
HINT_MS = 1000
HINT_WIDTH = 720
HINT_HEIGHT = 248
# A MacBook-shaped keyboard. Each row is 15 key-units wide.
# A one-character letter or digit is drawn. Every other key is only a shape.
HINT_BOARD = (
    (
        ("`", 1), ("1", 1), ("2", 1), ("3", 1), ("4", 1), ("5", 1),
        ("6", 1), ("7", 1), ("8", 1), ("9", 1), ("0", 1), ("-", 1),
        ("=", 1), ("delete", 2),
    ),
    (
        ("tab", 1.5), ("q", 1), ("w", 1), ("e", 1), ("r", 1), ("t", 1),
        ("y", 1), ("u", 1), ("i", 1), ("o", 1), ("p", 1), ("[", 1),
        ("]", 1), ("\\", 1.5),
    ),
    (
        ("caps", 1.75), ("a", 1), ("s", 1), ("d", 1), ("f", 1), ("g", 1),
        ("h", 1), ("j", 1), ("k", 1), ("l", 1), (";", 1), ("'", 1),
        ("return", 2.25),
    ),
    (
        ("shift", 2.25), ("z", 1), ("x", 1), ("c", 1), ("v", 1), ("b", 1),
        ("n", 1), ("m", 1), (",", 1), (".", 1), ("/", 1), ("shift", 2.75),
    ),
    (
        ("fn", 1), ("ctrl", 1), ("opt", 1), ("cmd", 1.25), ("space", 6.5),
        ("cmd", 1.25), ("opt", 1), ("left", 1), ("right", 1),
    ),
)
SLOGANS = (
    "Just your type of fun.",
    "The keys to the alphabet.",
    "Every letter counts.",
    "Mind your Ps and Qs.",
    "All the write keys.",
    "A capital idea.",
    "Caps off to you.",
    "From A to Z, key by key.",
)

CSS = """
window.kids {
  background-color: #fff6ea;
  color: #2c2416;
}

.home-title {
  font-size: 68px;
  font-weight: 800;
  color: #2c2416;
}
.home-sub {
  font-size: 26px;
  font-weight: 700;
  color: #8a7260;
}

button.mode,
button.mode:hover,
button.mode:active,
button.mode:focus {
  background: none;
  background-color: transparent;
  background-image: none;
  border: none;
  box-shadow: none;
  outline: none;
  padding: 0;
}
.mode-key {
  border-radius: 36px;
  min-width: 340px;
  min-height: 230px;
}
.mode-key.infant-mode { background-color: #e5926a; }
.mode-key.toddler-mode { background-color: #7eb6ea; }
.mode-face {
  border-radius: 36px 36px 28px 28px;
  margin-bottom: 16px;
  padding: 36px 32px 20px;
}
.mode-key.infant-mode .mode-face { background-color: #ffd8c2; }
.mode-key.toddler-mode .mode-face { background-color: #d7ebff; }
button.mode label { color: #2c2416; }
button.mode .mode-sub { color: #8a7260; }
.mode-title { font-size: 52px; font-weight: 800; }
.mode-sub { font-size: 22px; font-weight: 700; }

button.back,
button.back:hover,
button.back:active {
  background-image: none;
  background-color: rgba(255, 255, 255, 0.86);
  color: #5c4030;
  font-size: 20px;
  font-weight: 800;
  border-radius: 999px;
  padding: 10px 20px;
  box-shadow: none;
}
button.back:hover { background-color: #ffffff; }
button.back label { color: #2c2416; }

.giant-key {
  background-color: #e7d3c4;
  border-radius: 64px;
  min-width: 440px;
  min-height: 390px;
}
.giant-key .key-face {
  background-color: #fffdf8;
  border-radius: 64px 64px 48px 48px;
  margin-bottom: 24px;
  min-height: 320px;
  min-width: 440px;
}
.giant-key.struck { background-color: #c2410c; }
.giant-key.struck .key-face { background-color: #f05a28; }
.infant-letter {
  font-size: 220px;
  font-weight: 800;
  color: #f05a28;
}
.giant-key.struck .infant-letter { color: #fff6ea; }
.infant-name {
  font-size: 56px;
  font-weight: 800;
  color: #2c2416;
  min-height: 72px;
}
.infant-name.idle { color: #8a7260; }
.toddler-prompt {
  font-size: 32px;
  font-weight: 800;
  color: #8a7260;
  min-height: 48px;
}
.praise {
  font-size: 48px;
  font-weight: 800;
  color: #1f8a4c;
  min-height: 48px;
}
.letter-key {
  border-radius: 32px;
  min-width: 132px;
  min-height: 156px;
}
.letter-key.current { background-color: #c2410c; }
.letter-key.done { background-color: #146338; }
.letter-key.todo { background-color: #e4d3c4; }
.letter-key.disabled,
.letter-key.current.disabled,
.letter-key.done.disabled,
.letter-key.todo.disabled { background-color: #e7d9cc; }
.key-face {
  border-radius: 32px 32px 24px 24px;
  margin-bottom: 14px;
  min-width: 132px;
  min-height: 126px;
}
.letter-key.current .key-face { background-color: #f05a28; }
.letter-key.done .key-face { background-color: #1f8a4c; }
.letter-key.todo .key-face { background-color: #ffffff; }
.letter-key.disabled .key-face,
.letter-key.current.disabled .key-face,
.letter-key.done.disabled .key-face,
.letter-key.todo.disabled .key-face { background-color: #efe4d8; }
.toddler-letter {
  font-size: 84px;
  font-weight: 800;
  background-color: transparent;
}
.letter-key.current .toddler-letter { color: #fff6ea; font-size: 96px; }
.letter-key.done .toddler-letter { color: #fff6ea; }
.letter-key.todo .toddler-letter { color: #c4b2a4; }
.letter-key.disabled .toddler-letter { color: #b7a394; font-size: 84px; }

.settings-title {
  font-size: 64px;
  font-weight: 800;
  color: #2c2416;
}
.settings-label {
  font-size: 28px;
  font-weight: 800;
  color: #8a7260;
}
.settings-note {
  font-size: 22px;
  font-weight: 700;
  color: #2c2416;
}
button.settings-save,
button.settings-save:hover,
button.settings-save:active {
  background-image: none;
  background-color: #1f8a4c;
  font-size: 24px;
  font-weight: 800;
  border-radius: 999px;
  padding: 12px 28px;
  box-shadow: none;
}
button.settings-save label { color: #ffffff; }
button.settings-save:hover { background-color: #3c8460; }
button.settings-save:active { background-color: #24563d; }

.watermark-wrap {
  background-color: rgba(255, 255, 255, 0.8);
  border-radius: 10px;
  padding: 6px 10px;
}
.watermark-wrap label {
  color: rgba(44, 36, 22, 0.55);
  font-size: 14px;
  font-weight: 700;
}
.watermark-wrap.armed { background-color: #ffedd5; }
.watermark-wrap.armed label {
  color: #c2410c;
  font-size: 16px;
}
.hold-ring { background-color: transparent; }
.watermark-wrap.armed .hold-ring { background-color: #ffedd5; }

window.kids.loading { background-color: #050505; }
.loading-page { background-color: #050505; }
.loading-title {
  font-size: 64px;
  font-weight: 800;
  color: #fff6ea;
}
.grok-mark {
  font-size: 16px;
  font-weight: 700;
  color: #8a8a8a;
}
.grok-loading {
  font-size: 15px;
  font-weight: 600;
  color: #6f6f6f;
}
.voice-note { margin-top: 36px; }
.hint-keyboard,
.hint-keyboard:disabled {
  background-color: transparent;
  background-image: none;
}
"""


def _gdk_keys(*names):
    found = []
    for name in names:
        value = getattr(Gdk, name, None)
        if value is not None:
            found.append(value)
    return tuple(found)


SHIFT_KEYS = _gdk_keys("KEY_Shift_L", "KEY_Shift_R")
CTRL_KEYS = _gdk_keys("KEY_Control_L", "KEY_Control_R")
COMMAND_KEYS = _gdk_keys(
    "KEY_Super_L",
    "KEY_Super_R",
    "KEY_Meta_L",
    "KEY_Meta_R",
    "KEY_Hyper_L",
    "KEY_Hyper_R",
)
RETURN_KEYS = _gdk_keys("KEY_Return", "KEY_KP_Enter", "KEY_ISO_Enter")

_css_loaded = False


def load_css():
    global _css_loaded
    if _css_loaded:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    display = Gdk.Display.get_default()
    if display is None:
        raise RuntimeError("no display")
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER,
    )
    _css_loaded = True


def chord_name(keyval):
    """Map a key to an exit-chord step, or return None."""
    if keyval in SHIFT_KEYS:
        return "shift"
    if keyval in CTRL_KEYS:
        return "ctrl"
    if keyval in COMMAND_KEYS:
        return "command"
    if keyval == Gdk.KEY_space:
        return "space"
    if keyval in RETURN_KEYS:
        return "return"
    return None


def typed_char(keyval):
    """Return a-z or 0-9 for a letter or digit key, ignoring Shift."""
    if Gdk.KEY_a <= keyval <= Gdk.KEY_z:
        return chr(keyval)
    if Gdk.KEY_A <= keyval <= Gdk.KEY_Z:
        return chr(keyval - Gdk.KEY_A + Gdk.KEY_a)
    if Gdk.KEY_0 <= keyval <= Gdk.KEY_9:
        return chr(keyval)
    if Gdk.KEY_KP_0 <= keyval <= Gdk.KEY_KP_9:
        return chr(Gdk.KEY_0 + (keyval - Gdk.KEY_KP_0))
    return None


class LoadBar(Gtk.DrawingArea):
    """A short bar that travels while voice clips are prepared."""

    def __init__(self, tone="light"):
        super().__init__()
        self.tone = tone
        self.phase = 0.2
        self.set_size_request(220, 4)
        self.set_halign(Gtk.Align.CENTER)
        self.set_can_target(False)
        self.set_draw_func(self._draw)

    def advance(self):
        self.phase += 0.035
        if self.phase > 1:
            self.phase = 0
        self.queue_draw()

    def _draw(self, _area, ctx, width, height):
        if width <= 0 or height <= 0:
            return
        if self.tone == "warm":
            ctx.set_source_rgba(0.42, 0.33, 0.25, 0.28)
            fill = (0.91, 0.36, 0.02)
        else:
            ctx.set_source_rgb(0.16, 0.16, 0.16)
            fill = (1, 1, 1)
        ctx.rectangle(0, 0, width, height)
        ctx.fill()
        span = max(28, width * 0.34)
        x = (width + span) * self.phase - span
        ctx.rectangle(0, 0, width, height)
        ctx.clip()
        ctx.set_source_rgb(*fill)
        ctx.rectangle(x, 0, span, height)
        ctx.fill()


def _round_rect(ctx, x, y, width, height, radius):
    radius = min(radius, width / 2, height / 2)
    ctx.new_sub_path()
    ctx.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    ctx.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    ctx.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    ctx.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def _hint_legend(symbol):
    """Letters and digits are labeled. Every other laptop key stays blank."""
    if len(symbol) == 1 and symbol.isalnum():
        return symbol.lower()
    return ""


def hint_keys(width, height):
    """Every key on the hint keyboard. A blank legend is a shape with no symbol."""
    pad_x, pad_y, gap = 10, 8, 4
    rows = len(HINT_BOARD)
    unit = (width - 2 * pad_x) / 15
    key_h = (height - 2 * pad_y - (rows - 1) * gap) / rows
    keys = []
    for row_index, row in enumerate(HINT_BOARD):
        y = pad_y + row_index * (key_h + gap)
        x = pad_x
        for symbol, units in row:
            key_w = units * unit - gap
            keys.append((_hint_legend(symbol), x, y, key_w, key_h))
            x += units * unit
    return keys


def hint_key_boxes(width, height):
    """Places of the letter and number keys. Values are x, y, key width, key height."""
    return {
        legend: (x, y, key_w, key_h)
        for legend, x, y, key_w, key_h in hint_keys(width, height)
        if legend
    }


def paint_hint_keyboard(ctx, width, height, target):
    """A faint laptop keyboard. The next key uses the same coral key as the word."""
    target = (target or "").lower()
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    for legend, x, y, key_w, key_h in hint_keys(width, height):
        _paint_hint_key(ctx, x, y, key_w, key_h, legend, bool(legend) and legend == target)


def _paint_hint_key(ctx, x, y, width, height, letter, target):
    radius = min(8, height / 2)
    lip = min(4, height / 5)
    if target:
        _round_rect(ctx, x, y, width, height, radius)
        ctx.set_source_rgb(0.761, 0.255, 0.047)
        ctx.fill()
        _round_rect(ctx, x, y, width, height - lip, radius)
        ctx.set_source_rgb(0.941, 0.353, 0.157)
        ctx.fill()
        ctx.set_source_rgb(1, 0.965, 0.918)
        ctx.set_font_size(max(12, height * 0.42))
    else:
        _round_rect(ctx, x, y, width, height, radius)
        ctx.set_source_rgba(0.55, 0.45, 0.38, 0.10)
        ctx.fill()
        _round_rect(ctx, x, y, width, height - lip, radius)
        ctx.set_source_rgba(1, 0.965, 0.918, 0.12)
        ctx.fill()
        ctx.set_source_rgba(0.45, 0.36, 0.28, 0.18)
        ctx.set_font_size(max(11, height * 0.34))
    if not letter:
        return
    extents = ctx.text_extents(letter)
    face_h = height - lip
    ctx.move_to(
        x + (width - extents.width) / 2 - extents.x_bearing,
        y + (face_h - extents.height) / 2 - extents.y_bearing,
    )
    ctx.show_text(letter)


def paint_app_mark(ctx, size):
    """Coral keycap with a cream K. The same mark as the menu icon."""
    pad = size * 0.08
    lip = size * 0.16
    radius = size * 0.22
    width = size - 2 * pad
    _round_rect(ctx, pad, pad, width, size - 2 * pad, radius)
    ctx.set_source_rgb(0.761, 0.255, 0.047)
    ctx.fill()
    _round_rect(ctx, pad, pad, width, size - 2 * pad - lip, radius)
    ctx.set_source_rgb(0.941, 0.353, 0.157)
    ctx.fill()
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size * 0.52)
    ctx.set_source_rgb(1, 0.965, 0.918)
    text = "K"
    extents = ctx.text_extents(text)
    face_height = size - 2 * pad - lip
    x = (size - extents.width) / 2 - extents.x_bearing
    y = pad + (face_height - extents.height) / 2 - extents.y_bearing
    ctx.move_to(x, y)
    ctx.show_text(text)


class HintKeyboard(Gtk.DrawingArea):
    """Where the next toddler letter sits. Hidden until Space is held."""

    def __init__(self):
        super().__init__()
        self.letter = ""
        self.add_css_class("hint-keyboard")
        self.set_size_request(HINT_WIDTH, HINT_HEIGHT)
        self.set_halign(Gtk.Align.CENTER)
        self.set_visible(False)
        self.set_can_target(False)
        self.set_draw_func(self._draw)

    def set_letter(self, letter):
        self.letter = (letter or "").lower()
        self.queue_draw()

    def _draw(self, _area, ctx, width, height):
        if width <= 0 or height <= 0:
            return
        paint_hint_keyboard(ctx, width, height, self.letter)


class AppMark(Gtk.DrawingArea):
    """The Kids Keyboard keycap, drawn so the loading page does not depend on an icon file."""

    def __init__(self, size=168):
        super().__init__()
        self.set_size_request(size, size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_can_target(False)
        self.set_draw_func(self._draw)

    def _draw(self, _area, ctx, width, height):
        size = min(width, height)
        if size <= 0:
            return
        ctx.save()
        ctx.translate((width - size) / 2, (height - size) / 2)
        paint_app_mark(ctx, size)
        ctx.restore()


class HoldRing(Gtk.DrawingArea):
    """Donut that fills clockwise while the exit chord is held."""

    def __init__(self):
        super().__init__()
        self.fraction = 0.0
        self.add_css_class("hold-ring")
        self.set_content_width(72)
        self.set_content_height(72)
        self.set_size_request(72, 72)
        self.set_can_target(False)
        self.set_visible(False)
        self.set_draw_func(self._draw)

    def set_fraction(self, fraction):
        self.fraction = 0.0 if fraction < 0 else 1.0 if fraction > 1 else fraction
        self.queue_draw()

    def _draw(self, _area, ctx, width, height):
        size = min(width, height)
        ctx.save()
        ctx.translate((width - size) / 2, (height - size) / 2)
        paint_hold_ring(ctx, size, self.fraction)
        ctx.restore()


class KidsWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Kids Keyboard")
        load_css()
        self.add_css_class("kids")
        self.add_css_class("loading")
        self.set_decorated(False)
        self.set_default_size(1280, 800)

        self.mode = "loading"
        self.lesson = None
        self.chord = ExitChord()
        self.speaker = Speaker(on_letters_ready=self._letters_ready)
        self.down_names = {}
        self.allow_close = False
        self.exit_timer = 0
        self.ring_timer = 0
        self._ring_started = 0
        self.advance_timer = 0
        self.hearing_word = False
        self.waiting_voice = False
        self.preparing_word = False
        self._word_loading = False
        self._space_replay = False
        self._word_pulse = 0
        self._word_serial = 0
        self._hint_timer = 0
        self._hint_pending = False
        self._auto_spoken = -1
        self._landed_voice = None
        self.ignored_down = set()
        self.shortcuts_inhibited = False
        self.inhibit_supported = False
        self._inhibit_checked = False
        self.idle_cookie = 0

        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.add_named(self._loading_page(), "loading")
        self.stack.add_named(self._home_page(), "home")
        self.stack.add_named(self._infant_page(), "infant")
        self.stack.add_named(self._toddler_page(), "toddler")
        self.stack.add_named(self._settings_page(), "settings")
        self.stack.set_visible_child_name("loading")

        self.back = Gtk.Button(label="Modes")
        self.back.add_css_class("back")
        self.back.set_halign(Gtk.Align.START)
        self.back.set_valign(Gtk.Align.START)
        self.back.set_margin_start(16)
        self.back.set_margin_top(14)
        self.back.set_visible(False)
        self.back.connect("clicked", lambda *_args: self.show_home())

        self.watermark = Gtk.Label(label=WATERMARK)
        self.watermark.set_justify(Gtk.Justification.RIGHT)
        self.watermark.set_xalign(1)
        self.watermark.set_can_target(False)
        self.hold_ring = HoldRing()
        self.hold_ring.set_valign(Gtk.Align.CENTER)
        self.mark_box = Gtk.Box(spacing=10)
        self.mark_box.add_css_class("watermark-wrap")
        self.mark_box.set_halign(Gtk.Align.END)
        self.mark_box.set_valign(Gtk.Align.END)
        self.mark_box.set_margin_end(16)
        self.mark_box.set_margin_bottom(14)
        self.mark_box.set_can_target(False)
        self.mark_box.append(self.hold_ring)
        self.mark_box.append(self.watermark)

        overlay = Gtk.Overlay()
        overlay.set_child(self.stack)
        overlay.add_overlay(self.back)
        overlay.add_overlay(self.mark_box)
        self.set_child(overlay)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key_pressed)
        keys.connect("key-released", self.on_key_released)
        self.add_controller(keys)

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self.connect("notify::is-active", self._on_active)
        self.connect("close-request", self.on_close_request)

    def _centered(self, spacing):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        box.set_hexpand(True)
        box.set_vexpand(True)
        return box

    def _mode_button(self, title, subtitle, css_class, handler):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.add_css_class("mode-key")
        box.add_css_class(css_class)
        face = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        face.add_css_class("mode-face")
        face.set_hexpand(True)
        face.set_vexpand(True)
        face.set_halign(Gtk.Align.FILL)
        face.set_valign(Gtk.Align.FILL)
        heading = Gtk.Label(label=title)
        heading.add_css_class("mode-title")
        heading.set_halign(Gtk.Align.CENTER)
        heading.set_xalign(0.5)
        detail = Gtk.Label(label=subtitle)
        detail.add_css_class("mode-sub")
        detail.set_halign(Gtk.Align.CENTER)
        detail.set_xalign(0.5)
        face.append(heading)
        face.append(detail)
        box.append(face)
        button = Gtk.Button()
        button.set_child(box)
        button.add_css_class("mode")
        button.add_css_class(css_class)
        button.connect("clicked", handler)
        return button

    def _loading_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.add_css_class("loading-page")
        page.set_hexpand(True)
        page.set_vexpand(True)
        center = self._centered(12)
        name = Gtk.Label(label="Kids Keyboard")
        name.add_css_class("loading-title")
        voice = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        voice.add_css_class("voice-note")
        voice.set_halign(Gtk.Align.CENTER)
        mark = Gtk.Label(label="Grok Voice")
        mark.add_css_class("grok-mark")
        message = Gtk.Label(label="Loading Grok generated voice files.")
        message.add_css_class("grok-loading")
        message.set_justify(Gtk.Justification.CENTER)
        self.loading_bar = LoadBar()
        self.loading_bar.set_size_request(160, 3)
        voice.append(mark)
        voice.append(message)
        voice.append(self.loading_bar)
        center.append(AppMark(200))
        center.append(name)
        center.append(voice)
        self._loading_pulse = GLib.timeout_add(40, self._pulse_loading)
        page.append(center)
        self.loading_mark = mark
        self.loading_message = message
        return page

    def _pulse_loading(self):
        if self.mode != "loading":
            self._loading_pulse = 0
            return False
        self.loading_bar.advance()
        return True

    def _stop_loading_pulse(self):
        if self._loading_pulse:
            GLib.source_remove(self._loading_pulse)
            self._loading_pulse = 0

    def _letters_ready(self):
        """Leave the loading page once the letter and number clips are in memory."""
        self._stop_loading_pulse()
        if self.mode == "loading":
            self.show_home()

    def _show_word_loading(self, serial):
        """Dim the word and show its bar while missing clips are fetched."""
        if serial != self._word_serial or self.mode != "toddler":
            return
        self._word_loading = True
        self._render_toddler()
        self._start_word_bar()

    def _hide_word_loading(self):
        """Clear the bar once this word's clips are ready."""
        if not self._word_loading:
            return
        self._word_loading = False
        self._stop_word_bar()
        if self.mode == "toddler" and self.lesson is not None:
            self._render_toddler()

    def _start_word_bar(self):
        self.word_bar.set_visible(True)
        if not self._word_pulse:
            self._word_pulse = GLib.timeout_add(40, self._pulse_word_bar)

    def _pulse_word_bar(self):
        if not self._word_loading or self.mode != "toddler":
            self._word_pulse = 0
            return False
        self.word_bar.advance()
        return True

    def _stop_word_bar(self):
        if self._word_pulse:
            GLib.source_remove(self._word_pulse)
            self._word_pulse = 0
        if getattr(self, "word_bar", None) is not None:
            self.word_bar.set_visible(False)

    def _clear_loading_chrome(self):
        self.remove_css_class("loading")

    def _home_page(self):
        page = self._centered(22)
        title = Gtk.Label(label="Kids Keyboard")
        title.add_css_class("home-title")
        subtitle = Gtk.Label(label=random.choice(SLOGANS))
        subtitle.add_css_class("home-sub")
        subtitle.set_wrap(True)
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.set_max_width_chars(32)
        buttons = Gtk.Box(spacing=32)
        buttons.set_halign(Gtk.Align.CENTER)
        buttons.append(
            self._mode_button(
                "Infant",
                "Hear the letters",
                "infant-mode",
                lambda *_args: self.show_infant(),
            )
        )
        buttons.append(
            self._mode_button(
                "Toddler",
                "Spell a word",
                "toddler-mode",
                lambda *_args: self.show_toddler(),
            )
        )
        page.append(AppMark(112))
        page.append(title)
        page.append(subtitle)
        page.append(buttons)
        return page

    def _infant_page(self):
        page = self._centered(18)
        self.giant_key = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.giant_key.add_css_class("giant-key")
        self.giant_key.set_halign(Gtk.Align.CENTER)
        face = Gtk.Box()
        face.add_css_class("key-face")
        face.set_hexpand(True)
        face.set_vexpand(True)
        face.set_halign(Gtk.Align.FILL)
        face.set_valign(Gtk.Align.FILL)
        self.letter = Gtk.Label(label="")
        self.letter.add_css_class("infant-letter")
        self.letter.set_hexpand(True)
        self.letter.set_halign(Gtk.Align.FILL)
        self.letter.set_valign(Gtk.Align.CENTER)
        self.letter.set_xalign(0.5)
        face.append(self.letter)
        self.giant_key.append(face)
        self.letter_name = Gtk.Label(label="Press any key")
        self.letter_name.add_css_class("infant-name")
        self.letter_name.add_css_class("idle")
        page.append(self.giant_key)
        page.append(self.letter_name)
        return page

    def _toddler_page(self):
        page = self._centered(18)
        self.prompt = Gtk.Label(label="Your turn")
        self.prompt.add_css_class("toddler-prompt")
        self.letter_row = Gtk.Box(spacing=18)
        self.letter_row.set_halign(Gtk.Align.CENTER)
        self.letter_row.set_valign(Gtk.Align.CENTER)
        self.word_bar = LoadBar(tone="warm")
        self.word_bar.set_size_request(280, 10)
        self.word_bar.set_visible(False)
        self.hint_key = HintKeyboard()
        page.append(self.prompt)
        page.append(self.letter_row)
        page.append(self.word_bar)
        page.append(self.hint_key)
        return page

    def _settings_page(self):
        page = self._centered(18)
        title = Gtk.Label(label="Settings")
        title.add_css_class("settings-title")
        label = Gtk.Label(label="xAI API key")
        label.add_css_class("settings-label")
        self.key_entry = Gtk.PasswordEntry()
        self.key_entry.set_show_peek_icon(True)
        self.key_entry.set_size_request(640, -1)
        self.key_note = Gtk.Label(label="")
        self.key_note.add_css_class("settings-note")
        self.key_note.set_wrap(True)
        self.key_note.set_max_width_chars(42)
        self.key_note.set_justify(Gtk.Justification.CENTER)
        self.key_note.set_visible(False)
        save = Gtk.Button(label="Save key")
        save.add_css_class("settings-save")
        save.set_halign(Gtk.Align.CENTER)
        save.connect("clicked", self._save_key)
        page.append(title)
        page.append(label)
        page.append(self.key_entry)
        page.append(self.key_note)
        page.append(save)
        return page

    def show_home(self):
        self._cancel_advance()
        self._stop_listening()
        self._clear_loading_chrome()
        self.mode = "home"
        self.back.set_label("Modes")
        self.back.set_visible(False)
        self.stack.set_visible_child_name("home")

    def show_infant(self):
        self._cancel_advance()
        self._stop_listening()
        self._clear_loading_chrome()
        self.mode = "infant"
        self.back.set_label("Modes")
        self.back.set_visible(True)
        self.letter.set_text("")
        self.giant_key.remove_css_class("struck")
        self.letter_name.set_text("Press any key")
        self.letter_name.add_css_class("idle")
        self.stack.set_visible_child_name("infant")

    def show_toddler(self):
        self._cancel_advance()
        self._stop_listening()
        self._clear_loading_chrome()
        self.mode = "toddler"
        self.lesson = ToddlerLesson(WORDS, random.shuffle)
        self.back.set_label("Modes")
        self.back.set_visible(True)
        self.stack.set_visible_child_name("toddler")
        self._announce_word()

    def show_settings(self):
        self._cancel_advance()
        self._stop_listening()
        self._clear_loading_chrome()
        self.mode = "settings"
        self.back.set_label("Home")
        self.back.set_visible(True)
        self._load_settings_form()
        self.stack.set_visible_child_name("settings")
        self.key_entry.grab_focus()

    def _load_settings_form(self):
        text, message = kids_voice.settings_form(
            kids_voice.environment_api_key(),
            kids_voice.read_stored_api_key(),
            kids_voice.bashrc_api_key(),
        )
        self.key_entry.set_text(text)
        self.key_note.set_text(message)
        self.key_note.set_visible(bool(message))

    def _save_key(self, *_args):
        key = self.key_entry.get_text().strip()
        try:
            kids_voice.write_stored_api_key(key)
        except Exception as exc:
            self.key_note.set_text(f"Could not save the key. {exc}")
            self.key_note.set_visible(True)
            return
        self.speaker.library.api_key = (
            key or kids_voice.environment_api_key() or kids_voice.bashrc_api_key()
        )
        self.speaker.library.billing = False
        if hasattr(self.speaker.library, "_said_billing"):
            self.speaker.library._said_billing = False
        if key:
            self.key_note.set_text("Key saved in the keyring on this computer.")
        else:
            self.key_note.set_text("Saved key removed.")
        self.key_note.set_visible(True)

    def _stop_listening(self):
        self._cancel_hint()
        self._drop_current_word()
        self._space_replay = False
        self.hearing_word = False
        self.waiting_voice = False
        self.preparing_word = False
        self._word_loading = False
        self._stop_word_bar()
        self.ignored_down.clear()
        self._word_serial += 1
        self.speaker.stop()

    def _drop_current_word(self):
        """Release the current word's decoded clips. The files stay on disk."""
        lesson = self.lesson
        voice = self._landed_voice or getattr(self.speaker, "word_voice", "")
        drop = getattr(self.speaker, "drop_phrases", None)
        if lesson is None or not voice or drop is None:
            return
        drop(voice, word_voice_phrases(lesson.word))

    def _announce_word(self):
        if self.mode not in ("toddler", "loading") or self.lesson is None or self.lesson.finished:
            return
        self._drop_keys()
        self._space_replay = False
        self.ignored_down.clear()
        self.waiting_voice = True
        self.preparing_word = True
        self.hearing_word = False
        self._landed_voice = None
        self._word_serial += 1
        serial = self._word_serial
        if self.mode == "toddler":
            self._render_toddler()
        self.speaker.prepare_word(
            self.lesson.word,
            letters=word_voice_phrases(self.lesson.word),
            on_fetch=lambda: self._show_word_loading(serial),
            on_voices=lambda: self._voices_ready(serial),
            on_done=lambda: self._voices_settled(serial),
        )

    def _voices_ready(self, serial):
        """Say the word once its clips, and its letter clips, are ready."""
        if serial != self._word_serial or self.mode not in ("toddler", "loading"):
            return
        if self.lesson is None or self.lesson.finished or self.hearing_word:
            return
        if self._auto_spoken == serial:
            return
        voice = getattr(self.speaker, "word_voice", None) or None
        if not self._word_audio_ready(voice):
            self._show_word_loading(serial)
            return
        self._hide_word_loading()
        self._speak_word(voice)

    def _voices_settled(self, serial):
        """The word's clips have finished loading."""
        if serial != self._word_serial:
            return
        self.preparing_word = False

    def _speak_random_word(self):
        """Space picks one new voice and says the word. The loading bar stays off."""
        if self.mode != "toddler" or self.lesson is None or self.lesson.finished:
            return
        if self.hearing_word:
            return
        word = self.lesson.word
        picker = getattr(self.speaker, "random_voice", None)
        voice = picker(word) if picker is not None else None
        self._drop_current_word()
        self._word_serial += 1
        serial = self._word_serial
        self._auto_spoken = -1
        self._space_replay = True
        self.waiting_voice = True
        self.preparing_word = True
        self.hearing_word = False
        self._landed_voice = None
        self._render_toddler()
        warmer = getattr(self.speaker, "prepare_letters", None)
        if warmer is None or not voice:
            self.preparing_word = False
            self._speak_word(voice)
            return
        warmer(
            voice,
            word_voice_phrases(word),
            on_done=lambda: self._reroll_ready(serial, voice),
        )

    def _reroll_ready(self, serial, voice):
        """Speak the voice Space picked, after its word and letters are loaded."""
        if serial != self._word_serial or self.mode not in ("toddler", "loading"):
            return
        if self.lesson is None or self.lesson.finished or self.hearing_word:
            return
        if not self._word_audio_ready(voice):
            return
        self.preparing_word = False
        self._speak_word(voice)

    def _word_audio_ready(self, voice):
        """Fake speakers have no clip cache. A real voice must be fully in memory."""
        ready = getattr(self.speaker, "phrases_ready", None)
        if ready is None:
            return True
        if not voice or self.lesson is None:
            return False
        return ready(voice, word_voice_phrases(self.lesson.word))

    def _speak_word(self, voice):
        """Play the current word in one voice. Typed letters use that voice."""
        if self.mode != "toddler" or self.lesson is None or self.lesson.finished:
            return
        if self.hearing_word:
            return
        voice = voice or None
        if not self._word_audio_ready(voice):
            self.waiting_voice = True
            if not self._space_replay:
                self._show_word_loading(self._word_serial)
            return
        self._space_replay = False
        self._landed_voice = voice
        self._auto_spoken = self._word_serial
        self.waiting_voice = False
        self.hearing_word = True
        self._render_toddler()
        self.speaker.say(
            self.lesson.word,
            on_done=self._word_heard,
            exclusive=True,
            voice=voice,
            fallback=False,
        )

    def _word_heard(self):
        self.hearing_word = False
        if self.mode == "toddler" and self.lesson is not None:
            self._render_toddler()

    def _render_toddler(self):
        while (child := self.letter_row.get_first_child()) is not None:
            self.letter_row.remove(child)
        word = self.lesson.word
        for index, ch in enumerate(word):
            if self._word_loading:
                state = "disabled"
            elif self.lesson.finished or index < self.lesson.pos:
                state = "done"
            elif index == self.lesson.pos:
                state = "current"
            else:
                state = "todo"
            self.letter_row.append(self._letter_key(ch, state))
        self._refresh_hint()
        if getattr(self, "word_bar", None) is not None:
            self.word_bar.set_visible(self._word_loading)
        if self.lesson.finished:
            self.prompt.set_text("Yes!")
            self.prompt.remove_css_class("toddler-prompt")
            self.prompt.add_css_class("praise")
        elif self.hearing_word or self.waiting_voice:
            self.prompt.set_text("Listen")
            self.prompt.remove_css_class("praise")
            self.prompt.add_css_class("toddler-prompt")
        else:
            self.prompt.set_text("Your turn")
            self.prompt.remove_css_class("praise")
            self.prompt.add_css_class("toddler-prompt")

    def _letter_key(self, character, state):
        cap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        cap.add_css_class("letter-key")
        cap.add_css_class(state)
        face = Gtk.Box()
        face.add_css_class("key-face")
        face.set_hexpand(True)
        face.set_vexpand(True)
        face.set_halign(Gtk.Align.FILL)
        face.set_valign(Gtk.Align.FILL)
        label = Gtk.Label(label=character)
        label.add_css_class("toddler-letter")
        label.set_hexpand(True)
        label.set_halign(Gtk.Align.FILL)
        label.set_valign(Gtk.Align.CENTER)
        label.set_xalign(0.5)
        face.append(label)
        cap.append(face)
        return cap

    def _infant_type(self, ch):
        self.letter.set_text(ch.upper() if ch.isalpha() else ch)
        self.letter_name.set_text(LETTER_NAMES[ch])
        self.letter_name.remove_css_class("idle")
        self.giant_key.add_css_class("struck")
        self.speaker.say(letter_speech(ch))

    def _toddler_type(self, ch):
        if self.lesson is None:
            return
        result = self.lesson.type_char(ch)
        if result is None:
            return
        self.speaker.say(result["speech"], voice=self._landed_voice, fallback=False)
        self._render_toddler()
        if result["done"]:
            self._cancel_advance()
            self.advance_timer = GLib.timeout_add(ADVANCE_MS, self._advance_word)

    def _advance_word(self):
        self.advance_timer = 0
        if self.mode != "toddler" or self.lesson is None:
            return False
        self._drop_current_word()
        self.lesson.advance()
        self._announce_word()
        return False

    def _cancel_advance(self):
        if self.advance_timer:
            GLib.source_remove(self.advance_timer)
            self.advance_timer = 0

    def on_key_pressed(self, _controller, keyval, keycode, _state):
        if self.mode == "settings" and keyval == Gdk.KEY_Escape:
            self.show_home()
            return True
        token = keycode or keyval
        if self.hearing_word or token in self.ignored_down:
            self.ignored_down.add(token)
            return True
        if token in self.down_names:
            return True
        name = chord_name(keyval)
        self.down_names[token] = name
        if name is not None:
            others = any(
                held == name and held_token != token
                for held_token, held in self.down_names.items()
            )
            if not others:
                result = self.chord.press(name)
                if result == "arm":
                    self.speaker.stop()
                    self._arm_exit()
                elif result == "reset":
                    self._disarm_exit()
                    if (
                        name == "space"
                        and self.mode == "toddler"
                        and not self._word_loading
                    ):
                        self._speak_random_word()
                        self._arm_space_hint()
            return True
        if (
            keyval == Gdk.KEY_Escape
            and self.mode not in ("home", "loading")
            and not self._word_loading
        ):
            self.show_home()
            return True
        if self.mode == "settings":
            return False
        ch = typed_char(keyval)
        if ch is not None and self.mode == "infant":
            self._infant_type(ch)
        elif ch is not None and self.mode == "toddler" and not self.waiting_voice:
            self._toddler_type(ch)
        return True

    def on_key_released(self, _controller, _keyval, keycode, _state):
        token = keycode or _keyval
        if self.hearing_word or token in self.ignored_down:
            self.ignored_down.discard(token)
            name = self.down_names.pop(token, None)
            if name == "space":
                self._cancel_hint()
            return True
        name = self.down_names.pop(token, None)
        if not name:
            return True
        if any(held == name for held in self.down_names.values()):
            return True
        was_armed = self.chord.armed
        if self.chord.release(name) == "cancel":
            self._disarm_exit()
            if was_armed and self.mode != "settings":
                self.show_settings()
        if name == "space":
            self._cancel_hint()
        return True

    def _arm_exit(self):
        if self.exit_timer:
            GLib.source_remove(self.exit_timer)
        if self.ring_timer:
            GLib.source_remove(self.ring_timer)
        self.watermark.set_text(
            "Release for settings. Keep holding to exit\n" + WATERMARK
        )
        self.mark_box.add_css_class("armed")
        self._ring_started = GLib.get_monotonic_time()
        self.hold_ring.set_fraction(0)
        self.hold_ring.set_visible(True)
        self.ring_timer = GLib.timeout_add(32, self._tick_ring)
        self.exit_timer = GLib.timeout_add(HOLD_MS, self._exit_now)

    def _tick_ring(self):
        if not self.exit_timer:
            return False
        elapsed_ms = (GLib.get_monotonic_time() - self._ring_started) / 1000.0
        self.hold_ring.set_fraction(hold_fraction(elapsed_ms))
        return True

    def _disarm_exit(self):
        if self.exit_timer:
            GLib.source_remove(self.exit_timer)
            self.exit_timer = 0
        if self.ring_timer:
            GLib.source_remove(self.ring_timer)
            self.ring_timer = 0
        self.hold_ring.set_fraction(0)
        self.hold_ring.set_visible(False)
        if self.watermark.get_text() != WATERMARK:
            self.watermark.set_text(WATERMARK)
        self.mark_box.remove_css_class("armed")

    def _exit_now(self):
        self.exit_timer = 0
        held = {name for name in self.down_names.values() if name}
        if not self.chord.armed or not set(EXIT_STEPS).issubset(held):
            self.chord.reset()
            self._disarm_exit()
            return False
        self.allow_close = True
        self.speaker.close()
        self.close()
        return False

    def _hint_letter(self):
        lesson = self.lesson
        if (
            self.mode != "toddler"
            or lesson is None
            or lesson.finished
            or lesson.pos < 0
            or lesson.pos >= len(lesson.word)
        ):
            return ""
        letter = lesson.word[lesson.pos].lower()
        if letter not in hint_key_boxes(HINT_WIDTH, HINT_HEIGHT):
            return ""
        return letter

    def _arm_space_hint(self):
        """The word was just requested. A one-second hold shows the next key."""
        self._cancel_hint()
        self._hint_pending = True
        self._hint_timer = GLib.timeout_add(HINT_MS, self._show_hint)

    def _show_hint(self):
        self._hint_timer = 0
        if not self._hint_pending or "space" not in self.down_names.values():
            self._hint_pending = False
            return False
        letter = self._hint_letter()
        if not letter:
            return False
        self.hint_key.set_letter(letter)
        self.hint_key.set_visible(True)
        return False

    def _refresh_hint(self):
        hint = getattr(self, "hint_key", None)
        if hint is None or not hint.get_visible():
            return
        letter = self._hint_letter()
        if not letter:
            hint.set_visible(False)
            return
        hint.set_letter(letter)

    def _cancel_hint(self):
        if self._hint_timer:
            GLib.source_remove(self._hint_timer)
            self._hint_timer = 0
        self._hint_pending = False
        hint = getattr(self, "hint_key", None)
        if hint is not None:
            hint.set_visible(False)

    def _drop_keys(self):
        self._cancel_hint()
        self.down_names.clear()
        self.chord.reset()
        self._disarm_exit()

    def on_close_request(self, _window):
        if not self.allow_close:
            return True
        self.speaker.close()
        self._cancel_advance()
        if self.exit_timer:
            GLib.source_remove(self.exit_timer)
            self.exit_timer = 0
        if self.ring_timer:
            GLib.source_remove(self.ring_timer)
            self.ring_timer = 0
        self._restore_shortcuts()
        app = self.get_application()
        if self.idle_cookie and app is not None:
            app.uninhibit(self.idle_cookie)
            self.idle_cookie = 0
        return False

    def _on_map(self, *_args):
        self.fullscreen()
        self._inhibit_shortcuts()
        self._inhibit_idle()
        self.speaker.warm()
        print("kids-typing: ready", file=sys.stderr, flush=True)

    def _on_unmap(self, *_args):
        self._restore_shortcuts()
        self.speaker.close()

    def _on_active(self, window, _pspec):
        if window.is_active():
            self._inhibit_shortcuts()
        else:
            self._drop_keys()

    def _inhibit_shortcuts(self):
        surface = self.get_surface()
        if surface is None or self.shortcuts_inhibited:
            return
        if not self._inhibit_checked:
            self._inhibit_checked = True
            supported = True
            if hasattr(surface, "get_capabilities"):
                caps = surface.get_capabilities()
                supported = bool(caps & Gdk.ToplevelCapabilities.INHIBIT_SHORTCUTS)
            self.inhibit_supported = supported
            print(
                f"kids-typing: shortcut inhibit supported={supported}",
                file=sys.stderr,
                flush=True,
            )
        try:
            surface.inhibit_system_shortcuts(None)
            self.shortcuts_inhibited = True
            print("kids-typing: system shortcuts inhibited", file=sys.stderr, flush=True)
        except Exception as exc:
            self.shortcuts_inhibited = False
            print(
                f"kids-typing: could not inhibit system shortcuts: {exc}",
                file=sys.stderr,
                flush=True,
            )

    def _restore_shortcuts(self):
        if not self.shortcuts_inhibited:
            return
        surface = self.get_surface()
        self.shortcuts_inhibited = False
        if surface is None:
            return
        try:
            surface.restore_system_shortcuts()
        except Exception as exc:
            print(f"kids-typing: could not restore shortcuts: {exc}", file=sys.stderr)

    def _inhibit_idle(self):
        if self.idle_cookie:
            return
        app = self.get_application()
        if app is None:
            return
        self.idle_cookie = app.inhibit(
            self,
            Gtk.ApplicationInhibitFlags.IDLE,
            "A child is learning to type",
        )
        print(
            f"kids-typing: idle inhibit cookie={self.idle_cookie}",
            file=sys.stderr,
            flush=True,
        )


def on_activate(app):
    win = app.get_active_window()
    if win is None:
        win = KidsWindow(app)
    win.present()


def main():
    GLib.set_prgname("kids-typing")
    GLib.set_application_name("Kids Keyboard")
    app = Gtk.Application(application_id="kids.typing")
    app.connect("activate", on_activate)
    raise SystemExit(app.run(sys.argv))


if __name__ == "__main__":
    main()
