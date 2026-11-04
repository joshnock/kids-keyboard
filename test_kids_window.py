#!/usr/bin/env python3
"""Open the window, exercise both modes, and prove only the chord closes it.

This takes over the screen for a few seconds, then quits on its own.
"""

import json
import os
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from kids_typing import KidsWindow, WATERMARK


class FakeSpeaker:
    def __init__(self):
        self.said = []
        self.voices = []
        self.prepared = []
        self.letters = []
        self.warmed = []
        self.pending = None
        self.exclusive = False

    def say(self, text, on_done=None, exclusive=False, voice=None, fallback=True):
        self.said.append(text)
        self.voices.append(voice)
        self.pending = on_done
        self.exclusive = exclusive

    def prepare_word(self, text, letters=(), on_voices=None, on_done=None, on_fetch=None):
        self.prepared.append(text)
        self.letters = list(letters)
        if on_voices is not None:
            on_voices()
        if on_done is not None:
            on_done()

    def prepare_letters(self, voice, phrases, on_fetch=None, on_done=None):
        self.warmed.append((voice, list(phrases)))
        if on_done is not None:
            on_done()

    def stop(self):
        self.pending = None

    def close(self):
        self.stop()

    def warm(self):
        return None

    def finish(self):
        done = self.pending
        self.pending = None
        if done is not None:
            done()


def shoot(win, name):
    """Save the widget tree. grim hangs on this compositor, so render here."""
    path = f"/tmp/kids-typing-{name}.png"
    width = win.get_width()
    height = win.get_height()
    paintable = Gtk.WidgetPaintable.new(win)
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, width, height)
    node = snap.to_node()
    if node is None or width <= 0 or height <= 0:
        raise RuntimeError(f"empty snapshot {width}x{height}")
    texture = win.get_native().get_renderer().render_texture(node, None)
    if not texture.save_to_png(path):
        raise RuntimeError(f"could not save {path}")
    print(f"SHOT {path} {texture.get_width()}x{texture.get_height()}", flush=True)


def active_window():
    try:
        raw = subprocess.check_output(["hyprctl", "activewindow", "-j"], text=True)
        return json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return {}


def press(win, keyval, keycode):
    win.on_key_pressed(None, keyval, keycode, 0)


def release(win, keyval, keycode):
    win.on_key_released(None, keyval, keycode, 0)


def tap(win, keyval, keycode):
    press(win, keyval, keycode)
    release(win, keyval, keycode)


def letter_key(ch, upper=False):
    if upper:
        return Gdk.KEY_A + (ord(ch) - ord("a"))
    return Gdk.unicode_to_keyval(ord(ch))


