# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).
The version is the one in `pyproject.toml`; a release is the git tag `v<version>` on the commit that carries it.

## [0.1.0] - 2026-09-25

First release. Prepared for PyPI; not yet tagged or published.

### Added
- `aprov embed | extract | verify | strip | from-job`, and the same operations as a library (`embed`, `extract`, `strip`, `Provenance`).
- PNG backend: an `ai-provenance` `tEXt`/`zTXt`/`iTXt` chunk spliced in before `IEND`, without decoding the image.
- JPEG backend: a private `AIPROV1` APP1 segment spliced into the marker structure, never re-encoding.
- MP4/M4V/M4A/MOV backend: a `uuid` box appended after the media data so the absolute chunk offsets in `moov` stay valid; edits that would move media data are refused. Checked against `ffmpeg`-encoded clips by comparing decoded output (`arac/gercek-video-dogrula.py`).
- Sidecar `<file>.provenance.json` for every other file type.
- Trusted Publishing workflow (`yayinla.yml`).
- `aprov --version`.
- CI builds the sdist and wheel, runs `twine check`, and installs the wheel into a clean venv to run `aprov` from it.

### Hardened before the first release
- JPEG, MP4 and sidecar writes now go through the same atomic temp-file-and-rename path as PNG, so an interrupted write can no longer leave a truncated asset. The temp file has a random name (`mkstemp`), the original's permission bits are kept, and a symlink is written through rather than replaced.
- The MP4 backend streams the file instead of loading it whole: embedding into or reading a multi-GB video no longer needs that much memory. `extract` refuses a record box declaring more than 16 MiB.
- Corrupt or wrongly shaped records (bytes that are not UTF-8, `extra` that is not an object, `params` that is not an object, ...) are a `ProvenanceError`, and the CLI reports them as `error: ...`; `verify --json` prints JSON for them instead of a traceback.
- `from-job`: an unreachable gateway, a timeout or a non-text body is a clean `error: could not fetch job ...`; the job id is URL-encoded as one path segment.
- The CLI reports OS errors (a directory, a permission problem) as `error: ...`.
- `Provenance(...)` raises `ProvenanceError` for a field of a type the reader would reject (`params=[...]`, `capability=7`). `result` stays unchecked, so existing files remain readable.
