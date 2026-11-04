"""Cached xAI voices for the kids typing phrases.

The first time a phrase is needed, it is downloaded and stored under
~/.local/share/kids-typing/voices/. Later plays use that file. A missing
key or a failed call returns nothing so the app can use espeak-ng.
"""

import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_URL = "https://api.x.ai/v1/tts"
DEFAULT_VOICE = "eve"


class VoiceBillingError(Exception):
    """The API account has no credits left for speech."""
# Built-in voices from GET /v1/tts/voices. Playback rotates through these.
VOICES = (
    "altair",
    "ara",
    "atlas",
    "aurora",
    "carina",
    "castor",
    "celeste",
    "cosmo",
    "eve",
    "helios",
    "helix",
    "iris",
    "kepler",
    "leo",
    "liora",
    "lumen",
    "luna",
    "lux",
    "naksh",
    "orion",
    "perseus",
    "rex",
    "rigel",
    "sal",
    "sirius",
    "ursa",
    "zagan",
    "zenith",
)


SCHEMA_NAME = "kids.typing.XaiApiKey"
ENV_MESSAGE = (
    "This key was loaded from environment variables. "
    "Save it, or type a new key to override it."
)
BASHRC_MESSAGE = (
    "This key was loaded from .bashrc. "
    "Save it, or type a new key to override it."
)
STORED_MESSAGE = "Using the key saved on this computer."


def environment_api_key():
    return os.environ.get("XAI_API_KEY", "").strip()


def bashrc_api_key(path=None):
    """Read XAI_API_KEY from .bashrc.

    Graphical apps are not started by bash, so a key written in .bashrc
    is not in the process environment. The assignment does not need export.
    """
    path = Path.home() / ".bashrc" if path is None else Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    found = ""
    for line in lines:
        value = _assignment_value(line, "XAI_API_KEY")
        if value is not None:
            found = value.strip()
    return found


def _assignment_value(line, name):
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    prefix = name + "="
    if not stripped.startswith(prefix):
        return None
    raw = stripped[len(prefix) :].strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw.split()[0] if raw else ""


def settings_form(environment, stored, shell=""):
    """Choose the text and note the settings page shows."""
    environment = (environment or "").strip()
    stored = (stored or "").strip()
    shell = (shell or "").strip()
    if environment:
        message = ENV_MESSAGE
        if stored and stored != environment:
            message += " A different key is already saved. Saving replaces it."
        return environment, message
    if shell:
        message = BASHRC_MESSAGE
        if stored and stored != shell:
            message += " A different key is already saved. Saving replaces it."
        return shell, message
    if stored:
        return stored, STORED_MESSAGE
    return "", ""


def load_api_key():
    """Prefer the saved key, then the process environment, then .bashrc."""
    return read_stored_api_key() or environment_api_key() or bashrc_api_key()


def _schema(name):
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    return Secret.Schema.new(
        name,
        Secret.SchemaFlags.NONE,
        {"application": Secret.SchemaAttributeType.STRING},
    )


def read_stored_api_key(schema_name=SCHEMA_NAME):
    """Return the keyring value, or an empty string when nothing is stored."""
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        value = Secret.password_lookup_sync(
            _schema(schema_name),
            {"application": "kids-typing"},
            None,
        )
    except Exception as exc:
        print(f"kids-typing: could not read the saved key: {exc}", file=sys.stderr)
        return ""
    return (value or "").strip()


def write_stored_api_key(key, schema_name=SCHEMA_NAME):
    """Store the key in the session keyring, or remove it when blank."""
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    schema = _schema(schema_name)
    attributes = {"application": "kids-typing"}
    key = (key or "").strip()
    if not key:
        Secret.password_clear_sync(schema, attributes, None)
        return
    saved = Secret.password_store_sync(
        schema,
        attributes,
        Secret.COLLECTION_DEFAULT,
        "Kids Typing xAI API key",
        key,
        None,
    )
    if not saved:
        raise RuntimeError("the keyring did not store the key")


def download_speech(text, voice, api_key):
    """Return MP3 bytes from the xAI text-to-speech API, or None."""
    payload = json.dumps(
        {"text": text, "voice_id": voice, "language": "en"}
    ).encode()
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            try:
                exc.read()
            except OSError:
                pass
            if exc.code == 402:
                raise VoiceBillingError
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            print(
                f"kids-typing: voice API returned {exc.code} for {voice}",
                file=sys.stderr,
            )
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            print(f"kids-typing: voice API failed: {exc}", file=sys.stderr)
            return None
        if not _looks_like_audio(data):
            print(
                f"kids-typing: voice API did not return audio for {voice}",
                file=sys.stderr,
            )
            return None
        return data
    return None


def _looks_like_audio(data):
    if data is None or len(data) < 64:
        return False
    if data[:1] in (b"{", b"<", b"["):
        return False
    return True


