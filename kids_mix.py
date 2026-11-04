"""Mix letter sounds so a fast run of keys is heard together.

PipeWire plays one stream. Each new clip is added into that stream instead
of stopping the one that is already playing. Each voice keeps a fixed gain,
and the stream stays a few frames ahead of the speakers so a new letter is
not stuck behind a long buffer. Saved letter and number clips for the
voices chosen at launch are decoded into memory when the window opens. A
toddler word is decoded, with that voice's letter sounds, when the word
is selected.
"""

import array
import fcntl
import math
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time

RATE = 48000
FRAME = 480  # 10 ms, so a new letter joins on the next slice
FRAME_SECONDS = FRAME / RATE
# Audio already handed to the stream. More than this and a new letter waits.
TARGET_AHEAD = 0.04
# Full-scale clips summed at this gain stay off the rail, then tanh rounds the peak.
VOICE_GAIN = 0.58


def pcm_from_media(path):
    """Decode an audio file to mono 16-bit PCM at RATE. Empty on failure."""
    if not path or not shutil.which("ffmpeg"):
        return b""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        return b""
    data = proc.stdout
    if len(data) % 2:
        data = data[:-1]
    return data if len(data) >= 2 else b""


def espeak_pcm(text):
    """Render speech with espeak-ng and return mixable PCM. Empty on failure."""
    if not text or not shutil.which("espeak-ng"):
        return b""
    with tempfile.TemporaryDirectory() as directory:
        wav = f"{directory}/say.wav"
        proc = subprocess.run(
            ["espeak-ng", "-v", "en-us", "-s", "120", "-a", "180", "-w", wav, "--", text],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            return b""
        return pcm_from_media(wav)


def _soft_clip(sample):
    """Round a summed sample so overlapping letters do not hard-clip."""
    if sample > 96000:
        sample = 96000
    elif sample < -96000:
        sample = -96000
    return int(math.tanh(sample / 32768.0) * 32767.0)


def pace_wait(written, started, now, frame_seconds=FRAME_SECONDS, target_ahead=TARGET_AHEAD):
    """How long to wait before writing the next frame.

    Returns (wait, written, started). Audio that has already fallen behind
    the clock is dropped, so a stall does not burst out later as a pile of
    late letters.
    """
    if started is None:
        return 0.0, written, now
    queued = written - (now - started)
    if queued < 0:
        return 0.0, 0.0, now
    if queued > target_ahead:
        return min(queued - target_ahead, frame_seconds), written, started
    return 0.0, written, started


def mix_frame(voices, count):
    """Add `count` samples from each voice into one 16-bit frame.

    Voices are dicts with "samples" (array of signed shorts) and "pos".
    Finished voices are returned so the caller can drop them. Each voice
    keeps a fixed gain. A second letter does not duck the one already playing.
    """
    if not voices or count <= 0:
        return array.array("h"), []
    mixed = [0.0] * count
    finished = []
    for voice in voices:
        samples = voice["samples"]
        pos = voice["pos"]
        end = pos + count
        if end > len(samples):
            end = len(samples)
        for index, sample in enumerate(samples[pos:end]):
            mixed[index] += sample * VOICE_GAIN
        voice["pos"] = end
        if end >= len(samples):
            finished.append(voice)
    out = array.array("h")
    for sample in mixed:
        out.append(_soft_clip(sample))
    return out, finished


class VoiceMix:
    """One PipeWire stream that several clips play into at once."""

    def __init__(self, spawn=None):
        self._spawn = spawn or _spawn_pw_cat
        self._lock = threading.Lock()
        self._voices = []
        self._closed = threading.Event()
        self._thread = None
        self._proc = None
        self._reported = False
        self._clock = time.monotonic
        self._sleep = time.sleep

    def warm(self):
        """Open the stream before the first key, so playback starts quickly."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._closed.clear()
            self._thread = threading.Thread(target=self._loop, name="kids-mix", daemon=True)
            self._thread.start()

    def play(self, pcm, on_done=None):
        """Start pcm over whatever is already playing. Return False if it cannot."""
        if not pcm:
            return False
        samples = array.array("h")
        usable = pcm[: len(pcm) - (len(pcm) % 2)]
        if len(usable) < 2:
            return False
        samples.frombytes(usable)
        voice = {"samples": samples, "pos": 0, "on_done": on_done}
        with self._lock:
            if self._closed.is_set():
                return False
            self._voices.append(voice)
        self.warm()
        return True

    def stop(self):
        """Drop every clip that is playing. Their callbacks are not run."""
        with self._lock:
            self._voices.clear()

    def close(self):
        """Stop playback and release PipeWire."""
        self._closed.set()
        self.stop()
        proc = self._proc
        if proc is not None and proc.stdin is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        self._kill_proc()
        self._thread = None

    def _kill_proc(self):
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.poll() is None:
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except OSError:
                pass
            proc.terminate()
        try:
            proc.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=0.3)

    def render(self, count):
        """Mix the next `count` samples. Used by the stream and by tests."""
        with self._lock:
            voices = list(self._voices)
        if not voices:
            return b"\x00" * (count * 2), []
        frame, finished = mix_frame(voices, count)
        callbacks = []
        with self._lock:
            for voice in finished:
                if voice in self._voices:
                    self._voices.remove(voice)
                    if voice["on_done"] is not None:
                        callbacks.append(voice["on_done"])
        return frame.tobytes(), callbacks

    def _loop(self):
        proc = None
        failures = 0
        started = None
        written = 0.0
        try:
            while not self._closed.is_set():
                if proc is None or proc.poll() is not None:
                    proc = self._spawn()
                    self._proc = proc
                    started = None
                    written = 0.0
                    if proc is None:
                        failures += 1
                        if failures >= 3:
                            self._give_up()
                            failures = 0
                        self._sleep(0.05)
                        continue
                    failures = 0
                    _limit_pipe(proc)
                wait, written, started = pace_wait(
                    written, started, self._clock()
                )
                if wait > 0 and not self._closed.is_set():
                    self._sleep(wait)
                    continue
                data, callbacks = self.render(FRAME)
                try:
                    proc.stdin.write(data)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError, ValueError):
                    proc = None
                    self._proc = None
                    started = None
                    written = 0.0
                    continue
                written += FRAME_SECONDS
                for callback in callbacks:
                    try:
                        callback()
                    except Exception as exc:
                        print(f"kids-typing: voice callback failed: {exc}", file=sys.stderr)
        finally:
            if self._proc is proc:
                self._kill_proc()
            elif proc is not None:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=0.3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=0.3)

    def _give_up(self):
        if not self._reported:
            self._reported = True
            print("kids-typing: could not open the audio mix", file=sys.stderr)
        with self._lock:
            voices = list(self._voices)
            self._voices.clear()
        for voice in voices:
            callback = voice.get("on_done")
            if callback is not None:
                try:
                    callback()
                except Exception:
                    pass


def _spawn_pw_cat():
    if not shutil.which("pw-cat"):
        return None
    try:
        return subprocess.Popen(
            [
                "pw-cat",
                "--playback",
                "--raw",
                "--format",
                "s16",
                "--rate",
                str(RATE),
                "--channels",
                "1",
                "--channel-map",
                "MONO",
                "--latency",
                "20ms",
                "--media-role",
                "Game",
                "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        print(f"kids-typing: pw-cat failed: {exc}", file=sys.stderr)
        return None


def _limit_pipe(proc):
    """Keep the OS pipe to a few frames so a new letter cannot sit behind it."""
    stdin = getattr(proc, "stdin", None)
    fileno = getattr(stdin, "fileno", None)
    if fileno is None:
        return
    try:
        # 4096 bytes is about 43 ms of 48 kHz mono s16, and the smallest pipe.
        fcntl.fcntl(fileno(), fcntl.F_SETPIPE_SZ, 4096)
    except (OSError, AttributeError, ValueError):
        return


class Speaker:
    """Play phrases. Letters overlap. An exclusive phrase stops the others."""

    def __init__(self, library=None, mix=None, decode=None, speak=None, dispatch=None, synchronous=False, roster=None, on_letters_ready=None):
        from kids_voice import DEFAULT_VOICE, VOICES, VoiceLibrary, VoiceRoster, load_api_key
        import os
        from pathlib import Path

        pinned = os.environ.get("KIDS_TYPING_VOICE", "").strip()
        if roster is None:
            from kids_voice import SESSION_VOICES, session_voices

            names = (pinned,) if pinned else session_voices(VOICES, SESSION_VOICES)
            roster = VoiceRoster(names, pinned)
        self.roster = roster
        self.word_voice = ""
        self.library = library or VoiceLibrary(
            Path.home() / ".local" / "share" / "kids-typing" / "voices",
            api_key=load_api_key(),
            voice=pinned or DEFAULT_VOICE,
        )
        self.mix = mix or VoiceMix()
        self.decode = decode or pcm_from_media
        self.speak = speak or espeak_pcm
        self.dispatch = dispatch or _glib_dispatch
        self.synchronous = synchronous
        self._generation = 0
        self._pcm_cache = {}
        self._cache_lock = threading.Lock()
        self._said_fallback = False
        self._prefetch_started = False
        self._preload_started = False
        self._prepare_generation = 0
        self.on_letters_ready = on_letters_ready

    def warm(self):
        self.mix.warm()
        self.preload()
        self.prefetch()

    def preload(self):
        """Decode saved letter and number clips. Toddler words wait until selected."""
        if self._preload_started:
            return
        self._preload_started = True
        threading.Thread(target=self._preload_saved, name="kids-pcm", daemon=True).start()

    def _preload_saved(self):
        from kids_voice import letter_phrases, number_phrases

        jobs = [
            (text, voice)
            for text in letter_phrases() + number_phrases()
            for voice in self.roster.voices
        ]
        decoded = 0
        try:
            decoded = self._decode_jobs(jobs)
        finally:
            self._notify_letters_ready()
        print(
            f"kids-typing: decoded {decoded} saved clips into memory",
            file=sys.stderr,
            flush=True,
        )

    def _decode_jobs(self, jobs):
        from concurrent.futures import ThreadPoolExecutor

        if not jobs:
            return 0
        decoded = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for stored in pool.map(self._remember_job, jobs):
                decoded += stored
        return decoded

    def _notify_letters_ready(self):
        callback = self.on_letters_ready
        if callback is None:
            return
        self.dispatch(callback)

    def _remember_job(self, item):
        text, voice = item
        return 1 if self._remember_pcm(text, voice) else 0

    def _saved_clip(self, voice, text):
        """Decode a clip prefetch just wrote. Prefetch reports the voice first."""
        self._remember_pcm(text, voice)

    def _remember_pcm(self, text, voice):
        """Decode one saved clip into the playback cache. Do not download."""
        voice = (voice or "").strip().lower()
        text = text or ""
        if not voice or not text:
            return False
        key = (voice, text)
        with self._cache_lock:
            if key in self._pcm_cache:
                return False
        path = self.library.cached(text, voice)
        if not path:
            return False
        try:
            pcm = self.decode(path)
        except Exception as exc:
            print(
                f"kids-typing: could not decode {voice} {text}: {exc}",
                file=sys.stderr,
            )
            return False
        if not pcm:
            return False
        with self._cache_lock:
            if key in self._pcm_cache:
                return False
            self._pcm_cache[key] = pcm
        return True

    def prefetch(self):
        """Fetch this launch's letter and number clips without blocking the window."""
        if self._prefetch_started or not getattr(self.library, "enabled", False):
            return
        self._prefetch_started = True
        threading.Thread(target=self._prefetch_missing, name="kids-voices", daemon=True).start()

    def _prefetch_missing(self):
        from kids_voice import prefetch, startup_phrases

        summary = prefetch(
            self.library,
            startup_phrases(),
            self.roster.voices,
            on_saved=self._saved_clip,
        )
        print(
            "kids-typing: voice clips "
            f"saved {summary['saved']}, "
            f"already stored {summary['skipped']}, "
            f"failed {len(summary['failed'])}",
            file=sys.stderr,
            flush=True,
        )

    def prepare_word(self, text, letters=(), on_voices=None, on_done=None, on_fetch=None):
        """Fetch one voice of this word and that voice's letter sounds, then decode them."""
        text = text or ""
        self._prepare_generation += 1
        generation = self._prepare_generation
        phrases = _unique_phrases((text, *letters))
        voice = self.random_voice(text) if text else ""
        self.word_voice = voice
        if not phrases:
            self._fire_prepare(on_done, generation)
            return
        if not self.phrases_ready(voice, phrases) and on_fetch is not None:
            on_fetch()
        if self.synchronous:
            self._prepare_word(phrases, voice, on_voices, on_done, generation, on_fetch)
            return
        threading.Thread(
            target=self._prepare_word,
            args=(phrases, voice, on_voices, on_done, generation, on_fetch),
            name="kids-word",
            daemon=True,
        ).start()

    def prepare_letters(self, voice, phrases, on_fetch=None, on_done=None):
        """Fetch and decode clips for the voice that is reading this word."""
        voice = (voice or "").strip().lower()
        phrases = _unique_phrases(phrases)
        if not voice or not phrases:
            if on_done is not None:
                on_done()
            return
        self.word_voice = voice
        self._prepare_generation += 1
        generation = self._prepare_generation
        if not self.phrases_ready(voice, phrases) and on_fetch is not None:
            on_fetch()
        if self.synchronous:
            self._warm_phrases(phrases, voice, on_done, generation, on_fetch)
            return
        threading.Thread(
            target=self._warm_phrases,
            args=(phrases, voice, on_done, generation, on_fetch),
            name="kids-letters",
            daemon=True,
        ).start()

    def phrases_ready(self, voice, phrases):
        """True when every phrase is decoded Grok audio in memory."""
        voice = (voice or "").strip().lower()
        phrases = _unique_phrases(phrases)
        if not voice or not phrases:
            return False
        with self._cache_lock:
            return all(self._pcm_cache.get((voice, phrase)) for phrase in phrases)

    def drop_phrases(self, voice, phrases):
        """Forget decoded clips for a finished word. Files on disk stay."""
        voice = (voice or "").strip().lower()
        if not voice:
            return
        with self._cache_lock:
            for phrase in _unique_phrases(phrases):
                self._pcm_cache.pop((voice, phrase), None)

    def _prepare_word(self, phrases, voice, on_voices, on_done, generation, on_fetch=None):
        if not self._fill_phrases(phrases, voice, generation, on_fetch):
            return
        self._fire_prepare(on_voices, generation)
        self._fire_prepare(on_done, generation)

    def _warm_phrases(self, phrases, voice, on_done, generation, on_fetch=None):
        if not self._fill_phrases(phrases, voice, generation, on_fetch):
            return
        self._fire_prepare(on_done, generation)

    def _fill_phrases(self, phrases, voice, generation, on_fetch):
        """Decode every clip into memory. Retry downloads until that is true."""
        told = False
        while generation == self._prepare_generation:
            if self.phrases_ready(voice, phrases):
                return True
            try:
                self._fetch_phrases(phrases, voice)
                if generation != self._prepare_generation:
                    return False
                if voice:
                    self._decode_jobs([(phrase, voice) for phrase in phrases])
            except Exception as exc:
                print(
                    f"kids-typing: could not prepare {phrases[:1]}: {exc}",
                    file=sys.stderr,
                )
            if generation != self._prepare_generation:
                return False
            if self.phrases_ready(voice, phrases):
                return True
            if on_fetch is not None:
                self._fire_prepare(on_fetch, generation)
            if not told:
                told = True
                print(
                    "kids-typing: waiting for grok voice clips",
                    file=sys.stderr,
                    flush=True,
                )
            if self.synchronous or not getattr(self.library, "enabled", False):
                return False
            if not self._pause_prepare(generation):
                return False
        return False

    def _pause_prepare(self, generation):
        """Wait before another download attempt, and stop if a new word started."""
        delay = 5.0 if getattr(self.library, "billing", False) else 1.5
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if generation != self._prepare_generation:
                return False
            time.sleep(0.05)
        return generation == self._prepare_generation

    def _fetch_phrases(self, phrases, voice):
        """Download any missing clips before playback asks for them."""
        if not voice or not getattr(self.library, "enabled", False):
            return
        from kids_voice import prefetch

        prefetch(
            self.library,
            phrases,
            [voice],
            on_saved=self._saved_clip,
        )

    def _fire_prepare(self, callback, generation):
        if callback is None or generation != self._prepare_generation:
            return

        def run():
            if generation != self._prepare_generation:
                return
            callback()

        self.dispatch(run)

    def random_voice(self, text, choose=None):
        """Pick any voice that already has this phrase, or any roster voice."""
        if self.roster.pinned:
            return self.roster.pinned
        with self._cache_lock:
            cached = {voice for (voice, phrase) in self._pcm_cache if phrase == text}
        ready = [
            voice
            for voice in self.roster.voices
            if voice in cached or self.library.cached(text, voice) is not None
        ]
        pool = ready or list(self.roster.voices)
        if choose is not None:
            return choose(pool)
        return random.choice(pool)

    def say(self, text, on_done=None, exclusive=False, voice=None, fallback=True):
        if exclusive:
            self.stop()
        if not text:
            self._finish(on_done, self._generation)
            return
        generation = self._generation
        chosen = (voice or "").strip().lower()
        if not chosen:
            ready = [
                name
                for name in self.roster.voices
                if self.library.cached(text, name) is not None
            ]
            chosen = self.roster.pick_from(ready)
        voice = chosen
        cached = self._pcm_cache.get((voice, text))
        if cached is not None:
            self._play(cached, on_done, generation)
            return
        if self.synchronous:
            self._load(text, voice, on_done, generation, fallback)
            return
        threading.Thread(
            target=self._load,
            args=(text, voice, on_done, generation, fallback),
            daemon=True,
        ).start()

    def stop(self):
        """Cancel clips and in-flight loads. Pending callbacks are not run."""
        self._generation += 1
        self.mix.stop()

    def close(self):
        self._prepare_generation += 1
        self.stop()
        self.mix.close()

    def _load(self, text, voice, on_done, generation, fallback=True):
        try:
            pcm = self._produce(text, voice, fallback)
        except Exception as exc:
            print(f"kids-typing: voice failed: {exc}", file=sys.stderr)
            pcm = b""
        if self.synchronous:
            self._play(pcm, on_done, generation)
            return
        self.dispatch(lambda: self._play(pcm, on_done, generation))

    def _produce(self, text, voice, fallback=True):
        key = (voice, text)
        with self._cache_lock:
            cached = self._pcm_cache.get(key)
        if cached is not None:
            return cached
        path = self.library.cached(text, voice)
        if path is None and fallback and getattr(self.library, "enabled", False):
            path = self.library.clip(text, voice)
        pcm = self.decode(path) if path else b""
        if pcm:
            with self._cache_lock:
                return self._pcm_cache.setdefault(key, pcm)
        if not fallback:
            return b""
        self._warn_fallback()
        return self.speak(text) or b""

    def _play(self, pcm, on_done, generation):
        if generation != self._generation:
            return
        if not pcm:
            self._finish(on_done, generation)
            return

        def done():
            self._finish(on_done, generation)

        if not self.mix.play(pcm, on_done=done):
            self._finish(on_done, generation)

    def _finish(self, on_done, generation):
        if on_done is None or generation != self._generation:
            return
        self.dispatch(on_done)

    def _warn_fallback(self):
        if self._said_fallback or self.library.enabled:
            return
        self._said_fallback = True
        print("kids-typing: no XAI_API_KEY, using espeak-ng", file=sys.stderr)


def _unique_phrases(phrases):
    unique = []
    seen = set()
    for phrase in phrases:
        if phrase and phrase not in seen:
            seen.add(phrase)
            unique.append(phrase)
    return unique


def _glib_dispatch(fn):
    from gi.repository import GLib

    def wrapper():
        fn()
        return False

    GLib.idle_add(wrapper)
