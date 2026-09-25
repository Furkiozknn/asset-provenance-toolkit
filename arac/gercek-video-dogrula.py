#!/usr/bin/env python3
"""Check the MP4 backend against real encoded media, not a fixture.

    python3 arac/gercek-video-dogrula.py

`tests/test_mp4_backend.py` builds its own ISO base media files by hand.
That is the right way to test the *mechanism* - the chunk offset in `stco`
is a value the test chose, so the test can assert on it - but a hand-built
file is not the thing this tool will actually be pointed at. A real encoder
produces layouts a fixture does not: `moov` before or after `mdat`, `free`
padding, `edts`, a second track, `avcC` inside `stsd`.

So this script asks a decoder instead of a parser. For each clip it takes
the sha256 of the **decoded** output, embeds a record, and takes it again.
Structure is not the claim; frame data is. If a single byte of media moved,
the second hash differs - or ffmpeg refuses the file outright.

It ends with the negative control, because a check that only ever passes
proves nothing: the same record is spliced in near the front of the file,
the way the JPEG backend legitimately splices its segment, and the decode
must come out *wrong*. If that ever starts passing, this script has stopped
measuring anything.

Exit codes: 0 all checks passed, 1 a check failed, 2 ffmpeg not available.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from asset_provenance_toolkit import Provenance, embed, extract, strip  # noqa: E402
from asset_provenance_toolkit.mp4_backend import _our_box  # noqa: E402
from asset_provenance_toolkit.schema import ProvenanceError  # noqa: E402

RECORD = Provenance(
    capability="video-generate",
    provider="mock-video",
    params={"prompt": "a red sneaker rotating", "seed": 42},
    job_id="job-real-0001",
)

#: (filename, ffmpeg args, decode format). Between them these cover both
#: box layouts an encoder produces, an audio-only ISO base media file, and a
#: QuickTime `.mov`.
CLIPS = [
    ("kamera.mp4", ["-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p"], "rawvideo"),
    ("faststart.mp4", ["-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=2",
                       "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                       "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
                       "-movflags", "+faststart"], "rawvideo"),
    ("eski.mov", ["-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=2",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p"], "rawvideo"),
    ("ses.m4a", ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac"], "s16le"),
]

hata = 0


def sorun(mesaj: str) -> None:
    global hata
    hata += 1
    print("HATA  " + mesaj)


def tamam(mesaj: str) -> None:
    print("ok    " + mesaj)


def coz(path: Path, fmt: str) -> tuple[int, str]:
    """sha256 of the decoded stream - what a player would actually get."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", fmt, "-"],
        capture_output=True,
    )
    return r.returncode, hashlib.sha256(r.stdout).hexdigest()


def akislar(path: Path) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return "<ffprobe failed>"
    data = json.loads(r.stdout)
    # Drop fields that legitimately move with file size rather than content.
    for s in data.get("streams", []):
        for k in ("bit_rate", "start_time", "start_pts"):
            s.pop(k, None)
    return json.dumps(data, sort_keys=True)


def bir_klip(tmpdir: Path, name: str, args: list[str], fmt: str) -> None:
    path = tmpdir / name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(path)], check=True)
    original = path.read_bytes()
    rc_before, hash_before = coz(path, fmt)
    streams_before = akislar(path)
    if rc_before != 0:
        sorun(f"{name}: ffmpeg could not decode the file we just produced")
        return

    backend = embed(path, RECORD)
    if backend != "mp4":
        sorun(f"{name}: routed to the {backend!r} backend, expected 'mp4'")
        return

    if extract(path) != RECORD:
        sorun(f"{name}: the record did not survive the round trip")

    rc_after, hash_after = coz(path, fmt)
    if rc_after != 0:
        sorun(f"{name}: ffmpeg refuses the file after embed")
    elif hash_after != hash_before:
        sorun(f"{name}: decoded output changed - media data moved")
    else:
        tamam(f"{name}: decoded output byte-identical after embed ({backend} backend)")

    if akislar(path) != streams_before:
        sorun(f"{name}: ffprobe reports different streams after embed")

    if not strip(path):
        sorun(f"{name}: strip reported nothing to remove")
    elif path.read_bytes() != original:
        sorun(f"{name}: strip did not restore the original bytes")
    else:
        tamam(f"{name}: strip restores the file byte for byte")


def main() -> int:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("ffmpeg/ffprobe not on PATH - this script checks against real")
        print("encoded media, so there is nothing it can do without them.")
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for name, args, fmt in CLIPS:
            try:
                bir_klip(tmpdir, name, args, fmt)
            except ProvenanceError as exc:
                # A refusal is a legitimate result from this library, but not
                # here: these are files it just wrote itself. Report it as the
                # failure it is and keep going, so one bad clip does not hide
                # the state of the others.
                sorun(f"{name}: the toolkit refused its own file: {exc}")

        # --- negative control -------------------------------------------
        name, args, fmt = CLIPS[0]
        path = tmpdir / "kontrol.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(path)], check=True)
        original = path.read_bytes()
        rc_before, hash_before = coz(path, fmt)
        ftyp_end = int.from_bytes(original[:4], "big")
        path.write_bytes(original[:ftyp_end] + _our_box(RECORD) + original[ftyp_end:])
        rc_after, hash_after = coz(path, fmt)
        if rc_after == 0 and hash_after == hash_before:
            sorun(
                "negative control: splicing a box in before mdat did NOT damage the file. "
                "Either this ffmpeg repairs broken chunk offsets, or these checks have "
                "stopped measuring anything - do not trust the passes above."
            )
        else:
            tamam("negative control: the same splice before mdat does break the decode")

    print()
    print(f"{hata} sorun" if hata else "gercek medya uzerinde her sey tutuyor")
    return 1 if hata else 0


if __name__ == "__main__":
    raise SystemExit(main())
