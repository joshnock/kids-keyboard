"""Letter names, toddler words, and the parent exit chord.

The exit chord is Shift, then Ctrl, then Command, then Space, then Return.
Each key has to still be held when the next one goes down. Once all five are
held, the app waits two seconds before it quits. Letting go cancels it.
"""

HOLD_MS = 2000

EXIT_STEPS = ("shift", "ctrl", "command", "space", "return")

LETTER_NAMES = {
    "a": "ay",
    "b": "bee",
    "c": "see",
    "d": "dee",
    "e": "ee",
    # "ef", not "eff": espeak-ng reads "eff" as a spelled abbreviation.
    "f": "ef",
    "g": "jee",
    "h": "aitch",
    "i": "eye",
    "j": "jay",
    "k": "kay",
    "l": "ell",
    "m": "em",
    "n": "en",
    "o": "oh",
    "p": "pee",
    "q": "cue",
    "r": "are",
    "s": "ess",
    "t": "tee",
    "u": "you",
    "v": "vee",
    "w": "double you",
    "x": "ex",
    "y": "why",
    "z": "zee",
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}


def word_voice_phrases(word):
    """Clips one voice needs when this toddler word is selected.

    That is the word, each of its letter sounds, and the finished line
    ("T, cat"). The last line is included so the final key does not wait
    on a new download.
    """
    phrases = []
    seen = set()

    def add(text):
        if text and text not in seen:
            seen.add(text)
            phrases.append(text)

    add(word)
    last = ""
    for character in word or "":
        last = letter_speech(character)
        add(last)
    if last:
        add(f"{last}, {word}")
    return phrases


def letter_speech(ch):
    """Return the text a voice should say for this character.

    A single letter is the letter itself. The written word "ay" is the
    word aye, which voices say like "eye". The letter Z is "zed" on the
    voice API, so Z is sent as the word "zee".
    """
    if ch.lower() == "z":
        return "zee"
    if ch.isalpha():
        return ch.upper()
    return ch


WORDS = (
    "cat",
    "dog",
    "sun",
    "mom",
    "dad",
    "bus",
    "hat",
    "pig",
    "cup",
    "red",
    "bed",
    "box",
    "fox",
    "hen",
    "jam",
    "kid",
    "log",
    "map",
    "nut",
    "pen",
    "rat",
    "top",
    "cow",
    "bee",
    "egg",
    "ball",
    "duck",
    "fish",
    "frog",
    "milk",
    "book",
    "star",
    "tree",
    "bird",
    "cake",
    "door",
    "hand",
    "home",
    "moon",
    "shoe",
)

WATERMARK = "Shift + Ctrl + Command + Space + Return, hold 2 seconds"


def hold_fraction(elapsed_ms, hold_ms=HOLD_MS):
    """How full the exit ring is. 0 at the start of the hold, 1 at the end."""
    if hold_ms <= 0:
        return 1.0
    if elapsed_ms <= 0:
        return 0.0
    if elapsed_ms >= hold_ms:
        return 1.0
    return elapsed_ms / hold_ms


class ExitChord:
    """Parent exit sequence. Kids mashing other keys do not disturb it."""

    def __init__(self):
        self.progress = 0
        self.held = set()
        self.armed = False

    def press(self, name):
        """Record a chord key going down.

        Returns "ignore", "advance", "reset", or "arm".
        "arm" means every key is held in order and the two-second wait can start.
        """
        if name not in EXIT_STEPS:
            return "ignore"
        if name in self.held:
            return "ignore"
        expected = EXIT_STEPS[self.progress] if self.progress < len(EXIT_STEPS) else None
        if name != expected:
            self._clear()
            if name == EXIT_STEPS[0]:
                self.held.add(name)
                self.progress = 1
                return "advance"
            return "reset"
        self.held.add(name)
        self.progress += 1
        if self.progress == len(EXIT_STEPS):
            self.armed = True
            return "arm"
        return "advance"

    def release(self, name):
        """Record a chord key going up. Returns "cancel" or "ignore"."""
        if name not in self.held:
            return "ignore"
        self._clear()
        return "cancel"

    def reset(self):
        """Drop the sequence. Used when focus is lost."""
        self._clear()

    def _clear(self):
        self.progress = 0
        self.held.clear()
        self.armed = False


class ToddlerLesson:
    """One word at a time. Only the next letter counts."""

    def __init__(self, words, shuffle):
        self._shuffle = shuffle
        self.queue = list(words)
        if not self.queue:
            raise ValueError("need at least one word")
        self._shuffle(self.queue)
        self.word_index = 0
        self.pos = 0
        self.finished = False

    @property
    def word(self):
        return self.queue[self.word_index]

    def type_char(self, ch):
        """Try one typed character.

        A correct letter returns speech text and whether the word is finished.
        Anything else returns None and changes nothing.
        """
        if self.finished or not ch or len(ch) != 1:
            return None
        ch = ch.lower()
        expected = self.word[self.pos]
        if ch != expected or ch not in LETTER_NAMES:
            return None
        speech = letter_speech(ch)
        self.pos += 1
        if self.pos < len(self.word):
            return {"speech": speech, "done": False}
        self.finished = True
        # A period after "A" makes espeak say the article "a", not the letter.
        return {"speech": f"{speech}, {self.word}", "done": True}

    def advance(self):
        """Move to the next word after the finished one has been shown."""
        if not self.finished:
            return
        finished = self.word
        self.finished = False
        self.pos = 0
        self.word_index += 1
        if self.word_index < len(self.queue):
            return
        self.word_index = 0
        self._shuffle(self.queue)
        if len(self.queue) > 1 and self.queue[0] == finished:
            self.queue.append(self.queue.pop(0))
