# asset-provenance-toolkit

Embed and extract generation provenance — capability, provider, params, job id — directly in the files an AI pipeline produces. A provider-agnostic generalization of the classic "drag the PNG back into the UI to see its generation parameters" pattern (AUTOMATIC1111 and friends), applicable to any file and any generation backend.

Part of the same small ecosystem as [`ai-job-gateway`](https://github.com/Furkiozknn/ai-job-gateway), [`prompt-template-manager`](https://github.com/Furkiozknn/prompt-template-manager), and [`model-comparison-harness`](https://github.com/Furkiozknn/model-comparison-harness) — coupled only through documented HTTP contracts, never through a shared Python dependency (see [ADR-006](https://github.com/Furkiozknn/Furkiozknn/blob/claude/ai-creative-platform-research-fwh2vt/research/lab/DECISIONS.md)).

## Why

A generated image or video is only as reproducible as the metadata that survives alongside it. Once a file leaves the system that made it — downloaded, shared, archived — there's usually no way to know what produced it: which model, which provider, which parameters, which prompt. `ai-job-gateway`'s job records answer that question, but only for as long as the job hasn't expired out of the store (`result_expires_at`, see ADR-005). This tool makes provenance an attribute of the *file itself*, so it survives independently of any database or job store's retention window.

## What it does

- **Embed** a `Provenance` record (capability, provider, params, optional job id / source URL / result) into a file.
- **Extract** it back out, as JSON.
- **Verify** whether a file has provenance, with a scriptable exit code.
- **Strip** it, when you want to publish a file without its generation history attached.
- **`from-job`**: fetch a finished job directly from a running `ai-job-gateway`-compatible server and embed its record in one step.

## Backends

| File type | Backend | How |
|---|---|---|
| `.png` | native | A `tEXt` chunk (`ai-provenance`) via Pillow — other `tEXt` chunks are preserved, and the image is re-saved without recompression artifacts (`img.copy()` after `img.load()`). |
| anything else | sidecar | A `<file>.provenance.json` file next to the asset. |

`extract()` always checks the sidecar as a fallback, even for PNGs — a sidecar can legitimately exist next to a PNG whose embedded chunk was stripped by some other tool along the way.

More native backends (JPEG/EXIF, MP4/QuickTime atoms) are natural next steps, deliberately out of scope for v1 to keep the initial surface to one well-understood format plus the universal sidecar fallback.

## Install

```bash
uv sync --group dev
```

## CLI usage

```bash
# Embed provenance manually
aprov embed output.png --capability image-generate --provider flux-2 \
    --params '{"prompt": "a red sneaker on a white background", "seed": 42}'

# Extract it back out
aprov extract output.png
# {
#   "capability": "image-generate",
#   ...
# }

# Check whether a file has provenance (exit 0/1, scriptable)
aprov verify output.png

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
embed("output.png", provenance)

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

## Roadmap / known v1 limitations

- Only PNG has a native backend; every other format falls back to a sidecar file.
- `from-job` requires the job to already be in `ready` status — it does not poll or wait.
- No signature/tamper-detection on embedded or sidecar provenance — this tool records provenance, it does not authenticate it. Anyone with file access can edit or forge a provenance record the same way they could edit any other metadata.

## License

MIT