class VoiceLibrary:
    def __init__(self, directory, api_key="", voice=DEFAULT_VOICE, download=None):
        self.directory = Path(directory)
        self.api_key = (api_key or "").strip()
        self.voice = (voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
        self.download = download or download_speech
        self._guard = threading.Lock()
        self._text_locks = {}
        self.billing = False
        self._said_billing = False

    def _lock_for(self, text, voice):
        key = f"{voice}\n{text}"
        with self._guard:
            lock = self._text_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._text_locks[key] = lock
            return lock

    def _voice(self, voice):
        chosen = (voice or self.voice or DEFAULT_VOICE).strip().lower()
        return chosen or DEFAULT_VOICE

    @property
    def enabled(self):
        return bool(self.api_key)

    def cached(self, text, voice=None):
        path = self._path(text, voice)
        if path.is_file() and path.stat().st_size > 0:
            return path
        return None

    def clip(self, text, voice=None):
        """Return a saved recording, downloading it once when a key is set."""
        voice = self._voice(voice)
        found = self.cached(text, voice)
        if found is not None:
            return found
        if not self.enabled or not text or self.billing:
            return None
        with self._lock_for(text, voice):
            found = self.cached(text, voice)
            if found is not None:
                return found
            if self.billing:
                return None
            try:
                data = self.download(text, voice, self.api_key)
            except VoiceBillingError:
                self._note_billing()
                return None
            if not _looks_like_audio(data):
                return None
            path = self._path(text, voice)
            path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".part")
            temporary.write_bytes(data)
            os.replace(temporary, path)
            return path

    def _path(self, text, voice=None):
        voice = self._voice(voice)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:40] or "clip"
        digest = hashlib.sha256(f"{voice}\n{text}".encode()).hexdigest()[:10]
        return self.directory / voice / f"{slug}-{digest}.mp3"

    def _note_billing(self):
        self.billing = True
        if self._said_billing:
            return
        self._said_billing = True
        print(
            "kids-typing: voice downloads stopped because the API account is out of credits",
            file=sys.stderr,
        )


def letter_phrases():
    """The spoken text for a through z, each once."""
    from kids_logic import letter_speech

    phrases = []
    seen = set()
    for character in "abcdefghijklmnopqrstuvwxyz":
        text = letter_speech(character)
        if text not in seen:
            seen.add(text)
            phrases.append(text)
    return phrases


def number_phrases():
    """The spoken text for 0 through 9. The app says the digit itself."""
    from kids_logic import letter_speech

    return [letter_speech(character) for character in "0123456789"]


def startup_phrases():
    """Letters and digits decoded when the window opens.

    Toddler words are left out. One word is prepared when it is selected.
    """
    phrases = letter_phrases()
    seen = set(phrases)
    for text in number_phrases():
        if text not in seen:
            seen.add(text)
            phrases.append(text)
    return phrases


def catalog_phrases():
    """Every letter, number, and toddler word the app speaks, each once."""
    from kids_logic import WORDS

    phrases = startup_phrases()
    seen = set(phrases)
    for word in WORDS:
        if word not in seen:
            seen.add(word)
            phrases.append(word)
    return phrases


SESSION_VOICES = 10


def session_voices(voices, count=SESSION_VOICES, sample=None):
    """Choose the voices loaded for letters when the app opens.

    A fresh subset is taken each call. The result keeps the roster's order.
    """
    names = []
    for voice in voices:
        voice = (voice or "").strip().lower()
        if voice and voice not in names:
            names.append(voice)
    if count <= 0 or len(names) <= count:
        return tuple(names)
    if sample is None:
        picked = random.sample(names, count)
    else:
        picked = list(sample(list(names), count))
    order = {name: index for index, name in enumerate(names)}
    picked.sort(key=lambda name: order.get(name, 0))
    return tuple(picked)


class VoiceRoster:
    """Pick a voice for each phrase. A pinned voice never changes."""

    def __init__(self, voices=VOICES, pinned=""):
        self.pinned = (pinned or "").strip().lower()
        names = []
        for voice in voices:
            voice = (voice or "").strip().lower()
            if voice and voice not in names:
                names.append(voice)
        if self.pinned and self.pinned not in names:
            names.append(self.pinned)
        self.voices = tuple(names) or (DEFAULT_VOICE,)
        self._last = ""

    def pick(self, choose=None):
        if self.pinned:
            return self.pinned
        return self._choose(self.voices, choose)

    def pick_from(self, candidates, choose=None):
        """Pick among voices that already have this phrase, when any do."""
        if self.pinned:
            return self.pinned
        names = [voice for voice in candidates if voice in self.voices]
        if not names:
            return self.pick(choose)
        return self._choose(names, choose)

    def _choose(self, choices, choose):
        remaining = [voice for voice in choices if voice != self._last] or list(choices)
        voice = random.choice(remaining) if choose is None else choose(remaining)
        self._last = voice
        return voice


def prefetch(library, phrases, voices, workers=4, on_saved=None):
    """Download any missing letter and word clip. Cached files are left alone.

    on_saved(voice, text) runs after a clip is written, so playback can
    decode it before the first key asks for it.
    """
    skipped = 0
    missing = []
    for voice in voices:
        for text in phrases:
            if library.cached(text, voice) is None:
                missing.append((voice, text))
            else:
                skipped += 1
    if not library.enabled or not missing:
        return {"saved": 0, "skipped": skipped, "failed": [], "billing": False}

    saved = 0
    failed = []
    billing = False

    def fetch(item):
        voice, text = item
        if library.billing:
            return voice, text, "stopped"
        stored = library.clip(text, voice) is not None
        if library.billing and not stored:
            return voice, text, "billing"
        if stored and on_saved is not None:
            try:
                on_saved(voice, text)
            except Exception as exc:
                print(
                    f"kids-typing: could not decode {voice} {text}: {exc}",
                    file=sys.stderr,
                )
        return voice, text, stored

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(fetch, item) for item in missing]
        done = 0
        for future in as_completed(futures):
            voice, text, ok = future.result()
            done += 1
            if ok is True:
                saved += 1
            elif ok == "billing":
                billing = True
            elif ok == "stopped":
                billing = True
            else:
                failed.append((voice, text))
                print(
                    f"kids-typing: could not store {voice} {text}",
                    file=sys.stderr,
                )
            if not billing and (done == len(missing) or done % 25 == 0):
                print(
                    f"kids-typing: voice clips {done}/{len(missing)}",
                    file=sys.stderr,
                    flush=True,
                )
    return {"saved": saved, "skipped": skipped, "failed": failed, "billing": billing}
