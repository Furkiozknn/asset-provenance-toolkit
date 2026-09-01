"""Command-line entry point: `aprov embed|extract|verify|strip|from-job`."""

from __future__ import annotations

import argparse
import json
import sys

from .core import embed, extract, strip
from .gateway_client import JobFetchError, fetch_job_record
from .schema import Provenance, ProvenanceError


def _cmd_embed(args: argparse.Namespace) -> None:
    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as exc:
        print(f"error: --params must be valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(params, dict):
        print("error: --params must be a JSON object", file=sys.stderr)
        raise SystemExit(1)

    provenance = Provenance(
        capability=args.capability,
        provider=args.provider,
        params=params,
        job_id=args.job_id,
        source=args.source,
        source_url=args.source_url,
    )
    try:
        backend = embed(args.file, provenance)
    except (FileNotFoundError, ProvenanceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"embedded provenance into {args.file} ({backend} backend)")


def _cmd_extract(args: argparse.Namespace) -> None:
    try:
        provenance = extract(args.file)
    except (FileNotFoundError, ProvenanceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if provenance is None:
        print(f"no provenance found for {args.file}", file=sys.stderr)
        raise SystemExit(1)
    print(provenance.to_json(pretty=not args.compact))


def _cmd_verify(args: argparse.Namespace) -> None:
    try:
        provenance = extract(args.file)
    except (FileNotFoundError, ProvenanceError) as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1)
    if provenance is None:
        print(f"FAIL: no provenance found for {args.file}")
        raise SystemExit(1)
    print(
        f"OK: {args.file} has provenance "
        f"(capability={provenance.capability!r}, provider={provenance.provider!r}, "
        f"source={provenance.source!r}, created_at={provenance.created_at})"
    )


def _cmd_strip(args: argparse.Namespace) -> None:
    try:
        removed = strip(args.file)
    except (FileNotFoundError, ProvenanceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if removed:
        print(f"removed provenance from {args.file}")
    else:
        print(f"no provenance found on {args.file} (nothing to remove)")


def _cmd_from_job(args: argparse.Namespace) -> None:
    try:
        record = fetch_job_record(args.gateway_url, args.job_id)
    except JobFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    status = record.get("status")
    if status != "ready":
        print(f"error: job {args.job_id} is not ready (status={status!r})", file=sys.stderr)
        raise SystemExit(1)

    missing = [k for k in ("capability", "provider", "params", "id") if k not in record]
    if missing:
        print(f"error: job record is missing expected field(s): {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)

    provenance = Provenance(
        capability=record["capability"],
        provider=record["provider"],
        params=record["params"],
        job_id=record["id"],
        source="ai-job-gateway",
        source_url=args.gateway_url,
        created_at=record.get("created_at"),
        result=record.get("result"),
    )
    try:
        backend = embed(args.file, provenance)
    except (FileNotFoundError, ProvenanceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"embedded provenance from job {args.job_id} into {args.file} ({backend} backend)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="aprov", description="asset-provenance-toolkit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    embed_parser = subparsers.add_parser("embed", help="embed provenance into a file")
    embed_parser.add_argument("file")
    embed_parser.add_argument("--capability", required=True)
    embed_parser.add_argument("--provider", required=True)
    embed_parser.add_argument("--params", default="{}", help="JSON object, e.g. '{\"prompt\": \"a cat\"}'")
    embed_parser.add_argument("--job-id", default=None)
    embed_parser.add_argument("--source", default="manual")
    embed_parser.add_argument("--source-url", default=None)
    embed_parser.set_defaults(func=_cmd_embed)

    extract_parser = subparsers.add_parser("extract", help="print a file's embedded provenance as JSON")
    extract_parser.add_argument("file")
    extract_parser.add_argument("--compact", action="store_true", help="single-line JSON instead of pretty-printed")
    extract_parser.set_defaults(func=_cmd_extract)

    verify_parser = subparsers.add_parser("verify", help="check whether a file has provenance (exit 0/1)")
    verify_parser.add_argument("file")
    verify_parser.set_defaults(func=_cmd_verify)

    strip_parser = subparsers.add_parser("strip", help="remove provenance from a file")
    strip_parser.add_argument("file")
    strip_parser.set_defaults(func=_cmd_strip)

    from_job_parser = subparsers.add_parser(
        "from-job", help="fetch a finished job from an ai-job-gateway server and embed its provenance"
    )
    from_job_parser.add_argument("file")
    from_job_parser.add_argument("--gateway-url", required=True)
    from_job_parser.add_argument("--job-id", required=True)
    from_job_parser.set_defaults(func=_cmd_from_job)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
