#!/usr/bin/env python3
"""Overlapping voices: a new letter does not cut off the one already playing."""

import array
import os
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kids_mix import (  # noqa: E402
    FRAME_SECONDS,
    Speaker,
    VoiceMix,
    espeak_pcm,
    mix_frame,
    pace_wait,
    pcm_from_media,
)
from kids_voice import VoiceRoster  # noqa: E402


class MixFrameTests(unittest.TestCase):
    def test_a_second_voice_does_not_duck_the_first(self):
        alone_voice = {"samples": array.array("h", [10000, 10000, 10000]), "pos": 0}
        alone, _alone_done = mix_frame([alone_voice], 3)
        first = {"samples": array.array("h", [10000, 10000, 10000]), "pos": 0}
        second = {"samples": array.array("h", [0, 0]), "pos": 0}
        frame, finished = mix_frame([first, second], 3)
        self.assertEqual(list(frame), list(alone))
        self.assertEqual(finished, [first, second])

    def test_one_voice_keeps_headroom(self):
        frame, _finished = mix_frame(
            [{"samples": array.array("h", [32767]), "pos": 0}],
            1,
        )
        self.assertGreater(frame[0], 10000)
        self.assertLess(frame[0], 22000)

    def test_two_full_clips_stay_in_range(self):
        one = {"samples": array.array("h", [32767]), "pos": 0}
        two = {"samples": array.array("h", [32767]), "pos": 0}
        frame, _finished = mix_frame([one, two], 1)
        self.assertGreater(frame[0], 20000)
        self.assertLess(frame[0], 32767)

    def test_pace_drops_a_stall_instead_of_bursting(self):
        wait, written, started = pace_wait(0.0, None, 10.0)
        self.assertEqual((wait, written, started), (0.0, 0.0, 10.0))
        wait, written, started = pace_wait(0.1, 5.0, 5.0)
        self.assertEqual(written, 0.1)
        self.assertEqual(started, 5.0)
        self.assertAlmostEqual(wait, FRAME_SECONDS)
        wait, written, started = pace_wait(0.1, 5.0, 6.0)
        self.assertEqual((wait, written, started), (0.0, 0.0, 6.0))


class Pipe:
    """A stand-in for pw-cat that records the mixed stream."""

    def __init__(self):
        self.chunks = []
        self.stdin = self
        self.closed = False

    def write(self, data):
        self.chunks.append(data)
        return len(data)

    def flush(self):
        return None

    def close(self):
        self.closed = True

    def poll(self):
        return 0 if self.closed else None

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.closed = True


class VoiceMixTests(unittest.TestCase):
    def test_two_active_clips_share_a_frame(self):
        def render(levels):
            mix = VoiceMix(spawn=Pipe)
            for level in levels:
                mix._voices.append(
                    {"samples": array.array("h", [level] * 100), "pos": 0, "on_done": None}
                )
            frame, _callbacks = mix.render(10)
            shorts = array.array("h")
            shorts.frombytes(frame)
            return list(shorts)

        one = render([10000])
        both = render([10000, 10000])
        quiet = render([10000, 0])
        self.assertEqual(quiet, one)
        self.assertGreater(both[0], one[0])
        self.assertLess(both[0], 32767)
        self.assertEqual(len(both), 10)

    def test_the_stream_finishes_a_clip(self):
        mix = VoiceMix(spawn=Pipe)
        done = threading.Event()
        try:
            self.assertTrue(mix.play(b"\x01\x00" * 200, on_done=done.set))
            self.assertTrue(done.wait(2), "the clip never finished")
        finally:
            mix.close()

    def test_stop_drops_a_clip_without_the_callback(self):
        mix = VoiceMix(spawn=Pipe)
        called = []
        mix._voices.append(
            {
                "samples": array.array("h", [1] * 8000),
                "pos": 0,
                "on_done": lambda: called.append(1),
            }
        )
        mix.stop()
        frame, callbacks = mix.render(100)
        self.assertEqual(callbacks, [])
        self.assertEqual(frame, b"\x00" * 200)
        self.assertEqual(called, [])

    def test_silence_reaches_pipewire(self):
        mix = VoiceMix()
        done = threading.Event()
        try:
            self.assertTrue(mix.play(b"\x00\x00" * 4800, on_done=done.set))
            self.assertTrue(done.wait(2), "PipeWire did not finish the clip")
        finally:
            mix.close()


