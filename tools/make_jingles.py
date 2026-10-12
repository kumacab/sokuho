"""Compose les jingles ORIGINAUX des reels (aucun sample, aucun morceau existant) : 6 ambiances × 2 variantes.

Lancement : python tools/make_jingles.py  → assets/music/<ambiance>/sokuho_<ambiance>_<n>.mp3
Tout est synthétisé ici (batterie, basse, accords), donc les sons appartiennent au compte.
"""
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "music"

NOTES = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def freq(note, octave):
    return 440.0 * 2 ** ((NOTES[note] + 12 * (octave + 1) - 69) / 12)


def env(n, a=0.005, r=0.2):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / max(r, 1e-4))
    return e


def kick(n):
    t = np.arange(n) / SR
    f = 120 * np.exp(-t * 25) + 45
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def snare(n, rnd):
    t = np.arange(n) / SR
    return (rnd.standard_normal(n) * 0.6 + np.sin(2 * np.pi * 190 * t) * 0.4) * np.exp(-t * 18)


def hat(n, rnd):
    t = np.arange(n) / SR
    noise = rnd.standard_normal(n)
    noise = np.diff(noise, prepend=0)  # passe-haut grossier
    return noise * np.exp(-t * 60) * 0.35


def saw(f, n, detune=0.0):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for d in (-detune, 0, detune):
        out += 2 * ((t * f * (1 + d)) % 1) - 1
    return out / 3


def square(f, n):
    t = np.arange(n) / SR
    return np.sign(np.sin(2 * np.pi * f * t))


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


STYLES = {
    #        bpm  gamme/accords (fondamentale, octave)                         batterie        son
    "epic": (128, [("A", 2), ("F", 2), ("C", 3), ("G", 2)], "minor", "four", "saw"),
    "hype": (150, [("E", 2), ("C", 2), ("G", 2), ("D", 2)], "minor", "trap", "square"),
    "chill": (88, [("F", 2), ("A", 2), ("D", 2), ("C", 2)], "major7", "lofi", "saw"),
    "emotional": (76, [("C", 3), ("G", 2), ("A", 2), ("F", 2)], "major", "soft", "saw"),
    "dark": (100, [("D", 2), ("A#", 1), ("C", 2), ("A", 1)], "minor", "four", "square"),
    "fun": (140, [("C", 3), ("A", 2), ("F", 2), ("G", 2)], "major", "bounce", "square"),
}
CHORDS = {"minor": [0, 3, 7], "major": [0, 4, 7], "major7": [0, 4, 7, 11]}


def compose(style, variant, seconds=16):
    bpm, prog, quality, drums, timbre = STYLES[style]
    rnd = np.random.default_rng(hash((style, variant)) % 2 ** 32)
    beat = int(SR * 60 / bpm)
    n = int(SR * seconds)
    bar = beat * 4
    mix = np.zeros(n + 2 * bar)
    for b in range(int(np.ceil(n / bar))):
        root, octv = prog[(b + variant) % len(prog)]
        f0 = freq(root, octv)
        start = b * bar
        # accords tenus (pad)
        chord = np.zeros(bar)
        for iv in CHORDS[quality]:
            f = f0 * 2 ** ((iv + 12) / 12)
            chord += (saw(f, bar, 0.004) if timbre == "saw" else square(f, bar) * 0.5)
        chord = lowpass(chord, 1400 if style != "chill" else 900) * env(bar, 0.08, 2.5) * 0.10
        mix[start:start + bar] += chord
        # basse
        for k in range(8):
            if style in ("emotional",) and k % 2:
                continue
            s = start + k * beat // 2
            ln = beat // 2
            note = f0 * (2 if (k == 6 and variant) else 1)
            mix[s:s + ln] += lowpass(saw(note, ln), 500) * env(ln, 0.003, 0.18) * 0.32
        # mélodie (arpège) sur les ambiances rythmées
        if style in ("epic", "hype", "fun", "dark"):
            pattern = [0, 2, 1, 2, 0, 2, 1, 3] if variant == 0 else [0, 1, 2, 1, 3, 2, 1, 2]
            notes = CHORDS[quality] + [12]
            for k, p in enumerate(pattern):
                s = start + k * beat // 2
                ln = beat // 2
                f = f0 * 4 * 2 ** (notes[p % len(notes)] / 12)
                mix[s:s + ln] += square(f, ln) * env(ln, 0.002, 0.09) * 0.07
        # batterie
        for k in range(16):
            s = start + k * beat // 4
            ln = min(beat, len(mix) - s)
            if ln <= 0:
                continue
            on_kick = {"four": k % 4 == 0, "trap": k in (0, 6, 10), "lofi": k in (0, 7, 10),
                       "soft": k == 0, "bounce": k in (0, 6, 8, 14)}[drums]
            on_snare = {"four": k in (4, 12), "trap": k == 8, "lofi": k in (4, 12), "soft": k == 8,
                        "bounce": k in (4, 12)}[drums]
            on_hat = {"four": k % 2 == 1, "trap": True, "lofi": k % 2 == 0, "soft": k % 4 == 2,
                      "bounce": k % 2 == 1}[drums]
            if on_kick:
                mix[s:s + ln] += kick(ln) * 0.9
            if on_snare:
                mix[s:s + ln] += snare(ln, rnd) * (0.35 if drums != "soft" else 0.15)
            if on_hat:
                mix[s:s + ln] += hat(ln, rnd) * (0.6 if drums == "trap" else 0.45)
    mix = mix[:n]
    fade = int(SR * 1.5)
    mix[-fade:] *= np.linspace(1, 0, fade)
    mix = np.tanh(mix * 1.4)  # légère saturation pour la cohésion
    mix /= np.max(np.abs(mix)) + 1e-9
    return (mix * 0.9 * 32767).astype(np.int16)


def main():
    only = sys.argv[1:] or list(STYLES)
    for style in only:
        folder = OUT / style
        folder.mkdir(parents=True, exist_ok=True)
        for v in range(2):
            pcm = compose(style, v)
            wav = folder / f"sokuho_{style}_{v + 1}.wav"
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes(pcm.tobytes())
            mp3 = wav.with_suffix(".mp3")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "2", "-b:a", "160k", str(mp3)],
                           check=True)
            wav.unlink()
            print(mp3.relative_to(ROOT))


if __name__ == "__main__":
    main()
