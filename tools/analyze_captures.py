#!/usr/bin/env python3
"""Analyze iRobot API captures from MITM proxy sessions.

Usage:
    python tools/analyze_captures.py captures/*.jsonl
    python tools/analyze_captures.py captures/*.jsonl --update-docs
    python tools/analyze_captures.py --help
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Same BLID normalization as the MITM addon
BLID_RE = re.compile(r"/[A-F0-9]{12,32}(?=/|$)", re.IGNORECASE)

# ANSI
_RST = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"


def normalize_path(path: str) -> str:
    """Replace BLIDs and UUIDs in paths with placeholders."""
    path = BLID_RE.sub("/<BLID>", path)
    # Strip query string for grouping
    return path.split("?")[0]


def infer_schema(obj, _depth: int = 0) -> dict | str | list:
    """Infer a type skeleton from a JSON value.

    Returns a structure like:
        {"state": {"cycle": "string", "phase": "string"}, "id": "number"}
    """
    if _depth > 10:
        return "..."
    if isinstance(obj, dict):
        return {k: infer_schema(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        if not obj:
            return ["empty"]
        # Infer from first element
        return [infer_schema(obj[0], _depth + 1)]
    if isinstance(obj, bool):
        return "boolean"
    if isinstance(obj, int):
        return "integer"
    if isinstance(obj, float):
        return "number"
    if isinstance(obj, str):
        if obj == "[REDACTED]":
            return "string (redacted)"
        return "string"
    if obj is None:
        return "null"
    return str(type(obj).__name__)


def merge_schemas(a, b):
    """Merge two inferred schemas, producing the union of all keys."""
    if isinstance(a, dict) and isinstance(b, dict):
        merged = dict(a)
        for k, v in b.items():
            if k in merged:
                merged[k] = merge_schemas(merged[k], v)
            else:
                merged[k] = v
        return merged
    if isinstance(a, list) and isinstance(b, list):
        if not a:
            return b
        if not b:
            return a
        return [merge_schemas(a[0], b[0])]
    # If types differ, note it
    if a != b:
        a_str = str(a) if not isinstance(a, str) else a
        b_str = str(b) if not isinstance(b, str) else b
        types = set(a_str.split(" | ")) | set(b_str.split(" | "))
        return " | ".join(sorted(types))
    return a


def format_schema(schema, indent: int = 0) -> str:
    """Pretty-print an inferred schema."""
    pad = "  " * indent
    if isinstance(schema, dict):
        if not schema:
            return "{}"
        lines = ["{"]
        for k, v in schema.items():
            val = format_schema(v, indent + 1)
            lines.append(f"{pad}  {k}: {val}")
        lines.append(f"{pad}}}")
        return "\n".join(lines)
    if isinstance(schema, list):
        if not schema:
            return "[]"
        inner = format_schema(schema[0], indent + 1)
        return f"[{inner}]"
    return str(schema)


def load_captures(paths: list[str]) -> list[dict]:
    """Load all JSONL capture files."""
    records = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"  Warning: {p} not found, skipping", file=sys.stderr)
            continue
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    print(
                        f"  Warning: {p}:{line_no} invalid JSON, skipping",
                        file=sys.stderr,
                    )
    return records


def group_by_endpoint(records: list[dict]) -> dict:
    """Group records by (method, normalized_path)."""
    groups = defaultdict(list)
    for r in records:
        key = (r["method"], normalize_path(r.get("path", "/")))
        groups[key].append(r)
    return dict(groups)


def analyze(records: list[dict]):
    """Print analysis summary to console."""
    groups = group_by_endpoint(records)

    print(f"\n{_BOLD}iRobot API Capture Analysis{_RST}")
    print(f"{_DIM}{'─' * 60}{_RST}")
    print(f"  Total requests: {_BOLD}{len(records)}{_RST}")
    print(f"  Unique endpoints: {_BOLD}{len(groups)}{_RST}")
    print()

    for (method, path), reqs in sorted(
        groups.items(), key=lambda x: (-len(x[1]), x[0])
    ):
        status_codes = defaultdict(int)
        for r in reqs:
            status_codes[r.get("status_code", "?")] += 1
        status_str = ", ".join(
            f"{code}x{count}" for code, count in sorted(status_codes.items())
        )

        print(f"  {_CYAN}{_BOLD}{method:7s}{_RST} {path}")
        print(f"          {_DIM}count={len(reqs)}  status=[{status_str}]{_RST}")

        # Merge response schemas
        resp_schema = None
        for r in reqs:
            body = r.get("response_body")
            if body is not None:
                s = infer_schema(body)
                resp_schema = merge_schemas(resp_schema, s) if resp_schema else s

        if resp_schema:
            formatted = format_schema(resp_schema, indent=5)
            print(f"          {_GREEN}response schema:{_RST}")
            for line in formatted.split("\n"):
                print(f"            {line}")

        # Merge request schemas
        req_schema = None
        for r in reqs:
            body = r.get("request_body")
            if body is not None:
                s = infer_schema(body)
                req_schema = merge_schemas(req_schema, s) if req_schema else s

        if req_schema:
            formatted = format_schema(req_schema, indent=5)
            print(f"          {_YELLOW}request schema:{_RST}")
            for line in formatted.split("\n"):
                print(f"            {line}")

        print()

    return groups


# -- Docs update logic --

DOCS_PATH = Path("docs/v4-api.md")
UNDISCOVERED_HEADER = "## Undiscovered Endpoints"
TABLE_HEADER = (
    "| Method | Path | Status Codes | Notes |\n|--------|------|-------------|-------|"
)

# Known endpoints already documented in the template
KNOWN_PATHS = {
    "/v1/discover/endpoints",
    "/accounts.login",
    "/v2/login",
}


def update_docs(groups: dict):
    """Append newly discovered endpoints to docs/v4-api.md."""
    if not DOCS_PATH.exists():
        print(
            f"  {_YELLOW}Warning: {DOCS_PATH} not found, skipping --update-docs{_RST}"
        )
        return

    content = DOCS_PATH.read_text(encoding="utf-8")

    # Find new endpoints
    new_endpoints = []
    for (method, path), reqs in sorted(groups.items()):
        if path in KNOWN_PATHS:
            continue
        # Check if already in the doc
        if path in content:
            continue
        status_codes = sorted({r.get("status_code", "?") for r in reqs})
        status_str = ", ".join(str(s) for s in status_codes)
        new_endpoints.append((method, path, status_str))

    if not new_endpoints:
        print(f"  {_GREEN}No new endpoints to add to docs.{_RST}")
        return

    # Build table rows
    rows = "\n".join(
        f"| {method} | `{path}` | {status} | _TODO_ |"
        for method, path, status in new_endpoints
    )

    # Insert after the undiscovered endpoints table header
    if UNDISCOVERED_HEADER in content:
        # Find the table or insert after header
        insert_marker = TABLE_HEADER
        if insert_marker in content:
            # Append rows after existing table header
            content = content.replace(insert_marker, f"{insert_marker}\n{rows}")
        else:
            # Add table after header
            content = content.replace(
                UNDISCOVERED_HEADER,
                f"{UNDISCOVERED_HEADER}\n\n{TABLE_HEADER}\n{rows}",
            )
    else:
        # Append section at the end
        content += f"\n\n{UNDISCOVERED_HEADER}\n\n{TABLE_HEADER}\n{rows}\n"

    DOCS_PATH.write_text(content, encoding="utf-8")
    print(f"  {_GREEN}Added {len(new_endpoints)} endpoint(s) to {DOCS_PATH}{_RST}")
    for method, path, _ in new_endpoints:
        print(f"    + {method} {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze iRobot MITM capture files (JSONL format).",
        epilog="Example: python tools/analyze_captures.py captures/*.jsonl --update-docs",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="JSONL capture files to analyze",
    )
    parser.add_argument(
        "--update-docs",
        action="store_true",
        help="Add newly discovered endpoints to docs/v4-api.md",
    )
    args = parser.parse_args()

    records = load_captures(args.files)
    if not records:
        print("No records found in the provided files.", file=sys.stderr)
        sys.exit(1)

    groups = analyze(records)

    if args.update_docs:
        update_docs(groups)


if __name__ == "__main__":
    main()
