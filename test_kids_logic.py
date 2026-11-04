#!/usr/bin/env python3
"""Tests for letter names, toddler progress, and the parent exit chord."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kids_logic import (  # noqa: E402
    HOLD_MS,
    LETTER_NAMES,
    hold_fraction,
    letter_speech,
    word_voice_phrases,
    WATERMARK,
    WORDS,
    ExitChord,
    ToddlerLesson,
)


class LetterTests(unittest.TestCase):
    def test_letter_names(self):
        self.assertEqual(LETTER_NAMES["a"], "ay")
        self.assertEqual(letter_speech("a"), "A")
        self.assertEqual(letter_speech("i"), "I")
        self.assertEqual(letter_speech("8"), "8")
        self.assertEqual(letter_speech("z"), "zee")
        self.assertEqual(letter_speech("Z"), "zee")
        self.assertEqual(LETTER_NAMES["f"], "ef")
        self.assertEqual(LETTER_NAMES["w"], "double you")
        self.assertEqual(LETTER_NAMES["3"], "three")
        self.assertEqual(len(LETTER_NAMES), 36)

    def test_a_word_brings_its_letter_sounds(self):
        self.assertEqual(word_voice_phrases("cat"), ["cat", "C", "A", "T", "T, cat"])
        self.assertEqual(word_voice_phrases("bee"), ["bee", "B", "E", "E, bee"])

    def test_words(self):
        self.assertEqual(len(WORDS), 40)
        self.assertEqual(len(set(WORDS)), 40)
        for word in WORDS:
            self.assertIn(len(word), (3, 4))
            for ch in word:
                self.assertIn(ch, LETTER_NAMES)

    def test_watermark_names_the_chord(self):
        self.assertIn("Shift", WATERMARK)
        self.assertIn("Command", WATERMARK)
        self.assertIn("Return", WATERMARK)
        self.assertEqual(HOLD_MS, 2000)
        self.assertEqual(hold_fraction(0), 0)
        self.assertEqual(hold_fraction(1000), 0.5)
        self.assertEqual(hold_fraction(2000), 1)
        self.assertEqual(hold_fraction(2500), 1)


class ChordTests(unittest.TestCase):
    def test_full_sequence_arms(self):
        chord = ExitChord()
        self.assertEqual(chord.press("shift"), "advance")
        self.assertEqual(chord.press("ctrl"), "advance")
        self.assertEqual(chord.press("command"), "advance")
        self.assertEqual(chord.press("space"), "advance")
        self.assertEqual(chord.press("return"), "arm")
        self.assertTrue(chord.armed)

    def test_repeat_does_not_move_or_disarm(self):
        chord = ExitChord()
        chord.press("shift")
        self.assertEqual(chord.press("shift"), "ignore")
        self.assertEqual(chord.progress, 1)
        for name in ("ctrl", "command", "space", "return"):
            chord.press(name)
        self.assertEqual(chord.press("return"), "ignore")
        self.assertTrue(chord.armed)

    def test_wrong_order_resets(self):
        chord = ExitChord()
        chord.press("shift")
        self.assertEqual(chord.press("space"), "reset")
        self.assertEqual(chord.progress, 0)
        self.assertFalse(chord.armed)

    def test_shift_after_a_mistake_starts_over(self):
        chord = ExitChord()
        chord.press("ctrl")
        self.assertEqual(chord.progress, 0)
        self.assertEqual(chord.press("shift"), "advance")
        self.assertEqual(chord.progress, 1)

    def test_other_keys_do_not_disturb_it(self):
        chord = ExitChord()
        chord.press("shift")
        self.assertEqual(chord.press("a"), "ignore")
        self.assertEqual(chord.progress, 1)
        self.assertEqual(chord.release("a"), "ignore")
        self.assertEqual(chord.progress, 1)

    def test_release_cancels(self):
        chord = ExitChord()
        chord.press("shift")
        chord.press("ctrl")
        self.assertEqual(chord.release("shift"), "cancel")
        self.assertEqual(chord.progress, 0)
        self.assertFalse(chord.armed)
        self.assertEqual(chord.release("shift"), "ignore")

    def test_release_after_arm_cancels(self):
        chord = ExitChord()
        for name in ("shift", "ctrl", "command", "space", "return"):
            chord.press(name)
        self.assertEqual(chord.release("return"), "cancel")
        self.assertFalse(chord.armed)


class ToddlerTests(unittest.TestCase):
    def test_only_the_next_letter_counts(self):
        lesson = ToddlerLesson(["cat"], lambda words: None)
        self.assertEqual(lesson.word, "cat")
        self.assertIsNone(lesson.type_char("x"))
        self.assertIsNone(lesson.type_char("A"))
        self.assertEqual(lesson.pos, 0)
        self.assertEqual(lesson.type_char("C"), {"speech": "C", "done": False})
        self.assertEqual(lesson.type_char("a"), {"speech": "A", "done": False})
        self.assertEqual(lesson.type_char("t"), {"speech": "T, cat", "done": True})
        self.assertIsNone(lesson.type_char("t"))
        self.assertTrue(lesson.finished)

    def test_z_is_spoken_as_zee(self):
        lesson = ToddlerLesson(["zoo"], lambda words: None)
        self.assertEqual(lesson.type_char("z"), {"speech": "zee", "done": False})

    def test_advance_waits_until_the_word_is_finished(self):
        lesson = ToddlerLesson(["cat", "dog"], lambda words: None)
        lesson.advance()
        self.assertEqual(lesson.word, "cat")
        self.assertEqual(lesson.pos, 0)

    def test_cycle_does_not_start_with_the_word_just_finished(self):
        calls = {"n": 0}

        def shuffle(words):
            calls["n"] += 1
            if calls["n"] == 1:
                words[:] = ["cat", "dog"]
            else:
                words[:] = ["dog", "cat"]

        lesson = ToddlerLesson(["dog", "cat"], shuffle)
        self.assertEqual(lesson.word, "cat")
        for ch in "cat":
            lesson.type_char(ch)
        lesson.advance()
        self.assertEqual(lesson.word, "dog")
        for ch in "dog":
            lesson.type_char(ch)
        lesson.advance()
        self.assertEqual(lesson.word, "cat")
        self.assertEqual(lesson.pos, 0)
        self.assertFalse(lesson.finished)

    def test_empty_list_is_rejected(self):
        with self.assertRaises(ValueError):
            ToddlerLesson([], lambda words: None)


if __name__ == "__main__":
    unittest.main()