def main():
    GLib.set_prgname("kids-typing-test")
    app = Gtk.Application(application_id="kids.typing.test")
    failed = {"v": True}

    def activate(_app):
        win = KidsWindow(app)
        win.speaker = FakeSpeaker()
        win._letters_ready()
        win.set_title("Kids Typing Test")
        win.present()

        def note_close(*_args):
            if win.allow_close:
                failed["v"] = False
                print("CHECKS_OK", flush=True)
            return False

        win.connect("close-request", note_close)

        def bail(message):
            print(message, flush=True)
            traceback.print_exc()
            win.allow_close = True
            app.quit()

        def watchdog():
            print("WATCHDOG_QUIT", flush=True)
            win.allow_close = True
            app.quit()
            return False

        GLib.timeout_add(12000, watchdog)

        def later(delay, fn):
            def wrapper():
                try:
                    fn()
                except Exception:
                    bail("CHECKS_FAILED")
                return False

            GLib.timeout_add(delay, wrapper)

        def phase_home():
            info = active_window()
            print(
                f"WINDOW class={info.get('class')} title={info.get('title')}",
                flush=True,
            )
            surface = win.get_surface()
            caps = surface.get_capabilities() if surface is not None else None
            print(f"CAPS {caps} supported={win.inhibit_supported}", flush=True)
            if not win.shortcuts_inhibited:
                raise RuntimeError("shortcuts were not inhibited")
            if not win.inhibit_supported:
                raise RuntimeError("compositor does not support shortcut inhibit")
            if win.on_close_request(win) is not True:
                raise RuntimeError("close was allowed before the chord")
            if WATERMARK not in win.watermark.get_text():
                raise RuntimeError(win.watermark.get_text())
            if win.back.get_visible():
                raise RuntimeError("Modes button is visible on the home screen")
            shoot(win, "home")
            later(150, phase_infant_logic)

        def phase_infant_logic():
            win.show_infant()
            win.speaker.said.clear()
            press(win, Gdk.KEY_b, 56)
            press(win, Gdk.KEY_b, 56)
            if win.letter.get_text() != "B" or win.letter_name.get_text() != "bee":
                raise RuntimeError(
                    f"infant showed {win.letter.get_text()} / {win.letter_name.get_text()}"
                )
            if win.speaker.said != ["B"]:
                raise RuntimeError(f"speech {win.speaker.said}")
            release(win, Gdk.KEY_b, 56)
            press(win, Gdk.KEY_Shift_L, 50)
            press(win, Gdk.KEY_Left, 113)
            if win.speaker.said != ["B"] or win.chord.progress != 1:
                raise RuntimeError("shift or arrow was treated as a letter")
            release(win, Gdk.KEY_Left, 113)
            release(win, Gdk.KEY_Shift_L, 50)
            tap(win, Gdk.KEY_Escape, 9)
            if win.mode != "home" or win.allow_close:
                raise RuntimeError("escape closed the app or stayed in infant mode")
            win.show_infant()
            tap(win, Gdk.KEY_a, 38)
            later(150, phase_infant_shot)

        def phase_infant_shot():
            shoot(win, "infant")
            phase_toddler_logic()

        def phase_toddler_logic():
            win.show_toddler()
            word = win.lesson.word
            if win.speaker.said != [word] or not win.hearing_word:
                raise RuntimeError(
                    f"word was not announced: {win.speaker.said} lock={win.hearing_word}"
                )
            if win.prompt.get_text() != "Listen":
                raise RuntimeError(win.prompt.get_text())
            tap(win, letter_key(word[0], upper=True), 300)
            if win.lesson.pos != 0 or len(win.speaker.said) != 1:
                raise RuntimeError("a key was accepted while the word was spoken")
            win.speaker.finish()
            if win.hearing_word or win.prompt.get_text() != "Your turn":
                raise RuntimeError("typing did not unlock after the word")
            wrong = "z" if word[0] != "z" else "q"
            before = len(win.speaker.said)
            tap(win, letter_key(wrong), 220)
            if win.lesson.pos != 0 or len(win.speaker.said) != before:
                raise RuntimeError("a wrong toddler key was accepted")
            for index, ch in enumerate(word):
                tap(win, letter_key(ch, upper=(index == 0)), 300 + ord(ch))
            if not win.lesson.finished:
                raise RuntimeError("word did not finish")
            if not win.speaker.said[-1].endswith(word):
                raise RuntimeError(win.speaker.said[-1])
            if win.prompt.get_text() != "Yes!":
                raise RuntimeError(win.prompt.get_text())
            later(150, phase_toddler_shot)

        def phase_toddler_shot():
            shoot(win, "toddler")
            phase_back_home()

        def phase_back_home():
            win.back.emit("clicked")
            if win.mode != "home":
                raise RuntimeError("Modes did not return home")
            later(100, phase_cancel_hold)

        def phase_cancel_hold():
            sequence = (
                (Gdk.KEY_Shift_L, 50),
                (Gdk.KEY_Control_L, 37),
                (Gdk.KEY_Super_L, 133),
                (Gdk.KEY_space, 65),
                (Gdk.KEY_Return, 36),
            )
            win._drop_keys()
            press(win, Gdk.KEY_Control_L, 37)
            if win.chord.armed or win.chord.progress != 0:
                raise RuntimeError("chord armed out of order")
            release(win, Gdk.KEY_Control_L, 37)
            for keyval, keycode in sequence:
                press(win, keyval, keycode)
            if not win.chord.armed or "Keep holding" not in win.watermark.get_text():
                raise RuntimeError("chord did not arm")
            if "Command" not in win.watermark.get_text():
                raise RuntimeError("watermark lost the exit command")
            release(win, Gdk.KEY_space, 65)
            if win.chord.armed or win.allow_close:
                raise RuntimeError("letting go did not cancel the exit")
            if win.mode != "settings":
                raise RuntimeError("releasing the chord did not open settings")
            if win.watermark.get_text() != WATERMARK:
                raise RuntimeError(win.watermark.get_text())
            for keyval, keycode in sequence:
                release(win, keyval, keycode)
            for keyval, keycode in sequence:
                press(win, keyval, keycode)
            if not win.chord.armed:
                raise RuntimeError("second chord did not arm")
            later(2300, phase_exit)

        def phase_exit():
            if not win.allow_close:
                raise RuntimeError("holding the chord for two seconds did not quit")
            failed["v"] = False
            print("CHECKS_OK", flush=True)
            app.quit()

        def wait_for_focus(tries=0):
            if win.is_active():
                later(0, phase_home)
                return False
            if tries == 8:
                subprocess.run(
                    [
                        "hyprctl",
                        "dispatch",
                        'hl.dsp.focus({ window = "class:kids\\\\.typing\\\\.test" })',
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            if tries > 25:
                raise RuntimeError("window never took keyboard focus")
            GLib.timeout_add(100, lambda: wait_for_focus(tries + 1))
            return False

        GLib.timeout_add(200, wait_for_focus)

    app.connect("activate", activate)
    app.run(None)
    if failed["v"]:
        print("CHECKS_FAILED", flush=True)
        raise SystemExit(1)


def main_logic():
    """Check word speech and the key lock without taking over the screen."""
    from kids_typing import Speaker

    app = Gtk.Application(application_id="kids.typing.logic")
    failed = {"v": None}

    def activate(_app):
        # No window is open, so hold the app until the checks finish.
        app.hold()

        def bail(message):
            failed["v"] = message
            print(message, flush=True)
            app.quit()

        speaker = Speaker()
        state = {"heard": False}

        def heard():
            state["heard"] = True

        speaker.say("cat", on_done=heard)

        def after_speech():
            if not state["heard"]:
                return True
            speaker.close()
            win = KidsWindow(app)
            win.speaker = FakeSpeaker()
            try:
                win.show_toddler()
                word = win.lesson.word
                if win.speaker.said != [word] or not win.hearing_word:
                    raise RuntimeError(f"announce {win.speaker.said} lock={win.hearing_word}")
                if win.prompt.get_text() != "Listen":
                    raise RuntimeError(win.prompt.get_text())
                press(win, letter_key(word[0], upper=True), 300)
                press(win, Gdk.KEY_Escape, 9)
                press(win, Gdk.KEY_Shift_L, 50)
                if win.lesson.pos != 0 or win.mode != "toddler" or win.chord.progress != 0:
                    raise RuntimeError("keys were accepted while the word was spoken")
                release(win, letter_key(word[0], upper=True), 300)
                win.speaker.finish()
                if win.hearing_word or win.prompt.get_text() != "Your turn":
                    raise RuntimeError("word speech did not unlock typing")
                press(win, letter_key(word[0], upper=True), 300)
                if win.lesson.pos != 1:
                    raise RuntimeError("the letter did not count after the word")
                release(win, letter_key(word[0], upper=True), 300)
                # A key held across the end of the word must not type on its own.
                win.show_home()
                win.show_toddler()
                word = win.lesson.word
                press(win, letter_key(word[0]), 310)
                win.speaker.finish()
                if win.lesson.pos != 0:
                    raise RuntimeError("a key held during the word typed afterward")
                release(win, letter_key(word[0]), 310)
                press(win, letter_key(word[0]), 310)
                if win.lesson.pos != 1:
                    raise RuntimeError("the same key did not count after release")
            except Exception as exc:
                bail(str(exc))
                return False
            failed["v"] = ""
            print("LOGIC_OK", flush=True)
            app.quit()
            return False

        def timeout():
            if failed["v"] is None:
                bail("timed out waiting for speech")
            return False

        GLib.timeout_add(100, after_speech)
        GLib.timeout_add(5000, timeout)

    app.connect("activate", activate)
    app.run(["kids-typing-logic"])
    if failed["v"] is None:
        print("CHECKS_FAILED", flush=True)
        raise SystemExit(1)
    if failed["v"]:
        raise SystemExit(1)


def main_settings():
    """Open settings with the parent chord, without taking over the screen."""
    import kids_voice

    os.environ["XAI_API_KEY"] = "env-key-for-test"
    kids_voice.read_stored_api_key = lambda schema_name="kids.typing.XaiApiKey": "saved-other"
    saved = {}

    def fake_write(key, schema_name="kids.typing.XaiApiKey"):
        saved["key"] = key

    kids_voice.write_stored_api_key = fake_write
    app = Gtk.Application(application_id="kids.typing.settings")
    failed = {"v": None}

    def activate(_app):
        app.hold()
        try:
            win = KidsWindow(app)
            sequence = (
                (Gdk.KEY_Shift_L, 50),
                (Gdk.KEY_Control_L, 37),
                (Gdk.KEY_Super_L, 133),
                (Gdk.KEY_space, 65),
                (Gdk.KEY_Return, 36),
            )
            for keyval, keycode in sequence:
                press(win, keyval, keycode)
            if not win.chord.armed or "Release for settings" not in win.watermark.get_text():
                raise RuntimeError(win.watermark.get_text())
            if not win.hold_ring.get_visible() or win.hold_ring.fraction != 0:
                raise RuntimeError(
                    f"ring visible={win.hold_ring.get_visible()} fraction={win.hold_ring.fraction}"
                )
            win._ring_started = GLib.get_monotonic_time() - 1000 * 1000
            if not win._tick_ring():
                raise RuntimeError("ring tick stopped")
            if not 0.45 < win.hold_ring.fraction < 0.6:
                raise RuntimeError(f"ring fraction {win.hold_ring.fraction}")
            release(win, Gdk.KEY_Return, 36)
            if win.hold_ring.get_visible():
                raise RuntimeError("hold ring stayed visible after release")
            if win.mode != "settings" or win.allow_close:
                raise RuntimeError(f"mode {win.mode} close {win.allow_close}")
            if win.key_entry.get_text() != "env-key-for-test":
                raise RuntimeError(win.key_entry.get_text())
            note = win.key_note.get_text()
            if "environment variables" not in note or "override" not in note:
                raise RuntimeError(note)
            if "already saved" not in note:
                raise RuntimeError(note)
            if win.on_key_pressed(None, Gdk.KEY_x, 53, 0) is not False:
                raise RuntimeError("a letter was stolen from the key field")
            win.key_entry.set_text("override-key")
            win._save_key()
            if saved.get("key") != "override-key":
                raise RuntimeError(repr(saved))
            if win.speaker.library.api_key != "override-key":
                raise RuntimeError(win.speaker.library.api_key)
            if "keyring" not in win.key_note.get_text():
                raise RuntimeError(win.key_note.get_text())
            press(win, Gdk.KEY_Escape, 9)
            if win.mode != "home" or win.back.get_visible():
                raise RuntimeError("escape did not leave settings")
        except Exception as exc:
            failed["v"] = str(exc)
            print(exc, flush=True)
        else:
            failed["v"] = ""
            print("SETTINGS_OK", flush=True)
        app.quit()

    app.connect("activate", activate)
    app.run(["kids-typing-settings"])
    os.environ.pop("XAI_API_KEY", None)
    if failed["v"] is None:
        print("CHECKS_FAILED", flush=True)
        raise SystemExit(1)
    if failed["v"]:
        raise SystemExit(1)


def main_loading():
    """Check the Grok Voice loading page in a normal window, not fullscreen."""
    app = Gtk.Application(application_id="kids.typing.loading")
    failed = {"v": None}

    def activate(_app):
        app.hold()
        win = KidsWindow(app)
        try:
            if win.mode != "loading" or win.stack.get_visible_child_name() != "loading":
                raise RuntimeError(f"opened on {win.mode}")
            if win.loading_mark.get_text() != "Grok Voice":
                raise RuntimeError(win.loading_mark.get_text())
            if win.loading_message.get_text() != "Loading Grok generated voice files.":
                raise RuntimeError(win.loading_message.get_text())
            if not win.has_css_class("loading") or win.loading_bar is None:
                raise RuntimeError("loading chrome is missing")
            press(win, Gdk.KEY_a, 38)
            press(win, Gdk.KEY_Escape, 9)
            if win.mode != "loading":
                raise RuntimeError("a key left the loading page early")
            win.fullscreen = lambda: None
            win._inhibit_shortcuts = lambda: None
            win._inhibit_idle = lambda: None
            win.speaker.warm = lambda: None
            win.present()

            def finish(tries=0):
                try:
                    if win.get_width() < 100:
                        if tries > 30:
                            raise RuntimeError("loading window did not map")
                        GLib.timeout_add(50, lambda: finish(tries + 1))
                        return False
                    try:
                        shoot(win, "loading")
                    except RuntimeError as exc:
                        if "empty snapshot" not in str(exc) or tries > 30:
                            raise
                        GLib.timeout_add(50, lambda: finish(tries + 1))
                        return False
                    win.show_settings()
                    win._letters_ready()
                    if win.mode != "settings":
                        raise RuntimeError("loading finished over the settings page")
                    win.mode = "loading"
                    win.stack.set_visible_child_name("loading")
                    win.add_css_class("loading")
                    win._letters_ready()
                    if win.mode != "home" or win.stack.get_visible_child_name() != "home":
                        raise RuntimeError("letters ready did not open home")
                    if win.has_css_class("loading") or win._loading_pulse:
                        raise RuntimeError("loading chrome stayed up")
                    if win.back.get_visible():
                        raise RuntimeError("Modes button is visible on the home screen")
                except Exception as exc:
                    failed["v"] = str(exc)
                    print(exc, flush=True)
                else:
                    failed["v"] = ""
                    print("LOADING_OK", flush=True)
                app.quit()
                return False

            GLib.timeout_add(50, finish)
            return
        except Exception as exc:
            failed["v"] = str(exc)
            print(exc, flush=True)
        app.quit()

    app.connect("activate", activate)
    app.run(["kids-typing-loading"])
    if failed["v"] is None:
        print("CHECKS_FAILED", flush=True)
        raise SystemExit(1)
    if failed["v"]:
        raise SystemExit(1)


class HoldSpeaker(FakeSpeaker):
    """Leaves the word's clips loading until the test says they are ready."""

    def __init__(self):
        super().__init__()
        self.on_voices = None
        self.on_done = None
        self.on_fetch = None
        self.on_letters_done = None
        self.on_letters_fetch = None
        self.picks = 0
        self.word_voice = ""

    def prepare_word(self, text, letters=(), on_voices=None, on_done=None, on_fetch=None):
        self.prepared.append(text)
        self.letters = list(letters)
        self.word_voice = "eve"
        self.on_voices = on_voices
        self.on_done = on_done
        self.on_fetch = on_fetch

    def prepare_letters(self, voice, phrases, on_fetch=None, on_done=None):
        self.warmed.append((voice, list(phrases)))
        self.word_voice = voice
        self.on_letters_fetch = on_fetch
        self.on_letters_done = on_done

    def random_voice(self, text, choose=None):
        self.picks += 1
        return "ara" if self.picks == 1 else "leo"


def _letters_disabled(win):
    child = win.letter_row.get_first_child()
    if child is None:
        return False
    while child is not None:
        if not child.has_css_class("disabled"):
            return False
        child = child.get_next_sibling()
    return True


def _check_hint_paint(hint, letter):
    """The next key is coral. The laptop keyboard around it stays faint."""
    import cairo

    from kids_typing import HINT_HEIGHT, HINT_WIDTH, hint_key_boxes, hint_keys

    width, height = HINT_WIDTH, HINT_HEIGHT
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    hint.set_letter(letter)
    hint._draw(None, ctx, width, height)
    boxes = hint_key_boxes(width, height)
    keys = hint_keys(width, height)
    labeled = {legend for legend, *_rest in keys if legend}
    if set("abcdefghijklmnopqrstuvwxyz0123456789") - labeled:
        raise RuntimeError("the hint is missing a letter or number")
    if any(legend in labeled for legend in "-[];',./`"):
        raise RuntimeError("a punctuation key was labeled")
    blanks = [key for key in keys if not key[0]]
    if len(blanks) < 15:
        raise RuntimeError("the hint is missing the blank laptop keys")

    def sample(x, y):
        px = int(x)
        py = int(y)
        stride = surface.get_stride()
        data = surface.get_data()
        index = py * stride + px * 4
        blue, green, red, alpha = data[index : index + 4]
        return red, green, blue, alpha

    def sample_box(box):
        x, y, _w, _h = box
        return sample(x + 8, y + 14)

    target = sample_box(boxes[letter])
    other = "q" if letter != "q" else "m"
    ghost = sample_box(boxes[other])
    number = sample_box(boxes["5"])
    if target[0] < 180 or target[1] > 140 or target[3] < 200:
        raise RuntimeError(f"target key {letter} painted {target}")
    if ghost[3] < 40 or ghost[3] > 70 or (ghost[0] > 180 and ghost[1] < 120):
        raise RuntimeError(f"ghost key {other} painted {ghost}")
    if number[3] > 70:
        raise RuntimeError(f"number key painted {number}")
    _legend, x, y, key_w, key_h = max(blanks, key=lambda key: key[3])
    edge = sample(x + 8, y + 14)
    middle = sample(x + key_w / 2, y + key_h / 2)
    if abs(edge[3] - middle[3]) > 12 or edge[3] > 70:
        raise RuntimeError(f"the space bar drew a symbol {edge} {middle}")


def _orange_pixels(surface):
    count = 0
    stride = surface.get_stride()
    data = surface.get_data()
    for y in range(surface.get_height()):
        row = y * stride
        for x in range(surface.get_width()):
            offset = row + x * 4
            blue, green, red, _alpha = data[offset : offset + 4]
            if red > 180 and green < 140 and blue < 40:
                count += 1
    return count


def main_toddler():
    """Check word loading and Space without taking over the screen."""
    from kids_logic import letter_speech, word_voice_phrases

    app = Gtk.Application(application_id="kids.typing.toddler")
    failed = {"v": None}

    def activate(_app):
        app.hold()
        win = KidsWindow(app)
        win.speaker = HoldSpeaker()
        try:
            win.show_toddler()
            word = win.lesson.word
            phrases = word_voice_phrases(word)
            speaker = win.speaker
            page = win.stack.get_child_by_name("toddler")
            if speaker.prepared != [word] or speaker.said:
                raise RuntimeError(f"prepared {speaker.prepared} said {speaker.said}")
            if speaker.letters != phrases:
                raise RuntimeError(f"word phrases {speaker.letters}")
            if not win.waiting_voice or win.hearing_word:
                raise RuntimeError("the word was spoken before its clips were ready")
            if win.mode != "toddler" or win.stack.get_visible_child_name() != "toddler":
                raise RuntimeError("cached word left the toddler page")
            if hasattr(win, "randomizer"):
                raise RuntimeError("voice bubbles are still on the window")
            if win.prompt.get_parent() is not page or win.letter_row.get_parent() is not page:
                raise RuntimeError("the word page is missing its letters")
            if win.word_bar.get_parent() is not page or win.word_bar.get_visible():
                raise RuntimeError("the progress bar was showing before a download")
            press(win, letter_key(word[0]), 300)
            release(win, letter_key(word[0]), 300)
            if win.lesson.pos != 0 or speaker.said:
                raise RuntimeError("a letter was accepted while clips were loading")
            speaker.on_fetch()
            if win.mode != "toddler" or win.stack.get_visible_child_name() != "toddler":
                raise RuntimeError("word loading left the toddler page")
            if not win.word_bar.get_visible() or win.has_css_class("loading"):
                raise RuntimeError("the word bar did not replace the loading page")
            if not _letters_disabled(win):
                raise RuntimeError("letters stayed active while clips loaded")
            import cairo

            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 280, 10)
            ctx = cairo.Context(surface)
            ctx.set_source_rgb(1, 0.953, 0.875)
            ctx.paint()
            win.word_bar.phase = 0.45
            win.word_bar._draw(None, ctx, 280, 10)
            if _orange_pixels(surface) < 200:
                raise RuntimeError("the progress bar did not paint under the word")
            press(win, letter_key(word[0]), 300)
            release(win, letter_key(word[0]), 300)
            press(win, Gdk.KEY_space, 65)
            release(win, Gdk.KEY_space, 65)
            press(win, Gdk.KEY_Escape, 9)
            release(win, Gdk.KEY_Escape, 9)
            if speaker.said or speaker.picks or win.lesson.pos != 0 or win.mode != "toddler":
                raise RuntimeError("loading accepted a key")
            speaker.on_voices()
            if win.word_bar.get_visible() or _letters_disabled(win):
                raise RuntimeError("the word stayed dim after its clips were ready")
            if speaker.said != [word] or speaker.voices != ["eve"] or not speaker.exclusive:
                raise RuntimeError(f"announced {speaker.said} {speaker.voices}")
            if not win.hearing_word or win.prompt.get_text() != "Listen":
                raise RuntimeError("the word did not lock typing")
            press(win, letter_key(word[0]), 300)
            release(win, letter_key(word[0]), 300)
            if speaker.said != [word] or win.lesson.pos != 0:
                raise RuntimeError("keys were accepted while the word was spoken")
            speaker.finish()
            if win.hearing_word or win.prompt.get_text() != "Your turn":
                raise RuntimeError("typing did not unlock after the word")
            speaker.on_voices()
            if speaker.said != [word]:
                raise RuntimeError("the word was announced twice")
            speaker.on_done()
            if win.preparing_word:
                raise RuntimeError("the word was still preparing")
            press(win, Gdk.KEY_space, 65)
            release(win, Gdk.KEY_space, 65)
            if speaker.said != [word] or speaker.warmed != [("ara", phrases)]:
                raise RuntimeError(f"space spoke early {speaker.said} {speaker.warmed}")
            speaker.on_voices()
            if speaker.said != [word]:
                raise RuntimeError("the old voice spoke after space")
            if win.word_bar.get_visible() or _letters_disabled(win):
                raise RuntimeError("space replay showed the loading bar")
            if speaker.on_letters_fetch is not None:
                speaker.on_letters_fetch()
            if win.mode != "toddler" or win.word_bar.get_visible() or _letters_disabled(win):
                raise RuntimeError("space replay showed the loading bar")
            speaker.on_letters_done()
            if win.word_bar.get_visible() or _letters_disabled(win):
                raise RuntimeError("the reroll left the loading bar up")
            if speaker.voices != ["eve", "ara"] or win.mode != "toddler":
                raise RuntimeError(f"reroll voice {speaker.voices} mode {win.mode}")
            speaker.finish()
            press(win, Gdk.KEY_space, 65)
            release(win, Gdk.KEY_space, 65)
            if speaker.warmed[-1][0] != "leo" or len(speaker.said) != 2:
                raise RuntimeError(f"second space {speaker.said} {speaker.warmed}")
            speaker.on_letters_done()
            if speaker.voices != ["eve", "ara", "leo"]:
                raise RuntimeError(f"second space voice {speaker.voices}")
            speaker.finish()
            for keyval, keycode in (
                (Gdk.KEY_Shift_L, 50),
                (Gdk.KEY_Control_L, 37),
                (Gdk.KEY_Super_L, 133),
                (Gdk.KEY_space, 65),
            ):
                press(win, keyval, keycode)
            if speaker.said != [word, word, word] or win.chord.progress != 4:
                raise RuntimeError(
                    f"chord space spoke {speaker.said} progress {win.chord.progress}"
                )
            for keyval, keycode in (
                (Gdk.KEY_space, 65),
                (Gdk.KEY_Super_L, 133),
                (Gdk.KEY_Control_L, 37),
                (Gdk.KEY_Shift_L, 50),
            ):
                release(win, keyval, keycode)
            if win.mode != "toddler":
                raise RuntimeError("releasing an unfinished chord left toddler mode")
            press(win, letter_key(word[0]), 300)
            if win.lesson.pos != 1:
                raise RuntimeError("the letter did not count after space")
            if speaker.voices[-1] != "leo" or speaker.said[-1] != letter_speech(word[0]):
                raise RuntimeError(f"letter voice {speaker.said} {speaker.voices}")
            _check_hint_paint(win.hint_key, word[win.lesson.pos])
            press(win, Gdk.KEY_space, 65)
            if win.hint_key.get_visible():
                raise RuntimeError("the hint showed before a second")
            if speaker.picks != 3 or len(speaker.warmed) != 3:
                raise RuntimeError(
                    f"space did not say the word {speaker.picks} {len(speaker.warmed)}"
                )
            if speaker.said[-1] != letter_speech(word[0]):
                raise RuntimeError("space said the word before its voice was ready")
            voices_before = list(speaker.voices)
            said_before = list(speaker.said)
            warmed_before = len(speaker.warmed)

            def peek():
                failed["early"] = win.hint_key.get_visible()
                return False

            def after_hold():
                try:
                    if failed.get("early"):
                        raise RuntimeError("the hint showed too soon")
                    if not win.hint_key.get_visible():
                        raise RuntimeError("holding space did not show the hint")
                    if win.hint_key.letter != word[win.lesson.pos]:
                        raise RuntimeError(f"hint letter {win.hint_key.letter}")
                    release(win, Gdk.KEY_space, 65)
                    if win.hint_key.get_visible():
                        raise RuntimeError("the hint stayed after space")
                    if (
                        speaker.voices != voices_before
                        or speaker.said != said_before
                        or len(speaker.warmed) != warmed_before
                        or speaker.picks != 3
                    ):
                        raise RuntimeError("releasing space said the word again")
                except Exception as exc:
                    failed["v"] = str(exc)
                    print(exc, flush=True)
                else:
                    failed["v"] = ""
                    print("TODDLER_OK", flush=True)
                app.quit()
                return False

            GLib.timeout_add(250, peek)
            GLib.timeout_add(1100, after_hold)
            return
        except Exception as exc:
            failed["v"] = str(exc)
            print(exc, flush=True)
        app.quit()

    app.connect("activate", activate)
    app.run(["kids-typing-toddler"])
    if failed["v"] is None:
        print("CHECKS_FAILED", flush=True)
        raise SystemExit(1)
    if failed["v"]:
        raise SystemExit(1)


if __name__ == "__main__":
    if "--logic" in sys.argv:
        main_logic()
    elif "--settings" in sys.argv:
        main_settings()
    elif "--loading" in sys.argv:
        main_loading()
    elif "--toddler" in sys.argv:
        main_toddler()
    else:
        main()
