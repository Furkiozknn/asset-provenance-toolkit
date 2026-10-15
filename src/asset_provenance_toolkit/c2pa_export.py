"""Turn an aprov record into a C2PA manifest definition you can sign.

aprov records are unsigned on purpose (see the README's C2PA section). When
a file does need a Content Credential, the record already holds what the
credential should say: what made the file and how. This module writes that
as a *manifest definition*, the JSON that `c2patool` reads with ``-m`` and
that ``c2pa.Builder`` in c2pa-python (and the other Content Authenticity
Initiative SDKs) accepts, so signing is one more command with your own
certificate. No dependency is added here: the output is plain JSON.

What goes in:

- a ``c2pa.actions.v2`` assertion with one ``c2pa.created`` action whose
  ``digitalSourceType`` is the IPTC term for AI-generated media
  (``trainedAlgorithmicMedia`` by default), ``softwareAgent`` set to the
  record's provider. This is the part viewers such as Content Credentials
  Verify show as "made with AI".
- a custom assertion, ``io.github.furkiozknn.aprov.recipe``, holding the
  record itself (capability, provider, params, job id, ...), so the full
  recipe travels inside the signed manifest.
- ``claim_generator_info`` naming aprov and its version, and optionally the
  ``alg`` / ``sign_cert`` / ``private_key`` / ``ta_url`` keys c2patool reads
  from the same file.

Nothing is signed here and nothing claims to be: the signature comes from
the C2PA tool and the certificate you give it.
"""

from __future__ import annotations

from typing import Any, Optional

from .schema import Provenance

#: IPTC NewsCodes digital source types (https://cv.iptc.org/newscodes/digitalsourcetype/)
#: that describe generated media, by the short name the CLI accepts.
DIGITAL_SOURCE_TYPES: dict[str, str] = {
    "trained": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
    "composite": "http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia",
    "algorithmic": "http://cv.iptc.org/newscodes/digitalsourcetype/algorithmicMedia",
}

#: Label of the custom assertion carrying the full aprov record. C2PA
#: reserves the ``c2pa.`` prefix and expects other labels to be namespaced
#: by an entity the author controls, in reverse-domain form.
RECIPE_ASSERTION_LABEL = "io.github.furkiozknn.aprov.recipe"


def manifest_definition(
    provenance: Provenance,
    *,
    title: Optional[str] = None,
    digital_source_type: str = "trained",
    generator_version: str = "",
    signing: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """The manifest definition for ``provenance`` as a JSON-ready dict.

    ``digital_source_type`` is a key of :data:`DIGITAL_SOURCE_TYPES` or a
    full IPTC URI. ``signing`` may carry ``alg``, ``sign_cert``,
    ``private_key`` and ``ta_url``; they are copied to the top level, which
    is where c2patool looks for them (c2pa-python takes the signer
    separately and ignores them).
    """
    source_type = DIGITAL_SOURCE_TYPES.get(digital_source_type, digital_source_type)
    if not source_type.startswith("http://cv.iptc.org/newscodes/digitalsourcetype/"):
        raise ValueError(
            f"digital source type must be one of {', '.join(DIGITAL_SOURCE_TYPES)} "
            f"or an IPTC digitalsourcetype URI, got {digital_source_type!r}"
        )

    created: dict[str, Any] = {
        "action": "c2pa.created",
        "softwareAgent": provenance.provider,
        "digitalSourceType": source_type,
    }
    if provenance.created_at:
        created["when"] = provenance.created_at

    generator: dict[str, str] = {"name": "aprov (asset-provenance-toolkit)"}
    if generator_version:
        generator["version"] = generator_version

    definition: dict[str, Any] = {}
    for key in ("alg", "sign_cert", "private_key", "ta_url"):
        if signing and signing.get(key):
            definition[key] = signing[key]
    definition["claim_generator_info"] = [generator]
    if title:
        definition["title"] = title
    definition["assertions"] = [
        {"label": "c2pa.actions.v2", "data": {"actions": [created]}},
        {"label": RECIPE_ASSERTION_LABEL, "data": provenance.to_dict()},
    ]
    return definition
