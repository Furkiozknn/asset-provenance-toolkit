# asset-provenance-toolkit

Embed and extract generation provenance — capability, provider, params, job id — directly in the files an AI pipeline produces, so the record travels with the asset instead of living only in a database row. A provider-agnostic generalization of the classic "drag the PNG back into the UI to see its generation parameters" pattern (AUTOMATIC1111, ComfyUI), applicable to any file and any generation backend.

Part of the same small ecosystem as [`ai-job-gateway`](https://github.com/Furkiozknn/ai-job-gateway), [`prompt-template-manager`](https://github.com/Furkiozknn/prompt-template-manager), and [`model-comparison-harness`](https://github.com/Furkiozknn/model-comparison-harness) — coupled only through documented HTTP contracts, never through a shared Python dependency (see [ADR-006](https://github.com/Furkiozknn/Furkiozknn/blob/claude/ai-creative-platform-research-fwh2vt/research/lab/DECISIONS.md)).

## Why

A generated image or video is only as reproducible as the metadata that survives alongside it. Once a file leaves the system that made it — downloaded, shared, archived — there's usually no way to know what produced it: which model, which provider, which parameters, which prompt. `ai-job-gateway`'s job records answer that question, but only for as long as the job hasn't expired out of the store (`result_expires_at`, see ADR-005). This tool makes provenance an attribute of the *file itself*, so it survives independently of any database or job store's retention window.

## What it does

- **Embed** a `Provenance` record (capability, provider, params, optional job id / source URL / result / arbitrary `extra` fields) into a file.
- **Extract** it back out, as JSON.
- **Verify** whether a file has provenance, with a scriptable exit code (or `--json` for machine-readable output).
- **Strip** it, when you want to publish a file without its generation history attached.
- **`from-job`**: fetch a finished job directly from a running `ai-job-gateway`-compatible server and embed its record in one step.

## Quickstart

```bash
uv sync --group dev

uv run aprov embed cat.png --capability image-generate --provider flux-2 \
    --params '{"prompt": "a red sneaker on a white background", "seed": 42}'
# embedded provenance into cat.png (png backend)

uv run aprov extract cat.png --compact
# {"capability":"image-generate","created_at":"2026-09-02T12:00:00+00:00", ...}

uv run aprov verify cat.png
# OK: cat.png has provenance (capability='image-generate', provider='flux-2', ...)
```

`cat.png` now carries its own generation history. Copy it, rename it, send it to someone else — `aprov extract cat.png` still works, with no database or job id lookup involved.

## Backends

| File type | Backend | How |
|---|---|---|
| `.png` | native | An `ai-provenance` chunk via Pillow — `tEXt` normally, `zTXt` (zlib-compressed, the same tradeoff ComfyUI makes for its embedded workflow JSON) once the record passes ~2 KB. Other text chunks are preserved, and the image is re-saved without touching pixel data (`img.copy()` after `img.load()`) — genuinely lossless. |
| `.jpg` / `.jpeg` | native | A private APP1 marker segment (tagged `AIPROV1\0`, distinct from EXIF's `Exif\0\0` or XMP's URI tag so it can never collide with either) spliced directly into the file's marker structure. Unlike the PNG backend, this never decodes or re-encodes the image — JPEG recompression is lossy, so this backend edits container bytes only, leaving every other byte (including all scan/pixel data) untouched. Capped at ~64 KB of provenance JSON per file, since a single marker segment's length field is 2 bytes; `embed` raises a clear error rather than silently truncating if a record is that large. |
| anything else | sidecar | A `<file>.provenance.json` file next to the asset. |

`extract()` always checks the sidecar as a fallback, even for PNG/JPEG — a sidecar can legitimately exist next to an image whose embedded record was stripped by some other tool along the way.

An MP4/QuickTime atom backend is a natural next step, deliberately left for later — video container formats are involved enough to deserve their own pass rather than being squeezed in alongside this one.

## Relationship to C2PA / Content Credentials

[C2PA](https://c2pa.org/) ("Content Credentials") is the industry standard for *cryptographically signed, tamper-evident* provenance: a manifest is bound to the asset's content hash and signed with an X.509 certificate, so a viewer can verify the credential wasn't altered and trace it to a specific signing identity, and browsers/platforms are increasingly built to surface that signature. This toolkit deliberately does **not** implement any of that. Signing requires certificate issuance and a trust model — a genuinely different, heavier product than a CLI a solo pipeline drops into its output step — and claiming C2PA compatibility without one would be actively misleading.

What this toolkit gives you is the same *idea* a C2PA assertion captures (what tool, what parameters, what job produced this asset) in the same *place* (inside or next to the file), with none of the same *guarantees*: no signature, no content-hash binding, no tamper detection, no revocation. Think of an `ai-provenance` record as a structural cousin of one C2PA assertion, not a substitute for a C2PA manifest. If a project genuinely needs verifiable, hard-to-forge authenticity claims — for publication, moderation, or legal purposes — reach for a real C2PA SDK. Use this toolkit for the far more common internal case: "I want to know what I ran to produce this file, six weeks from now, without a database lookup."

## CLI usage

```bash
# Embed provenance manually
aprov embed output.png --capability image-generate --provider flux-2 \
    --params '{"prompt": "a red sneaker on a white background", "seed": 42}' \
    --extra '{"steps": 30, "cfg_scale": 7.5}'

# Dispatch is by extension - this works exactly the same way on a JPEG
aprov embed output.jpg --capability image-generate --provider flux-2 \
    --params '{"prompt": "a red sneaker"}'

# Extract it back out
aprov extract output.png
# {
#   "capability": "image-generate",
#   ...
# }

# Check whether a file has provenance (exit 0/1, scriptable)
aprov verify output.png
aprov verify output.png --json   # {"ok": true, "file": "output.png", "provenance": {...}}

# Remove it before publishing/sharing
aprov strip output.png

# Fetch a finished job from a running ai-job-gateway server and embed it in one step
aprov from-job output.png --gateway-url http://localhost:8000 --job-id <job-id>
```

## Library usage

```python
from asset_provenance_toolkit import Provenance, embed, extract, strip

provenance = Provenance(
    capability="image-generate",
    provider="flux-2",
    params={"prompt": "a red sneaker", "seed": 42},
)
embed("output.png", provenance)   # also works unchanged for "output.jpg"

found = extract("output.png")
assert found.provider == "flux-2"

strip("output.png")
```

## The provenance schema

A small, deliberately stable JSON shape (`schema_version: 1`) — this is data meant to remain readable years after it was written, long after any job record it references has expired out of a gateway's store:

```json
{
  "schema_version": 1,
  "capability": "image-generate",
  "provider": "flux-2",
  "params": {"prompt": "a red sneaker", "seed": 42},
  "job_id": "job-abc123",
  "source": "ai-job-gateway",
  "source_url": "http://localhost:8000",
  "created_at": "2026-08-31T12:00:00+00:00",
  "result": {"...": "..."},
  "extra": {}
}
```

Add new fields through `extra`, not by changing what an old file already has embedded — a v1 reader must always be able to parse a v1 record; a record from a newer schema version is rejected with a clear error rather than silently misread.

## Testing

```bash
uv run pytest -v
```

## What this tool does NOT do

- **It is not a cryptographic authenticity claim.** Unlike C2PA/Content Credentials, nothing this tool writes is signed, hashed against the pixel data, or otherwise tamper-evident. Anyone with file access — including the exact commands this CLI ships — can edit, forge, or strip a provenance record as easily as they could edit any other metadata. Treat an `ai-provenance` record as a note to your future self and teammates, not as proof of origin for a third party.
- **It does not poll or wait.** `from-job` requires the job to already be in `ready` status on the gateway; it makes one GET request and fails cleanly otherwise.
- **It does not batch.** Each CLI invocation operates on one file; wrap it in a shell loop for a directory of outputs.
- **It has no native video backend.** MP4/QuickTime/WebM all fall back to the sidecar today.
- **The JPEG backend is a private marker, not real EXIF/XMP.** A generic EXIF viewer or `exiftool` won't surface an `ai-provenance` record embedded via this tool's JPEG backend — only `aprov extract` (or the sidecar, if present) will. This was a deliberate simplicity/dependency tradeoff, not an oversight: writing genuine, spec-compliant EXIF without a recompression pass is materially more work than the private-marker approach, for a tool whose primary reader is itself.

## License

MIT