class SpeakerOverlapTests(unittest.TestCase):
    def test_letters_overlap_and_an_exclusive_phrase_stops_them(self):
        class Library:
            enabled = True

            def cached(self, text, voice=None):
                return text

            def clip(self, text, voice=None):
                return text

        class Mix:
            def __init__(self):
                self.played = []
                self.stops = 0
                self.closed = 0

            def play(self, pcm, on_done=None):
                self.played.append(pcm)
                self.on_done = on_done
                return True

            def stop(self):
                self.stops += 1

            def warm(self):
                return None

            def close(self):
                self.closed += 1

        mix = Mix()
        speaker = Speaker(
            library=Library(),
            mix=mix,
            decode=lambda path: path.encode() + b"\x00",
            speak=lambda text: b"",
            dispatch=lambda fn: fn(),
            synchronous=True,
            roster=VoiceRoster(("eve",), pinned="eve"),
        )
        speaker.say("A")
        speaker.say("B")
        self.assertEqual(mix.stops, 0)
        self.assertEqual(len(mix.played), 2)
        heard = []
        speaker.say("cat", on_done=lambda: heard.append("cat"), exclusive=True)
        self.assertEqual(mix.stops, 1)
        self.assertEqual(mix.played[-1][:3], b"cat")
        mix.on_done()
        self.assertEqual(heard, ["cat"])

    def test_a_cancelled_load_does_not_play(self):
        class Library:
            enabled = True

            def cached(self, _text, voice=None):
                return None

            def clip(self, _text, voice=None):
                speaker.stop()
                return "late"

        class Mix:
            def __init__(self):
                self.played = []

            def play(self, pcm, on_done=None):
                self.played.append(pcm)
                return True

            def stop(self):
                return None

            def warm(self):
                return None

            def close(self):
                return None

        mix = Mix()
        heard = []
        speaker = Speaker(
            library=Library(),
            mix=mix,
            decode=lambda path: b"\x01\x00",
            speak=lambda text: b"",
            dispatch=lambda fn: fn(),
            synchronous=True,
        )
        speaker.say("A", on_done=lambda: heard.append("A"))
        self.assertEqual(mix.played, [])
        self.assertEqual(heard, [])


class PreloadTests(unittest.TestCase):
    def test_saved_clips_play_without_decoding_again(self):
        decoded = []

        class Library:
            enabled = False

            def cached(self, text, voice=None):
                if (voice, text) == ("eve", "A"):
                    return "eve-a.mp3"
                return None

            def clip(self, text, voice=None):
                raise AssertionError("preload downloaded a clip")

        class Mix:
            def __init__(self):
                self.played = []

            def play(self, pcm, on_done=None):
                self.played.append(pcm)
                return True

            def stop(self):
                return None

            def warm(self):
                return None

            def close(self):
                return None

        mix = Mix()
        speaker = Speaker(
            library=Library(),
            mix=mix,
            decode=lambda path: decoded.append(path) or b"\x02\x00",
            speak=lambda text: b"",
            dispatch=lambda fn: fn(),
            synchronous=True,
            roster=VoiceRoster(("eve", "ara")),
        )
        speaker._preload_saved()
        self.assertEqual(decoded, ["eve-a.mp3"])
        decoded.clear()
        speaker.say("A")
        speaker.say("A")
        self.assertEqual(decoded, [])
        self.assertEqual(mix.played, [b"\x02\x00", b"\x02\x00"])

    def test_startup_decodes_letters_and_numbers_only(self):
        order = []

        class Library:
            enabled = False

            def cached(self, text, voice=None):
                if voice == "eve" and text in ("A", "5", "cat"):
                    return text
                return None

            def clip(self, text, voice=None):
                raise AssertionError("preload downloaded a clip")

        class Mix:
            def play(self, pcm, on_done=None):
                return True

            def stop(self):
                return None

            def warm(self):
                return None

            def close(self):
                return None

        speaker = Speaker(
            library=Library(),
            mix=Mix(),
            decode=lambda path: order.append(("decode", path)) or b"\x01\x00",
            speak=lambda text: b"",
            dispatch=lambda fn: order.append("ready") or fn(),
            synchronous=True,
            roster=VoiceRoster(("eve",)),
            on_letters_ready=lambda: order.append("notify"),
        )
        speaker._preload_saved()
        self.assertLess(order.index(("decode", "A")), order.index("notify"))
        self.assertLess(order.index(("decode", "5")), order.index("notify"))
        self.assertNotIn(("decode", "cat"), order)


