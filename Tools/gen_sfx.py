"""CivWar sound palette v2. Original, reproducible synthesis; Python standard library only.

48 kHz / 16-bit / mono WAVs; use Tools/Unreal/import_audio.py to update SoundWaves.
Usage: python Tools/gen_sfx.py [output_dir] [--preview path/to/audition.wav]
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import wave

SR = 48000
TAU = math.tau
ROOT = Path(__file__).resolve().parents[1]


def zeros(seconds):
    return [0.0] * round(seconds * SR)


def mix(dst, src, at=0.0, gain=1.0):
    start = round(at * SR)
    for i in range(min(len(src), len(dst) - start)):
        dst[start + i] += src[i] * gain
    return dst


def lowpass(signal, cutoff):
    alpha = 1 - math.exp(-TAU * cutoff / SR)
    value, result = 0.0, []
    for sample in signal:
        value += alpha * (sample - value)
        result.append(value)
    return result


def highpass(signal, cutoff):
    return [x - y for x, y in zip(signal, lowpass(signal, cutoff))]


def envelope(signal, decay, attack=.002):
    return [x * min(1.0, i / max(1, attack * SR)) * math.exp(-i / (SR * decay))
            for i, x in enumerate(signal)]


def air(seconds, rng, low=80, high=7000, decay=.08, attack=.002):
    data = [rng.uniform(-1, 1) for _ in range(round(seconds * SR))]
    return envelope(highpass(lowpass(data, high), low), decay, attack)


def tone(seconds, frequency, decay=.1, end=None, attack=.002):
    n = round(seconds * SR)
    phase, result = 0.0, []
    for i in range(n):
        f = frequency if end is None else end + (frequency - end) * math.exp(-i / (SR * .035))
        result.append(math.sin(phase))
        phase += TAU * f / SR
    return envelope(result, decay, attack)


def modal(seconds, frequency, rng, material="wood"):
    # Inharmonic resonances distinguish wood, stone and metal without a synthetic voice.
    modes = {"wood": [(1, .055, 1), (2.76, .023, .45), (5.4, .012, .2)],
             "stone": [(1, .065, 1), (1.72, .045, .55), (3.81, .022, .26)],
             "metal": [(1, .16, 1), (2.41, .11, .38), (4.07, .055, .18)]}[material]
    out = zeros(seconds)
    pitch = rng.uniform(.97, 1.03)
    for ratio, decay, gain in modes:
        mix(out, tone(seconds, frequency * ratio * pitch, decay), gain=gain)
    return out


def room(signal, taps=((.037, .11), (.071, .065))):
    # Tiny early reflections, not a long reverb wash; preserve clarity during unit swarms.
    out = signal[:]
    reflection = lowpass(signal, 2400)
    for delay, gain in taps:
        mix(out, reflection, delay, gain)
    return out


def s_swing(rng):
    out = air(.22, rng, 300, 4200, .06, .025)
    return mix(out, air(.12, rng, 90, 700, .035, .012), .035, .45)


def s_hit_flesh(rng):
    out = tone(.24, rng.uniform(135, 155), .042, end=62)
    mix(out, air(.24, rng, 70, 1700, .024), gain=1.05)
    mix(out, modal(.15, 220, rng), .012, .18)
    return room(out)


def s_hit_metal(rng):
    out = modal(.44, rng.uniform(510, 570), rng, "metal")
    mix(out, air(.12, rng, 900, 6500, .01, .0007), gain=.65)
    mix(out, tone(.2, 120, .04, end=65), gain=.3)
    return room(out)


def s_sling(rng):
    out = air(.26, rng, 500, 3500, .06, .03)
    mix(out, modal(.13, 460, rng, "stone"), .018, .32)
    mix(out, air(.035, rng, 1600, 6200, .006), .027, .9)
    return out


def s_bow(rng):
    out = zeros(.36)
    # Damped string with a wooden bow-body click and an airy release.
    for harmonic, gain in [(1, .6), (2, .28), (3, .12), (5, .05)]:
        mix(out, tone(.36, rng.uniform(176, 184) * harmonic, .065 / harmonic), gain=gain)
    mix(out, modal(.16, 320, rng), gain=.3)
    mix(out, air(.15, rng, 1000, 4500, .035, .008), .018, .6)
    return out


def s_gun(rng, machine=False):
    length = .18 if machine else .42
    out = tone(length, rng.uniform(160, 190), .042, end=76)
    mix(out, air(length, rng, 240, 5600, .018, .0007), gain=2.1)
    mix(out, air(length, rng, 60, 1100, .08), gain=.55)
    mix(out, modal(.1, 750, rng, "metal"), .022, .07)
    return room(out, ((.044, .09), (.087, .045)))


def s_cannon(rng):
    out = tone(1.05, rng.uniform(100, 112), .14, end=38)
    mix(out, air(1.05, rng, 45, 2200, .19), gain=2.0)
    mix(out, air(.12, rng, 350, 5200, .016), gain=1.2)
    mix(out, modal(.2, 170, rng, "metal"), .055, .25)
    return room(out, ((.079, .12), (.143, .075)))


def s_explosion(rng):
    out = tone(1.25, 88, .19, end=35, attack=.003)
    mix(out, air(1.25, rng, 35, 2500, .25, .004), gain=2.5)
    mix(out, air(.17, rng, 300, 4500, .024), gain=.8)
    for _ in range(12):
        at = rng.uniform(.07, .8)
        mix(out, modal(.09, rng.uniform(240, 1000), rng, "stone"), at, .09 * math.exp(-at * 2))
    return room(out, ((.093, .1), (.17, .06)))


def s_death(rng):
    # Equipment/fabric falling, deliberately no repeated synthetic human groan.
    out = zeros(.46)
    mix(out, air(.3, rng, 150, 1800, .08, .018), gain=.5)
    mix(out, tone(.25, 105, .055, end=55), .13, .8)
    mix(out, modal(.18, 230, rng, "wood"), .16, .28)
    return out


def s_base_hit(rng):
    out = tone(.62, 130, .105, end=48)
    mix(out, air(.62, rng, 60, 1500, .14), gain=1.3)
    for at in [.035, .09, .16, .24]:
        mix(out, modal(.16, rng.uniform(160, 330), rng, "stone"), at, .2)
    return room(out)


def bell(seconds, frequency):
    out = zeros(seconds)
    for ratio, gain, decay in [(1, 1, .25), (2.01, .24, .13), (3.98, .065, .07)]:
        mix(out, tone(seconds, frequency * ratio, decay, attack=.005), gain=gain)
    return out


def horn(seconds, frequency):
    out = zeros(seconds)
    for harmonic, gain in [(1, 1), (2, .35), (3, .13), (4, .035)]:
        mix(out, tone(seconds, frequency * harmonic, seconds * .68, attack=.045), gain=gain)
    fade = round(min(.25, seconds * .4) * SR)
    for i in range(fade):
        out[-i - 1] *= i / fade
    return out


def s_ageup(rng):
    out = zeros(1.9)
    for frequency, at in [(293.665, 0), (440, .19), (587.33, .38)]:
        mix(out, bell(.95, frequency), at, .36)
    for frequency, gain in [(146.833, .18), (293.665, .22), (440, .13)]:
        mix(out, horn(1.15, frequency), .56, gain)
    mix(out, tone(.5, 95, .09, end=48), .56, .3)
    mix(out, air(.8, rng, 2000, 6500, .2, .03), .5, .12)
    return room(out, ((.061, .12), (.127, .08)))


def s_ui_click(rng):
    out = modal(.09, 740, rng, "wood")
    mix(out, tone(.09, 1174.66, .017, attack=.001), gain=.16)
    return out


def s_ui_error(rng):
    out = zeros(.25)
    mix(out, bell(.16, 293.665), gain=.4)
    mix(out, bell(.16, 246.942), .075, .3)
    return lowpass(out, 2200)


def s_train(rng):
    out = zeros(.36)
    mix(out, modal(.15, 440, rng), gain=.26)
    mix(out, bell(.26, 587.33), .07, .24)
    return out


def s_victory(rng):
    out = zeros(2.7)
    for frequency, at in [(293.665, 0), (369.994, .18), (440, .36), (587.33, .6)]:
        mix(out, horn(.7, frequency), at, .26)
        mix(out, bell(.75, frequency * 2), at, .07)
    for frequency, gain in [(146.833, .22), (293.665, .25), (369.994, .14), (440, .16)]:
        mix(out, horn(1.6, frequency), .95, gain)
    for at in [0, .36, .95]:
        mix(out, tone(.3, 100, .08, end=48), at, .3)
    mix(out, air(1.0, rng, 2200, 6000, .28, .02), .95, .1)
    return room(out, ((.071, .12), (.137, .08)))


def s_defeat(rng):
    out = zeros(2.2)
    for frequency, at in [(293.665, 0), (261.626, .28), (220, .59)]:
        mix(out, bell(.8, frequency), at, .23)
    mix(out, horn(1.2, 146.833), .8, .3)
    mix(out, horn(1.2, 174.614), .8, .15)
    return room(lowpass(out, 2100))


def s_skill_warning(rng):
    out = zeros(.9)
    # Three rising pulses: readable urgency without a sustained piercing siren.
    for at, frequency in [(0, 440), (.24, 523.251), (.48, 622.254)]:
        mix(out, bell(.32, frequency), at, .4)
        mix(out, tone(.2, 110, .04), at, .2)
    return out


def s_turret_build(rng):
    out = zeros(.55)
    for at, freq in [(0, 210), (.12, 270), (.26, 360)]:
        mix(out, modal(.2, freq, rng, "wood"), at, .45)
        mix(out, air(.07, rng, 300, 2800, .015), at, .3)
    mix(out, bell(.22, 880), .3, .1)
    return out


def s_meteor_fall(rng):
    out = air(.78, rng, 80, 2300, .55, .22)
    mix(out, tone(.78, 760, .5, end=145, attack=.09), gain=.1)
    return out


def s_laser(rng):
    out = tone(.27, rng.uniform(1000, 1100), .048, end=220, attack=.001)
    mix(out, tone(.27, 1650, .024, end=540), gain=.18)
    mix(out, air(.12, rng, 1400, 6500, .012), gain=.28)
    mix(out, tone(.17, 120, .04, end=70), gain=.35)
    return room(out, ((.031, .11),))


def s_rocket(rng):
    out = zeros(.64)
    mix(out, air(.2, rng, 120, 3800, .03), gain=1.1)
    mix(out, air(.56, rng, 80, 1900, .23, .025), .025, 1.6)
    mix(out, tone(.4, 145, .08, end=58), gain=.4)
    return out


# Event order is a stable seed contract, mirrored in CWAudio::ESound.
# name, generator, variants, peak ceiling dBFS, RMS ceiling dBFS
SPECS = [
    ("Swing", s_swing, 3, -9, -24), ("HitFlesh", s_hit_flesh, 3, -7, -22),
    ("HitMetal", s_hit_metal, 3, -9, -24), ("Sling", s_sling, 3, -10, -25),
    ("Bow", s_bow, 3, -9, -24), ("Gun", s_gun, 3, -7, -23),
    ("MachineGun", lambda rng: s_gun(rng, True), 3, -9, -24),
    ("Cannon", s_cannon, 3, -5, -21), ("Explosion", s_explosion, 3, -5, -21),
    ("Death", s_death, 3, -11, -25), ("BaseHit", s_base_hit, 3, -6, -22),
    ("AgeUp", s_ageup, 1, -7, -22), ("UIClick", s_ui_click, 1, -14, -29),
    ("UIError", s_ui_error, 1, -13, -28), ("Train", s_train, 1, -14, -29),
    ("Victory", s_victory, 1, -6, -21), ("Defeat", s_defeat, 1, -10, -25),
    ("SkillWarning", s_skill_warning, 1, -10, -25),
    ("TurretBuild", s_turret_build, 3, -10, -25),
    ("MeteorFall", s_meteor_fall, 3, -9, -24),
    ("Laser", s_laser, 3, -9, -24), ("Rocket", s_rocket, 3, -8, -23),
]


def finish(signal, peak_db, rms_db):
    signal = lowpass(highpass(signal, 28), 8500)
    # Fade both edges; DC removal alone can reintroduce a discontinuity at the start.
    fade_in, fade_out = round(.0008 * SR), min(round(.018 * SR), len(signal) // 3)
    for i in range(fade_in):
        signal[i] *= .5 - .5 * math.cos(math.pi * i / fade_in)
    for i in range(fade_out):
        signal[-1 - i] *= .5 - .5 * math.cos(math.pi * i / fade_out)
    peak = max(abs(x) for x in signal) or 1
    rms = math.sqrt(sum(x * x for x in signal) / len(signal)) or 1
    gain = min(10 ** (peak_db / 20) / peak, 10 ** (rms_db / 20) / rms)
    return [x * gain for x in signal]


def write_wav(path, samples):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, SR, 0, "NONE", "not compressed"))
        stream.writeframes(struct.pack("<%dh" % len(samples), *(round(x * 32767) for x in samples)))


def metrics(samples):
    return {"duration": round(len(samples) / SR, 6),
            "peak_dbfs": round(20 * math.log10(max(abs(x) for x in samples) or 1e-12), 3),
            "rms_dbfs": round(20 * math.log10(math.sqrt(sum(x*x for x in samples) / len(samples)) or 1e-12), 3),
            "dc": round(sum(samples) / len(samples), 7)}


def generate(out_dir, preview=None):
    out_dir = Path(out_dir)
    manifest = {"version": 2, "sample_rate": SR, "channels": 1, "bits": 16,
                "provenance": "Original deterministic procedural synthesis. No third-party samples.", "assets": []}
    primary = {}
    for index, (name, fn, variants, peak_db, rms_db) in enumerate(SPECS):
        for variant in range(variants):
            seed = 20261021 + index * 100 + variant
            samples = finish(fn(random.Random(seed)), peak_db, rms_db)
            suffix = "" if variant == 0 else "_V%02d" % (variant + 1)
            path = out_dir / ("SFX_" + name + suffix + ".wav")
            write_wav(path, samples)
            manifest["assets"].append({"file": path.name, "event": name, "variant": variant + 1, "seed": seed,
                                        "peak_ceiling_dbfs": peak_db, "rms_ceiling_dbfs": rms_db,
                                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **metrics(samples)})
            if variant == 0:
                primary[name] = samples
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if preview:
        order = ["UIClick", "UIError", "Train", "TurretBuild", "Swing", "HitFlesh", "HitMetal", "Sling", "Bow",
                 "Gun", "MachineGun", "Cannon", "Laser", "Rocket", "Explosion", "BaseHit", "Death", "SkillWarning",
                 "MeteorFall", "AgeUp", "Victory", "Defeat"]
        montage, cues = zeros(.25), []
        for name in order:
            cues.append({"event": name, "start_seconds": round(len(montage) / SR, 3)})
            montage.extend(primary[name])
            montage.extend(zeros(.3))
        write_wav(preview, montage)
        Path(preview).with_suffix(".json").write_text(json.dumps(cues, indent=2) + "\n", encoding="utf-8")
    print("Generated %d WAVs / %d events -> %s" % (len(manifest["assets"]), len(SPECS), out_dir))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", nargs="?", type=Path, default=ROOT / "RawAssets" / "Audio")
    parser.add_argument("--preview", type=Path, help="Write an isolated-cue listening reel outside the import directory")
    options = parser.parse_args()
    generate(options.output_dir, options.preview)
