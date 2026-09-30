"""Command-line entry point: `aprov embed|extract|verify|strip|from-job`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import embed, extract, strip
from .gateway_client import JobFetchError, fetch_job_record
from .schema import Provenance, ProvenanceError
from .sidecar_backend import sidecar_path

_DESCRIPTION = """\
Write which model, provider and parameters made a file into the file itself
(PNG, JPEG, MP4/MOV) or into a <file>.provenance.json beside it (everything
else), and read it back later - no database in the loop.

The record is a note to your future self, not proof of origin: it is not
signed and anyone with file access can edit or strip it (see C2PA for that).
"""

_EPILOG = """\
examples:
  aprov embed cat.png --capability image-generate --provider flux-2 \\
       --params '{"prompt": "a red sneaker", "seed": 42}'
  aprov extract cat.png
  aprov verify cat.png && echo "has a record"

exit codes:
  0  done (embed, strip) or the record was found (extract, verify)
  1  no record, unreadable file, bad JSON, or the gateway could not be reached
  2  wrong command line (missing argument, unknown option)
"""


class _Parser(argparse.ArgumentParser):
    """argparse with a hint line after a usage error. The exit code stays 2."""

    def __init__(self, *args, hint: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._hint = hint

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        if self._hint:
            print(f"hint: {self._hint}", file=sys.stderr)
        raise SystemExit(2)


def _non_empty(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return value


def _describe(file: str, exc: Exception) -> str:
    """Words for an OSError. A read-only file used to surface as a raw
    `[WinError 5] ... '...\\.name.xxxx.aprov-tmp' -> '...\\name'`."""
    if isinstance(exc, PermissionError):
        return f"{file}: permission denied - is it read-only or open in another program? ({exc.strerror})"
    return str(exc)


def _parse_json_object(raw: str, *, flag: str) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        print(f"error: {flag} must be valid JSON: {exc}", file=sys.stderr)
        print(f"hint: quote it, e.g. {flag} '{{\"key\": \"value\"}}'", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(value, dict):
        print(f"error: {flag} must be a JSON object", file=sys.stderr)
        raise SystemExit(1)
    return value


def _cmd_embed(args: argparse.Namespace) -> None:
    params = _parse_json_object(args.params, flag="--params")
    extra = _parse_json_object(args.extra, flag="--extra")

    provenance = Provenance(
        capability=args.capability,
        provider=args.provider,
        params=params,
        job_id=args.job_id,
        source=args.source,
        source_url=args.source_url,
        extra=extra,
    )
    try:
        backend = embed(args.file, provenance)
    except (OSError, ProvenanceError) as exc:
        print(f"error: {_describe(args.file, exc)}", file=sys.stderr)
        raise SystemExit(1)
    where = f"{backend} backend: {sidecar_path(args.file)}" if backend == "sidecar" else f"{backend} backend"
    print(f"embedded provenance into {args.file} ({where})")


def _cmd_extract(args: argparse.Namespace) -> None:
    try:
        provenance = extract(args.file)
    except (OSError, ProvenanceError) as exc:
        print(f"error: {_describe(args.file, exc)}", file=sys.stderr)
        raise SystemExit(1)
    if provenance is None:
        print(f"no provenance found for {args.file}", file=sys.stderr)
        raise SystemExit(1)
    print(provenance.to_json(pretty=not args.compact))


def _cmd_verify(args: argparse.Namespace) -> None:
    try:
        provenance = extract(args.file)
    except (OSError, ProvenanceError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "file": args.file, "error": _describe(args.file, exc)}))
        else:
            print(f"FAIL: {_describe(args.file, exc)}")
        raise SystemExit(1)
    if provenance is None:
        if args.json:
            print(json.dumps({"ok": False, "file": args.file, "error": "no provenance found"}))
        else:
            print(f"FAIL: no provenance found for {args.file}")
        raise SystemExit(1)
    if args.json:
        print(json.dumps({"ok": True, "file": args.file, "provenance": provenance.to_dict()}))
        return
    print(
        f"OK: {args.file} has provenance "
        f"(capability={provenance.capability!r}, provider={provenance.provider!r}, "
        f"source={provenance.source!r}, created_at={provenance.created_at})"
    )


def _cmd_strip(args: argparse.Namespace) -> None:
    try:
        removed = strip(args.file)
    except (OSError, ProvenanceError) as exc:
        print(f"error: {_describe(args.file, exc)}", file=sys.stderr)
        raise SystemExit(1)
    if removed:
        print(f"removed provenance from {args.file}")
    else:
        print(f"no provenance found on {args.file} (nothing to remove)")


def _cmd_from_job(args: argparse.Namespace) -> None:
    if not args.gateway_url.startswith(("http://", "https://")):
        print(
            f"error: --gateway-url must start with http:// or https:// (got {args.gateway_url!r})",
            file=sys.stderr,
        )
        raise SystemExit(1)
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

    try:
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
    except ProvenanceError as exc:
        print(f"error: job record from {args.gateway_url} has an unexpected shape: {exc}", file=sys.stderr)
        raise SystemExit(1)
    try:
        backend = embed(args.file, provenance)
    except (OSError, ProvenanceError) as exc:
        print(f"error: {_describe(args.file, exc)}", file=sys.stderr)
        raise SystemExit(1)
    print(f"embedded provenance from job {args.job_id} into {args.file} ({backend} backend)")


def main() -> None:
    raw = argparse.RawDescriptionHelpFormatter
    parser = _Parser(
        prog="aprov",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=raw,
        hint="'aprov embed --help' shows a full example; 'aprov --help' lists every command",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="{embed,extract,verify,strip,from-job}"
    )

    embed_parser = subparsers.add_parser(
        "embed",
        help="write a provenance record into a file",
        description="Write a provenance record into FILE: inside it for PNG, JPEG and MP4/MOV,\n"
        "in FILE.provenance.json beside it for anything else.\n"
        "Embedding again replaces the record.\n",
        epilog="example:\n"
        "  aprov embed cat.png --capability image-generate --provider flux-2 \\\n"
        "       --params '{\"prompt\": \"a red sneaker\", \"seed\": 42}'\n",
        formatter_class=raw,
        hint="a file plus two required options: "
        "aprov embed cat.png --capability image-generate --provider flux-2",
    )
    embed_parser.add_argument("file", help="the PNG, JPEG, MP4/MOV or other file to annotate")
    embed_parser.add_argument(
        "--capability", required=True, type=_non_empty, help="what was generated, e.g. image-generate"
    )
    embed_parser.add_argument("--provider", required=True, type=_non_empty, help="the model or service, e.g. flux-2")
    embed_parser.add_argument("--params", default="{}", help="JSON object, e.g. '{\"prompt\": \"a cat\"}'")
    embed_parser.add_argument("--job-id", default=None, help="id of the job that produced the file")
    embed_parser.add_argument("--source", default="manual", help="where the record came from (default: manual)")
    embed_parser.add_argument("--source-url", default=None, help="URL of the system that produced the file")
    embed_parser.add_argument(
        "--extra", default="{}", help="JSON object of additional fields, e.g. '{\"seed\": 42}'"
    )
    embed_parser.set_defaults(func=_cmd_embed)

    extract_parser = subparsers.add_parser(
        "extract",
        help="print a file's record as JSON",
        description="Print FILE's provenance record as JSON. Exit 1 if there is none.",
        epilog="example:\n  aprov extract cat.png --compact\n",
        formatter_class=raw,
        hint="a file: aprov extract cat.png",
    )
    extract_parser.add_argument("file", help="the file to read")
    extract_parser.add_argument("--compact", action="store_true", help="single-line JSON instead of pretty-printed")
    extract_parser.set_defaults(func=_cmd_extract)

    verify_parser = subparsers.add_parser(
        "verify",
        help="check whether a file has a record (exit 0 or 1)",
        description="Exit 0 if FILE has a readable provenance record, 1 if not.\n"
        "Checks presence and shape only - the record is not signed,\n"
        "so this is not proof of origin.\n",
        epilog="example:\n  aprov verify cat.png --json\n",
        formatter_class=raw,
        hint="a file: aprov verify cat.png",
    )
    verify_parser.add_argument("file", help="the file to check")
    verify_parser.add_argument("--json", action="store_true", help="machine-readable JSON instead of text")
    verify_parser.set_defaults(func=_cmd_verify)

    strip_parser = subparsers.add_parser(
        "strip",
        help="remove the record from a file",
        description="Remove the provenance record (and the .provenance.json sidecar, if any)\n"
        "so the file can be shared without its generation history.\n",
        epilog="example:\n  aprov strip cat.png\n",
        formatter_class=raw,
        hint="a file: aprov strip cat.png",
    )
    strip_parser.add_argument("file", help="the file to clean")
    strip_parser.set_defaults(func=_cmd_strip)

    from_job_parser = subparsers.add_parser(
        "from-job",
        help="embed a finished ai-job-gateway job's record",
        description="Fetch one finished job (one GET, no waiting) from an ai-job-gateway\n"
        "server and embed its capability, provider, params and result into FILE.\n",
        epilog="example:\n  aprov from-job out.png --gateway-url http://localhost:8000 --job-id job-abc123\n",
        formatter_class=raw,
        hint="aprov from-job out.png --gateway-url http://localhost:8000 --job-id <id>",
    )
    from_job_parser.add_argument("file", help="the file the job produced")
    from_job_parser.add_argument("--gateway-url", required=True, help="base URL, including http:// or https://")
    from_job_parser.add_argument("--job-id", required=True, help="id of a job whose status is ready")
    from_job_parser.set_defaults(func=_cmd_from_job)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