class WordPrepareTests(unittest.TestCase):
    def _speaker(self, library, decoded):
        class Mix:
            def __init__(self):
                self.played = []

            def play(self, pcm, on_done=None):
                self.played.append(pcm)
                return True

            def stop(self):
                return None

            def warm(self):
                return None

            def close(self):
                return None

        mix = Mix()
        speaker = Speaker(
            library=library,
            mix=mix,
            decode=lambda path: decoded.append(path) or b"\x01\x00",
            speak=lambda text: b"",
            dispatch=lambda fn: fn(),
            synchronous=True,
            roster=VoiceRoster(("eve", "ara", "leo")),
        )
        return speaker, mix

    def test_prepare_decodes_one_voice_and_its_letter_sounds(self):
        from kids_logic import word_voice_phrases

        decoded = []

        class Library:
            enabled = True
            billing = False

            def __init__(self):
                self.files = {
                    ("eve", "cat"): "eve-cat.mp3",
                    ("eve", "dog"): "eve-dog.mp3",
                }
                self.downloaded = []

            def cached(self, text, voice=None):
                return self.files.get((voice, text))

            def clip(self, text, voice=None):
                if voice != "eve" or text == "dog":
                    raise AssertionError(f"downloaded {voice} {text}")
                self.downloaded.append((voice, text))
                path = f"{voice}-{text}.mp3"
                self.files[(voice, text)] = path
                return path

        library = Library()
        events = []
        speaker, mix = self._speaker(library, decoded)
        speaker.random_voice = lambda text, choose=None: "eve"
        letters = word_voice_phrases("cat")

        def clip(text, voice=None):
            if "voices" in events:
                raise AssertionError(f"spoke before downloading {voice} {text}")
            if voice != "eve" or text == "dog":
                raise AssertionError(f"downloaded {voice} {text}")
            library.downloaded.append((voice, text))
            path = f"{voice}-{text}.mp3"
            library.files[(voice, text)] = path
            return path

        library.clip = clip
        speaker.prepare_word(
            "cat",
            letters=letters,
            on_fetch=lambda: events.append("fetch"),
            on_voices=lambda: events.append("voices"),
            on_done=lambda: events.append("done"),
        )
        self.assertEqual(events, ["fetch", "voices", "done"])
        self.assertEqual(speaker.word_voice, "eve")
        self.assertIn("eve-cat.mp3", decoded)
        self.assertNotIn("eve-dog.mp3", decoded)
        self.assertEqual(
            set(library.downloaded),
            {("eve", "C"), ("eve", "A"), ("eve", "T"), ("eve", "T, cat")},
        )
        self.assertNotIn(("ara", "cat"), library.downloaded)
        self.assertNotIn(("leo", "cat"), library.downloaded)
        speaker._pcm_cache[("eve", "cat")] = b"\x01\x00"
        speaker._pcm_cache[("ara", "cat")] = b"\x02\x00"
        speaker.say("cat", voice="ara", exclusive=True)
        self.assertEqual(mix.played, [b"\x02\x00"])

    def test_saved_word_tracks_wait_until_they_are_in_memory(self):
        from kids_logic import word_voice_phrases

        class Library:
            enabled = True
            billing = False

            def __init__(self):
                self.files = {
                    (voice, text): f"{voice}-{text}.mp3"
                    for text in word_voice_phrases("cat")
                    for voice in ("eve",)
                }
                self.downloaded = []

            def cached(self, text, voice=None):
                return self.files.get((voice, text))

            def clip(self, text, voice=None):
                raise AssertionError(f"downloaded {voice} {text}")

        events = []
        speaker, _mix = self._speaker(Library(), [])
        speaker.random_voice = lambda text, choose=None: "eve"
        speaker.prepare_word(
            "cat",
            letters=word_voice_phrases("cat"),
            on_fetch=lambda: events.append("fetch"),
            on_voices=lambda: events.append("voices"),
            on_done=lambda: events.append("done"),
        )
        self.assertEqual(events, ["fetch", "voices", "done"])
        self.assertTrue(speaker.phrases_ready("eve", word_voice_phrases("cat")))

    def test_prepare_letters_fetches_before_it_finishes(self):
        decoded = []

        class Library:
            enabled = True
            billing = False

            def __init__(self):
                self.files = {}
                self.downloaded = []

            def cached(self, text, voice=None):
                return self.files.get((voice, text))

            def clip(self, text, voice=None):
                self.downloaded.append((voice, text))
                path = f"{voice}-{text}.mp3"
                self.files[(voice, text)] = path
                return path

        library = Library()
        speaker, _mix = self._speaker(library, decoded)
        order = []
        generation = speaker._prepare_generation
        speaker.prepare_letters(
            "Leo",
            ("C", "A", "cat"),
            on_fetch=lambda: order.append("fetch"),
            on_done=lambda: order.append("done"),
        )
        self.assertGreater(speaker._prepare_generation, generation)
        self.assertEqual(order, ["fetch", "done"])
        self.assertEqual(speaker.word_voice, "leo")
        self.assertEqual(
            set(library.downloaded),
            {("leo", "C"), ("leo", "A"), ("leo", "cat")},
        )

    def test_switching_voice_drops_the_previous_word(self):
        class Library:
            enabled = False

            def cached(self, text, voice=None):
                return None

            def clip(self, text, voice=None):
                raise AssertionError("prepare downloaded a clip")

        events = []
        speaker, _mix = self._speaker(Library(), [])
        speaker.random_voice = lambda text, choose=None: "eve"
        speaker._pcm_cache[("eve", "cat")] = b"\x01\x00"
        speaker._pcm_cache[("leo", "C")] = b"\x03\x00"
        speaker.prepare_word(
            "cat",
            on_voices=lambda: speaker.prepare_letters(
                "leo",
                ("C",),
                on_done=lambda: events.append("leo"),
            ),
            on_done=lambda: events.append("cat"),
        )
        self.assertEqual(events, ["leo"])

    def test_a_new_word_cancels_the_previous_prepare(self):
        class Library:
            enabled = False

            def cached(self, text, voice=None):
                return None

            def clip(self, text, voice=None):
                raise AssertionError("prepare downloaded a clip")

        events = []
        speaker, _mix = self._speaker(Library(), [])
        speaker.random_voice = lambda text, choose=None: "eve"
        speaker._pcm_cache[("eve", "cat")] = b"\x01\x00"
        speaker._pcm_cache[("eve", "dog")] = b"\x02\x00"
        speaker.prepare_word(
            "cat",
            on_voices=lambda: speaker.prepare_word(
                "dog",
                on_done=lambda: events.append("dog"),
            ),
            on_done=lambda: events.append("cat"),
        )
        self.assertEqual(events, ["dog"])

    def test_a_missing_grok_clip_does_not_play_the_robot_voice(self):
        from kids_logic import word_voice_phrases

        class Library:
            enabled = True
            billing = False

            def __init__(self):
                self.files = {("eve", "cat"): "eve-cat.mp3"}

            def cached(self, text, voice=None):
                return self.files.get((voice, text))

            def clip(self, text, voice=None):
                return None

        spoken = []
        events = []
        speaker, mix = self._speaker(Library(), [])
        speaker.speak = lambda text: spoken.append(text) or b"\x09\x00"
        speaker.random_voice = lambda text, choose=None: "eve"
        speaker.prepare_word(
            "cat",
            letters=word_voice_phrases("cat"),
            on_fetch=lambda: events.append("fetch"),
            on_voices=lambda: events.append("voices"),
            on_done=lambda: events.append("done"),
        )
        self.assertTrue(events)
        self.assertTrue(all(event == "fetch" for event in events))
        self.assertEqual(spoken, [])
        self.assertFalse(speaker.phrases_ready("eve", word_voice_phrases("cat")))
        speaker.say("C", voice="eve", fallback=False)
        self.assertEqual(mix.played, [])
        self.assertEqual(spoken, [])
        self.assertNotIn(("eve", "C"), speaker._pcm_cache)
        speaker.say("C", voice="eve", fallback=True)
        self.assertEqual(spoken, ["C"])
        self.assertEqual(mix.played, [b"\x09\x00"])
        self.assertNotIn(("eve", "C"), speaker._pcm_cache)

    def test_drop_phrases_forgets_the_finished_word_only(self):
        from kids_logic import word_voice_phrases

        class Library:
            def __init__(self):
                self.files = {("eve", "cat"): "eve-cat.mp3"}

            def cached(self, text, voice=None):
                return self.files.get((voice, text))

            def clip(self, text, voice=None):
                raise AssertionError("drop downloaded a clip")

        library = Library()
        speaker, _mix = self._speaker(library, [])
        phrases = word_voice_phrases("cat")
        for phrase in phrases:
            speaker._pcm_cache[("eve", phrase)] = b"\x01\x00"
        speaker._pcm_cache[("eve", "dog")] = b"\x03\x00"
        speaker._pcm_cache[("ara", "cat")] = b"\x04\x00"
        before = dict(library.files)
        speaker.drop_phrases("eve", phrases)
        self.assertFalse(speaker.phrases_ready("eve", phrases))
        self.assertEqual(speaker._pcm_cache[("eve", "dog")], b"\x03\x00")
        self.assertEqual(speaker._pcm_cache[("ara", "cat")], b"\x04\x00")
        self.assertEqual(library.files, before)

    def test_startup_prefetch_skips_toddler_words(self):
        import kids_voice

        class Library:
            enabled = False

            def cached(self, text, voice=None):
                return None

        seen = {}

        def fake_prefetch(library, phrases, voices, workers=4, on_saved=None):
            seen["phrases"] = list(phrases)
            return {"saved": 0, "skipped": 0, "failed": [], "billing": False}

        speaker, _mix = self._speaker(Library(), [])
        original = kids_voice.prefetch
        kids_voice.prefetch = fake_prefetch
        try:
            speaker._prefetch_missing()
        finally:
            kids_voice.prefetch = original
        self.assertIn("A", seen["phrases"])
        self.assertIn("0", seen["phrases"])
        self.assertNotIn("cat", seen["phrases"])
        self.assertEqual(len(seen["phrases"]), 36)

    def test_a_fresh_speaker_loads_ten_voices_unless_one_is_pinned(self):
        import os

        from kids_voice import VOICES

        class Library:
            enabled = False

            def cached(self, text, voice=None):
                return None

        class Mix:
            def play(self, pcm, on_done=None):
                return True

            def stop(self):
                return None

            def warm(self):
                return None

            def close(self):
                return None

        saved = os.environ.pop("KIDS_TYPING_VOICE", None)
        try:
            speaker = Speaker(library=Library(), mix=Mix(), synchronous=True)
            self.assertEqual(len(speaker.roster.voices), 10)
            self.assertTrue(set(speaker.roster.voices).issubset(set(VOICES)))
            os.environ["KIDS_TYPING_VOICE"] = "sal"
            pinned = Speaker(library=Library(), mix=Mix(), synchronous=True)
            self.assertEqual(pinned.roster.voices, ("sal",))
            self.assertEqual(pinned.roster.pinned, "sal")
        finally:
            if saved is None:
                os.environ.pop("KIDS_TYPING_VOICE", None)
            else:
                os.environ["KIDS_TYPING_VOICE"] = saved


class DecodeTests(unittest.TestCase):
    def test_ffmpeg_pcm_is_mono_16_bit(self):
        path = "/tmp/kids-mix-tone.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.05:sample_rate=48000",
                path,
            ],
            check=True,
        )
        pcm = pcm_from_media(path)
        self.assertGreater(len(pcm), 1000)
        self.assertEqual(len(pcm) % 2, 0)

    def test_espeak_pcm_is_not_empty(self):
        pcm = espeak_pcm("A")
        self.assertGreater(len(pcm), 1000)
        self.assertEqual(len(pcm) % 2, 0)


if __name__ == "__main__":
    unittest.main()
