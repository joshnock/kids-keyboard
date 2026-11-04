#!/usr/bin/env python3
"""The voice library saves a clip once and plays it from disk after that."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tempfile

from kids_voice import (  # noqa: E402
    VOICES,
    VoiceLibrary,
    VoiceBillingError,
    VoiceRoster,
    bashrc_api_key,
    catalog_phrases,
    SESSION_VOICES,
    prefetch,
    session_voices,
    startup_phrases,
    read_stored_api_key,
    settings_form,
    write_stored_api_key,
)


class SettingsFormTests(unittest.TestCase):
    def test_environment_key_is_shown_with_an_override_message(self):
        text, message = settings_form("env-key", "")
        self.assertEqual(text, "env-key")
        self.assertIn("environment variables", message)
        self.assertIn("override", message)

    def test_a_different_saved_key_is_mentioned(self):
        text, message = settings_form("env-key", "saved-key")
        self.assertEqual(text, "env-key")
        self.assertIn("already saved", message)

    def test_without_an_environment_key_the_saved_key_is_shown(self):
        text, message = settings_form("", "saved-key")
        self.assertEqual(text, "saved-key")
        self.assertNotIn("environment variables", message)

    def test_bashrc_key_is_shown_when_the_process_has_none(self):
        text, message = settings_form("", "", "from-bashrc")
        self.assertEqual(text, "from-bashrc")
        self.assertIn(".bashrc", message)
        self.assertIn("override", message)

    def test_process_environment_wins_over_bashrc(self):
        text, message = settings_form("env-key", "", "from-bashrc")
        self.assertEqual(text, "env-key")
        self.assertIn("environment variables", message)

    def test_bashrc_assignment_does_not_need_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "bashrc")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# XAI_API_KEY=ignored\n")
                handle.write("XAI_API_KEY=first-key\n")
                handle.write('export XAI_API_KEY="second-key"\n')
            self.assertEqual(bashrc_api_key(path), "second-key")

    def test_user_bashrc_contains_a_key(self):
        key = bashrc_api_key()
        self.assertEqual(len(key), 84)

    def test_keyring_round_trip_uses_a_separate_schema(self):
        schema = "kids.typing.XaiApiKey.Test"
        write_stored_api_key("unit-test-not-a-real-key", schema)
        try:
            self.assertEqual(
                read_stored_api_key(schema),
                "unit-test-not-a-real-key",
            )
            write_stored_api_key("", schema)
            self.assertEqual(read_stored_api_key(schema), "")
        finally:
            write_stored_api_key("", schema)


class VoiceLibraryTests(unittest.TestCase):
    def test_missing_key_does_not_download(self):
        calls = []

        def download(text, voice, api_key):
            calls.append(text)
            return b"ID3" + b"x" * 80

        with tempfile.TemporaryDirectory() as directory:
            library = VoiceLibrary(directory, api_key="", download=download)
            self.assertIsNone(library.clip("cat"))
            self.assertEqual(calls, [])

    def test_first_call_saves_and_the_second_reads_the_file(self):
        calls = []

        def download(text, voice, api_key):
            calls.append((text, voice, api_key))
            return b"ID3" + text.encode() + b"x" * 80

        with tempfile.TemporaryDirectory() as directory:
            library = VoiceLibrary(
                directory, api_key="secret", voice="eve", download=download
            )
            first = library.clip("cat")
            second = library.clip("cat")
            self.assertEqual(calls, [("cat", "eve", "secret")])
            self.assertEqual(first, second)
            self.assertTrue(first.is_file())
            self.assertTrue(first.read_bytes().startswith(b"ID3cat"))

    def test_a_failed_download_is_not_saved(self):
        def download(text, voice, api_key):
            return b'{"error":"no"}'

        with tempfile.TemporaryDirectory() as directory:
            library = VoiceLibrary(directory, api_key="secret", download=download)
            self.assertIsNone(library.clip("A"))
            self.assertEqual(list(os.listdir(directory)) if os.listdir(directory) else [], [])

    def test_different_phrases_get_different_files(self):
        def download(text, voice, api_key):
            return b"ID3" + text.encode() + b"y" * 80

        with tempfile.TemporaryDirectory() as directory:
            library = VoiceLibrary(directory, api_key="secret", download=download)
            letter = library.clip("A")
            word = library.clip("cat")
            self.assertNotEqual(letter, word)
            self.assertEqual(library.cached("A"), letter)
            self.assertIsNone(library.cached("dog"))

    def test_each_voice_gets_its_own_file(self):
        calls = []

        def download(text, voice, api_key):
            calls.append((text, voice))
            return b"ID3" + voice.encode() + text.encode() + b"z" * 80

        with tempfile.TemporaryDirectory() as directory:
            library = VoiceLibrary(directory, api_key="secret", download=download)
            eve = library.clip("A", "eve")
            ara = library.clip("A", "ara")
            again = library.clip("A", "eve")
            self.assertNotEqual(eve, ara)
            self.assertEqual(eve, again)
            self.assertEqual(calls, [("A", "eve"), ("A", "ara")])
            self.assertIn("/eve/", str(eve))
            self.assertIn("/ara/", str(ara))


class CatalogTests(unittest.TestCase):
    def test_catalog_is_every_letter_and_word_once(self):
        phrases = catalog_phrases()
        self.assertEqual(len(phrases), len(set(phrases)))
        self.assertIn("A", phrases)
        self.assertIn("zee", phrases)
        self.assertNotIn("Z", phrases)
        self.assertIn("0", phrases)
        self.assertIn("8", phrases)
        self.assertIn("cat", phrases)
        self.assertEqual(len(phrases), 76)

    def test_session_voices_keeps_a_subset_in_roster_order(self):
        voices = ("zagan", "ara", "eve", "leo", "sal")
        picked = session_voices(voices, count=3, sample=lambda names, count: names[:count])
        self.assertEqual(picked, ("zagan", "ara", "eve"))
        self.assertEqual(session_voices(("eve", "ara"), count=10), ("eve", "ara"))
        self.assertEqual(SESSION_VOICES, 10)
        seen = set()
        for _ in range(20):
            choice = session_voices(VOICES, SESSION_VOICES)
            self.assertEqual(len(choice), 10)
            self.assertEqual(len(set(choice)), 10)
            self.assertTrue(set(choice).issubset(set(VOICES)))
            indexes = [VOICES.index(voice) for voice in choice]
            self.assertEqual(indexes, sorted(indexes))
            seen.add(choice)
        self.assertGreater(len(seen), 1)

    def test_startup_phrases_leave_toddler_words_out(self):
        phrases = startup_phrases()
        self.assertEqual(len(phrases), len(set(phrases)))
        self.assertIn("A", phrases)
        self.assertIn("zee", phrases)
        self.assertIn("0", phrases)
        self.assertIn("8", phrases)
        self.assertNotIn("cat", phrases)
        self.assertNotIn("shoe", phrases)
        self.assertEqual(len(phrases), 36)

    def test_roster_changes_voice_and_a_pin_stays(self):
        roster = VoiceRoster(("ara", "eve", "leo"))
        first = roster.pick(lambda choices: choices[0])
        second = roster.pick(lambda choices: choices[0])
        self.assertNotEqual(first, second)
        pinned = VoiceRoster(("ara", "eve"), pinned="leo")
        self.assertEqual(pinned.pick(), "leo")
        self.assertEqual(pinned.pick(), "leo")
        roster = VoiceRoster(("ara", "eve", "leo"))
        self.assertEqual(roster.pick_from(["eve"], lambda choices: choices[0]), "eve")
        self.assertIn("sal", VOICES)
        self.assertEqual(len(VOICES), 28)

    def test_prefetch_fills_every_voice_and_skips_saved_clips(self):
        calls = []

        def download(text, voice, api_key):
            calls.append((voice, text))
            return b"ID3" + voice.encode() + text.encode() + b"q" * 80

        with tempfile.TemporaryDirectory() as directory:
            library = VoiceLibrary(directory, api_key="secret", download=download)
            library.clip("A", "eve")
            calls.clear()
            summary = prefetch(library, ["A", "cat"], ["eve", "ara"], workers=2)
            self.assertEqual(summary["skipped"], 1)
            self.assertEqual(summary["saved"], 3)
            self.assertEqual(summary["failed"], [])
            self.assertEqual(len(calls), 3)
            again = prefetch(library, ["A", "cat"], ["eve", "ara"], workers=2)
            self.assertEqual(again["saved"], 0)
            self.assertEqual(again["skipped"], 4)
            self.assertFalse(again["billing"])

    def test_prefetch_tells_playback_when_a_new_clip_is_saved(self):
        saved = []

        def download(text, voice, api_key):
            return b"ID3" + voice.encode() + text.encode() + b"q" * 80

        with tempfile.TemporaryDirectory() as directory:
            library = VoiceLibrary(directory, api_key="secret", download=download)
            library.clip("A", "eve")
            summary = prefetch(
                library,
                ["A", "cat"],
                ["eve", "ara"],
                workers=2,
                on_saved=lambda voice, text: saved.append((voice, text)),
            )
            self.assertEqual(summary["saved"], 3)
            self.assertEqual(
                set(saved),
                {("eve", "cat"), ("ara", "A"), ("ara", "cat")},
            )

    def test_prefetch_stops_when_the_account_has_no_credits(self):
        calls = []

        def download(text, voice, api_key):
            calls.append((voice, text))
            raise VoiceBillingError

        with tempfile.TemporaryDirectory() as directory:
            library = VoiceLibrary(directory, api_key="secret", download=download)
            summary = prefetch(
                library,
                ["A", "B", "cat", "dog"],
                ["eve", "ara", "leo", "rex"],
                workers=2,
            )
            self.assertTrue(summary["billing"])
            self.assertEqual(summary["saved"], 0)
            self.assertLess(len(calls), 8)
            self.assertEqual(list(library.directory.glob("*")), [])


if __name__ == "__main__":
    unittest.main()
