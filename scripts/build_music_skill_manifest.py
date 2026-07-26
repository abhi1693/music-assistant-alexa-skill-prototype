#!/usr/bin/env python3
"""Build a manifest for a separate Alexa Music skill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


LAMBDA_ARN_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):lambda:"
    r"[a-z0-9-]+:\d{12}:function:[A-Za-z0-9-_]+"
    r"(?::[A-Za-z0-9-_]+)?$"
)


def build_manifest(
    source_path: Path,
    output_path: Path,
    lambda_arn: str,
    locale: str,
) -> None:
    if not LAMBDA_ARN_PATTERN.fullmatch(lambda_arn):
        raise ValueError("lambda ARN is invalid")

    data = json.loads(source_path.read_text(encoding="utf-8"))
    manifest = data.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("manifest root is missing")

    apis = manifest.get("apis")
    if not isinstance(apis, dict) or set(apis) != {"music"}:
        raise ValueError("Music manifest must contain only manifest.apis.music")
    music = apis["music"]
    if not isinstance(music, dict):
        raise ValueError("manifest.apis.music is invalid")

    publishing = manifest.get("publishingInformation")
    publishing_locales = (
        publishing.get("locales")
        if isinstance(publishing, dict)
        else None
    )
    music_locales = music.get("locales")
    if (
        not isinstance(publishing_locales, dict)
        or locale not in publishing_locales
        or not isinstance(music_locales, dict)
        or locale not in music_locales
    ):
        raise ValueError(f"locale {locale} is not configured")

    publishing["locales"] = {locale: publishing_locales[locale]}
    music["locales"] = {locale: music_locales[locale]}
    music["endpoint"] = {"uri": lambda_arn}

    events = manifest.get("events")
    if not isinstance(events, dict):
        raise ValueError("manifest.events is missing")
    events["endpoint"] = {"uri": lambda_arn}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("lambda_arn")
    parser.add_argument("--locale", default="en-IN")
    args = parser.parse_args()
    build_manifest(
        args.source,
        args.output,
        args.lambda_arn,
        args.locale,
    )
    print(f"WROTE {args.output}")


if __name__ == "__main__":
    main()
