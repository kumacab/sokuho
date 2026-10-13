"""Fonds sonores doux et ORIGINAUX pour les reels (nappe tenue + souffle léger), sans rythme ni mélodie.

Lancement : python tools/make_ambient.py → assets/music/ambient/sokuho_ambient_<n>.mp3
"""
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "music" / "ambient"
# accords lents (fréquences en Hz) : tons doux, rien d'agressif
PADS = [
    [130.81, 196.00, 261.63, 329.63],   # do majeur ouvert
    [110.00, 164.81, 220.00, 261.63],   # la mineur
    [146.83, 220.00, 293.66, 369.99],   # ré majeur
]


def pad(freqs, seconds=16, seed=0):
    rnd = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    out = np.zeros_like(t)
    for i, f in enumerate(freqs):
        lfo = 1 + 0.003 * np.sin(2 * np.pi * (0.07 + 0.02 * i) * t)  # léger flottement
        amp = 0.5 + 0.5 * np.sin(2 * np.pi * (0.05 + 0.013 * i) * t + i)
        for d in (-0.002, 0.002):
            out += np.sin(2 * np.pi * f * (1 + d) * t * lfo) * amp
    noise = rnd.standard_normal(len(t))
    acc, a = 0.0, np.exp(-2 * np.pi * 400 / SR)  # souffle filtré, très bas
    soft = np.empty_like(noise)
    for k in range(len(noise)):
        acc = (1 - a) * noise[k] + a * acc
        soft[k] = acc
    out = out / np.max(np.abs(out)) + soft / np.max(np.abs(soft)) * 0.08
    env = np.minimum(1, t / 2.0) * np.minimum(1, (seconds - t) / 2.0)
    out = out * env
    return (out / np.max(np.abs(out)) * 0.30 * 32767).astype(np.int16)  # volume bas : fond, pas musique


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for n, freqs in enumerate(PADS, 1):
        wav = OUT / f"sokuho_ambient_{n}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pad(freqs, seed=n).tobytes())
        mp3 = wav.with_suffix(".mp3")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "2", "-b:a", "128k", str(mp3)],
                       check=True)
        wav.unlink()
        print(mp3)


if __name__ == "__main__":
    main()
