"""Acquire and prepare the approved third-party music/SFX for CivWar.

Downloads use official URLs, first directly then the user's HTTP proxy if needed.
Original source copies and provenance stay separate from game-ready assets.
Requires ffmpeg/ffprobe on PATH. Never launches Unreal or touches existing SFX.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import urllib.request
import wave
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "RawAssets/ThirdParty/Epic_20261021"
MUSIC = ROOT / "RawAssets/Music"
SFX = ROOT / "RawAssets/Audio/ThirdParty"
PROXY = "http://127.0.0.1:9000"
TRACKS = [
    ("Titan", "Titan", "https://www.scottbuckley.com.au/library/wp-content/uploads/2018/06/sb_titan.mp3"),
    ("Legionnaire", "Legionnaire (Original)", "https://www.scottbuckley.com.au/wp-content/audio/sb_legionnaire.mp3"),
    ("Juggernaut", "Juggernaut", "https://www.scottbuckley.com.au/library/wp-content/uploads/2022/07/Juggernaut.mp3"),
]
KENNEY = "https://kenney.nl/media/pages/assets/fantasy-ui-borders/ab29cd0165-1701602367/kenney_fantasy-ui-borders.zip"
SFX_SELECTIONS = [
    ("TPSFX_SwordMetalHit", "WEAPSwrd_Sword Slide Cuts, Metallic, Impact CM4 2_344 Audio_Medieval Weapons Vol 2.wav", .100, 1.050, -9., -25., "Sword slide/cut and metallic impact; first isolated performance."),
    ("TPSFX_WoodenSpearHit", "WEAPBlnt_Spear And Stick Impact, Wooden MKH 2_344 Audio_Medieval Weapons Vol 2.wav", .025, .530, -9., -25., "Wooden spear/stick collision; first isolated impact."),
    ("TPSFX_ShieldClash", "WEAPArmr_Metal Shield Spin On Floor, Buckler MKH_344 Audio_Medieval Weapons Vol 2.wav", .575, 1.400, -9., -25., "Initial buckler contact excerpt, before the later long spinning/rattling performance."),
    ("TPSFX_BassDowner", "DSGNBass_Bass Drop & Downer Fast 16_344 Audio_Bass Drops & Downers.wav", .120, 2.125, -12., -26., "Short designed bass drop; trimmed leading silence, full audible ending retained with short fade."),
]

def request(url, headers=None, method=None):
    errors = []
    for proxy in (None, PROXY):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({} if proxy is None else {"http": proxy, "https": proxy}))
            req = urllib.request.Request(url, headers={"User-Agent": "CivWar-AssetAcquisition/1.0", **(headers or {})}, method=method)
            result = opener.open(req, timeout=45)
            if proxy:
                print("Proxy fallback used:", url, flush=True)
            return result
        except Exception as exc:
            errors.append(str(exc))
            print("Direct fetch failed; retrying user proxy:" if proxy is None else "Proxy fetch failed:", url, str(exc), flush=True)
    raise RuntimeError("; ".join(errors))

def fetch(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size:
        return target
    with request(url) as stream:
        data = stream.read()
    target.write_bytes(data)
    print("Downloaded", target.relative_to(ROOT), len(data), "bytes", flush=True)
    return target

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def safe_extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            path = (destination / item.filename).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise RuntimeError("Unsafe ZIP path: " + item.filename)
        z.extractall(destination)

def acquire():
    pages = [
        ("https://www.scottbuckley.com.au/library/" + key.lower() + "/", SOURCES / (key + "-source.html")) for key, _, _ in TRACKS
    ] + [
        ("https://kenney.nl/assets/fantasy-ui-borders", SOURCES / "Kenney-source.html"),
        ("https://gdc.sonniss.com/", SOURCES / "Sonniss-source.html"),
        ("https://sonniss.com/gdc-bundle-license/", SOURCES / "Sonniss-license-2026-10-21.html"),
        ("https://creativecommons.org/licenses/by/4.0/legalcode.txt", SOURCES / "CC-BY-4.0.txt"),
        (KENNEY, SOURCES / "Kenney/kenney_fantasy-ui-borders.zip"),
    ] + [(url, SOURCES / "Music" / (key + ".mp3")) for key, _, url in TRACKS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for future in [pool.submit(fetch, url, path) for url, path in pages]:
            future.result()
    safe_extract(SOURCES / "Kenney/kenney_fantasy-ui-borders.zip", SOURCES / "Kenney/FantasyUIBorders")
    print("KENNEY_READY", SOURCES / "Kenney/FantasyUIBorders", flush=True)

def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr

def ff_json(stderr):
    return json.loads(stderr[stderr.rfind("{"):stderr.rfind("}")+1])

def wav_info(path):
    with wave.open(str(path), "rb") as w:
        info = {"sample_rate": w.getframerate(), "channels": w.getnchannels(), "sample_width": w.getsampwidth(), "frames": w.getnframes(), "duration": w.getnframes()/w.getframerate()}
    info.update({"file": path.name, "sha256": sha(path), "bytes": path.stat().st_size})
    return info

def prepare_music():
    MUSIC.mkdir(parents=True, exist_ok=True)
    entries = []
    for key, title, url in TRACKS:
        source = SOURCES / "Music" / (key + ".mp3")
        target = MUSIC / ("MUS_" + key + ".wav")
        first = ff_json(run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(source), "-af", "loudnorm=I=-23:LRA=15:TP=-3:print_format=json", "-f", "null", "-"]))
        gain = ("loudnorm=I=-23:LRA=15:TP=-3:linear=true:measured_I={input_i}:measured_LRA={input_lra}:measured_TP={input_tp}:measured_thresh={input_thresh}:offset={target_offset}:print_format=json").format(**first)
        converted = ff_json(run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source), "-af", gain, "-map_metadata", "-1", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", "-fflags", "+bitexact", "-flags:a", "+bitexact", str(target)]))
        measured = ff_json(run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(target), "-af", "loudnorm=I=-23:LRA=15:TP=-3:print_format=json", "-f", "null", "-"]))
        if abs(float(measured["input_i"]) + 23) > .3 or float(measured["input_tp"]) > -2.9:
            raise RuntimeError("Music loudness out of bounds: " + key)
        entry = wav_info(target)
        entry.update({"asset": "/Game/Audio/Music/MUS_" + key, "title": title, "author": "Scott Buckley", "source_url": url, "page_url": "https://www.scottbuckley.com.au/library/" + key.lower() + "/", "source_file": str(source.relative_to(ROOT)).replace("\\", "/"), "source_sha256": sha(source), "license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/", "attribution": "'" + title + "' by Scott Buckley - released under CC-BY 4.0. www.scottbuckley.com.au", "modifications": "Decoded original MP3 to 48 kHz stereo PCM16 WAV; two-pass EBU R128 normalization to -23 LUFS / maximum -3 dBTP; original arrangement and full duration retained. Runtime crossfades music transitions; native wave loops at file boundary, not a musically seamless loop edit.", "source_loudness": first, "conversion_loudness": converted, "verified_loudness": measured})
        entries.append(entry)
        print("MUSIC_READY", target.name, round(entry["duration"], 2), "seconds", flush=True)
    (MUSIC / "manifest.json").write_text(json.dumps({"version": 1, "sample_rate": 48000, "assets": entries}, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    (SOURCES / "ATTRIBUTION.txt").write_text("\n".join(e["attribution"] + "\n" + e["page_url"] for e in entries) + "\n\nLicense: https://creativecommons.org/licenses/by/4.0/\nChanges: MP3 decoded to 48 kHz stereo PCM16; loudness normalized to -23 LUFS, max -3 dBTP. Full tracks retained.\n\nFantasy UI Borders by Kenney (CC0)\nhttps://kenney.nl/assets/fantasy-ui-borders\nLicense: https://creativecommons.org/publicdomain/zero/1.0/\nUsed: PNG/Default/Border/panel-border-000.png, copied unchanged; tinted and nine-slice scaled in the game UI. No sample image or sample font used.\n\nHistorical Weapons Vol. 2 / Bass Drops & Downers Vol. 1 by 344 Audio, provided in the Sonniss GDC 2026 bundle.\nhttps://gdc.sonniss.com/\nLicense: https://sonniss.com/gdc-bundle-license/ (v2.0 effective 2026-08-27).\nChanges: selected isolated excerpts, downmixed/resampled to 48 kHz mono PCM16, high-pass filtering, edge fades and restrained gains; bass excerpt also mixed subtly with the original CivWar civilization-up melody. Original recordings remain credited to their creator.\nFinished game use permitted; standalone/sample-library redistribution is not permitted. No AI training.\n", encoding="utf-8")

class RemoteZipFile(io.RawIOBase):
    """Seekable, bounded HTTP Range reader; never silently downloads a whole ZIP."""
    def __init__(self, url):
        self.url, self.position, self.transferred = url, 0, 0
        with request(url, {"Range": "bytes=-65536"}) as response:
            if response.status != 206:
                raise RuntimeError("Server does not support bounded HTTP Range")
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers["Content-Range"])
            self.tail_start, _, self.length = map(int, match.groups())
            self.tail = response.read(65537)
        if len(self.tail) > 65536: raise RuntimeError("Range size exceeded")
        self.transferred += len(self.tail)
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.position
    def seek(self, position, whence=0):
        self.position = position if whence == 0 else self.position + position if whence == 1 else self.length + position
        if self.position < 0: raise ValueError("Negative offset")
        return self.position
    def read(self, size=-1):
        if size < 0: size = self.length - self.position
        size = min(size, self.length - self.position)
        if size <= 0: return b""
        if size > 40 * 1024 * 1024: raise RuntimeError("Refusing large ZIP read")
        if self.position >= self.tail_start:
            data = self.tail[self.position-self.tail_start:self.position-self.tail_start+size]
        else:
            end = self.position + size - 1
            with request(self.url, {"Range": "bytes=%d-%d" % (self.position, end)}) as response:
                expected = "bytes %d-%d/%d" % (self.position, end, self.length)
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise RuntimeError("Incorrect server range response")
                data = response.read(size+1)
            if len(data) != size: raise RuntimeError("Incomplete/excess range response")
            self.transferred += len(data)
        self.position += len(data)
        return data

def index_sonniss():
    destination = SOURCES / "Sonniss"
    destination.mkdir(parents=True, exist_ok=True)
    def one(number):
        url = "https://downloads.sonniss.com/Sonniss.com-GDC2026-GameAudioBundle%dof5.zip" % number
        remote = RemoteZipFile(url)
        with zipfile.ZipFile(remote) as archive:
            entries = [{"name": item.filename, "bytes": item.file_size, "compressed_bytes": item.compress_size, "crc32": "%08x" % item.CRC} for item in archive.infolist()]
        (destination / ("archive%d-index.json" % number)).write_text(json.dumps({"url":url, "archive_bytes":remote.length, "transferred":remote.transferred, "entries":entries}, indent=2)+"\n",encoding="utf-8")
        chosen = [e for e in entries if re.search(r"sword|shield|spear|bass drop|historical|impact", e["name"], re.I)]
        print("Archive", number, "entries", len(entries), "range bytes", remote.transferred, "\n"+json.dumps(chosen,indent=2), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for future in [pool.submit(one, number) for number in (1,2)]: future.result()

def acquire_sonniss():
    index_path = SOURCES / "Sonniss/archive1-index.json"
    if not index_path.exists(): index_sonniss()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    original_dir = SOURCES / "Sonniss/originals"
    original_dir.mkdir(parents=True, exist_ok=True)
    receipts = []
    for _, filename, *_ in SFX_SELECTIONS:
        entry = next(e for e in index["entries"] if Path(e["name"]).name == filename)
        target = original_dir / filename
        transferred = 0
        if not target.exists():
            remote = RemoteZipFile(index["url"])
            with zipfile.ZipFile(remote) as archive:
                data = archive.read(entry["name"])  # zipfile checks uncompressed CRC.
            target.write_bytes(data)
            transferred = remote.transferred
        data = target.read_bytes()
        if len(data) != entry["bytes"] or "%08x" % zlib.crc32(data) != entry["crc32"]:
            raise RuntimeError("Sonniss source CRC/length mismatch: " + filename)
        receipts.append({**entry, "archive_url": index["url"], "sha256": sha(target), "local_file": str(target.relative_to(ROOT)).replace("\\", "/"), "transferred_on_this_run": transferred, "crc_verified": True})
    (SOURCES / "Sonniss/selected-sources.json").write_text(json.dumps({"license_url":"https://sonniss.com/gdc-bundle-license/", "license_version": "2.0 effective 2026-08-27", "acquisition_date":"2026-10-21", "method":"Bounded HTTP Range on official ZIP; extracted members CRC32 verified; raw audio retained only for this game's team.", "assets":receipts}, indent=2)+"\n", encoding="utf-8")
    print("SONNISS_READY", len(receipts), "CRC-verified source files", flush=True)

def prepare_sfx():
    import numpy as np
    acquire_sonniss()
    SFX.mkdir(parents=True, exist_ok=True)
    sources = json.loads((SOURCES / "Sonniss/selected-sources.json").read_text(encoding="utf-8"))["assets"]
    entries = []
    for key, filename, start, end, target_peak, target_rms, description in SFX_SELECTIONS:
        source = SOURCES / "Sonniss/originals" / filename
        target = SFX / (key + ".wav")
        decoded = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(source), "-af", "highpass=f=35", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
        audio = np.frombuffer(decoded, dtype="<f4").astype(np.float64)[round(start*48000):round(end*48000)].copy()
        # Five-millisecond attack only removes edit discontinuity. The release
        # removes the natural recording tail before the next original impact.
        attack, release = round(.005*48000), round(.080*48000)
        audio[:attack] *= np.linspace(0,1,attack)
        audio[-release:] *= np.linspace(1,0,release)
        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(audio**2)))
        gain = min(10**(target_peak/20)/peak, 10**(target_rms/20)/rms)
        pcm = np.rint(np.clip(audio*gain,-1,1)*32767).astype("<i2")
        with wave.open(str(target), "wb") as w:
            w.setparams((1,2,48000,0,"NONE","not compressed")); w.writeframes(pcm.tobytes())
        actual = pcm.astype(np.float64)/32768
        actual_peak = float(20*np.log10(np.max(np.abs(actual))))
        actual_rms = float(20*np.log10(np.sqrt(np.mean(actual**2))))
        if actual_peak > target_peak+.01 or actual_rms > target_rms+.01 or pcm[0] or pcm[-1]:
            raise RuntimeError("SFX bounds/endpoints failed: " + key)
        entry = wav_info(target)
        original = next(item for item in sources if Path(item["name"]).name == filename)
        entry.update({"asset":"/Game/Audio/ThirdParty/"+key, "description":description, "author":"344 Audio", "source_file":original["local_file"], "source_sha256":original["sha256"], "source_archive_url":original["archive_url"], "source_member":original["name"], "source_crc32":original["crc32"], "license_url":"https://sonniss.com/gdc-bundle-license/", "license_version":"2.0 effective 2026-08-27", "trim_seconds":[start,end], "gain_db":20*math.log10(gain), "peak_dbfs":actual_peak, "rms_dbfs":actual_rms, "modifications":"48 kHz mono PCM16; 35 Hz high-pass; explicit isolated excerpt; 5 ms attack and 80 ms release fades; gain capped by peak and RMS. No synthesis or generative processing."})
        entries.append(entry)
        print("SFX_READY", target.name, round(entry["duration"],3), "seconds peak", round(actual_peak,2), "RMS", round(actual_rms,2), flush=True)
    # Keep the original recognizable civilization-up melody; the downloaded
    # low-end layer peaks at only 20 percent of its peak before the final mix.
    original_cue = ROOT / "RawAssets/Audio/SFX_AgeUp.wav"
    bass_source = SFX / "TPSFX_BassDowner.wav"
    def read_pcm(path):
        with wave.open(str(path), "rb") as stream:
            if (stream.getframerate(),stream.getnchannels(),stream.getsampwidth()) != (48000,1,2):
                raise RuntimeError("Composite input format mismatch: " + str(path))
            return np.frombuffer(stream.readframes(stream.getnframes()),dtype="<i2").astype(np.float64)/32768
    cue, bass = read_pcm(original_cue), read_pcm(bass_source)
    combined = np.zeros(96000, dtype=np.float64)
    combined[:len(cue)] += cue
    bass = bass[:len(combined)].copy()
    bass[-3840:] *= np.linspace(1,0,3840)
    bass_gain = .20 * float(np.max(np.abs(cue))) / float(np.max(np.abs(bass)))
    combined[:len(bass)] += bass * bass_gain
    mix_gain = min(1.,10**(-6/20)/np.max(np.abs(combined)),10**(-22/20)/np.sqrt(np.mean(combined**2)))
    pcm = np.rint(np.clip(combined*mix_gain,-1,1)*32767).astype("<i2")
    target = SFX / "TPSFX_AgeUpEpic.wav"
    with wave.open(str(target), "wb") as stream:
        stream.setparams((1,2,48000,0,"NONE","not compressed"));stream.writeframes(pcm.tobytes())
    actual = pcm.astype(np.float64)/32768
    peak = float(20*np.log10(np.max(np.abs(actual))))
    rms = float(20*np.log10(np.sqrt(np.mean(actual**2))))
    if peak > -5.99 or rms > -21.99 or pcm[0] or pcm[-1]:
        raise RuntimeError("Composite bounds/endpoints failed")
    entry=wav_info(target)
    entry.update({"asset":"/Game/Audio/ThirdParty/TPSFX_AgeUpEpic","description":"Original melodic civilization-up cue with a subtle licensed bass-drop layer.","author":"CivWar original cue; licensed bass recording by 344 Audio","license_url":"https://sonniss.com/gdc-bundle-license/","license_version":"2.0 effective 2026-08-27","peak_dbfs":peak,"rms_dbfs":rms,"sources":[{"file":str(original_cue.relative_to(ROOT)).replace("\\","/"),"sha256":sha(original_cue),"trim_seconds":[0,len(cue)/48000],"gain":float(mix_gain)},{"file":str(bass_source.relative_to(ROOT)).replace("\\","/"),"sha256":sha(bass_source),"trim_seconds":[0,2],"gain":float(bass_gain*mix_gain),"underlying_source":next(e for e in entries if e["file"]==bass_source.name)["source_file"]}],"modifications":"Mixed original unchanged 1.9-second melodic cue into a 2.0-second container with the licensed processed bass excerpt at 20% of cue peak; bass final80ms additional fade; final mix capped at -6dBFS peak/-22dBFS RMS."})
    entries.append(entry)
    print("SFX_READY",target.name,"2.000 seconds peak",round(peak,2),"RMS",round(rms,2),flush=True)
    (SFX / "manifest.json").write_text(json.dumps({"version":1,"assets":entries},indent=2)+"\n",encoding="utf-8")

def write_provenance():
    records=[]
    for path in sorted(SOURCES.rglob("*")):
        if path.is_file() and path.name != "manifest.json" and path.suffix not in (".bin",):
            records.append({"file":str(path.relative_to(SOURCES)).replace("\\","/"),"bytes":path.stat().st_size,"sha256":sha(path)})
    (SOURCES / "manifest.json").write_text(json.dumps({"version":1,"acquired":"2026-10-21","sources":["https://www.scottbuckley.com.au/library/titan/","https://www.scottbuckley.com.au/library/legionnaire/","https://www.scottbuckley.com.au/library/juggernaut/","https://kenney.nl/assets/fantasy-ui-borders","https://gdc.sonniss.com/"],"files":records},indent=2)+"\n",encoding="utf-8")
    print("PROVENANCE_READY",len(records),"source/license records",flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["acquire", "music", "sonniss-index", "sfx", "provenance"])
    args = parser.parse_args()
    if args.command == "acquire": acquire()
    if args.command == "music": prepare_music()
    if args.command == "sonniss-index": index_sonniss()
    if args.command == "sfx": prepare_sfx()
    if args.command == "provenance": write_provenance()
