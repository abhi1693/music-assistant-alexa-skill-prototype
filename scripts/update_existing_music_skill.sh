#!/usr/bin/env bash
# Update an existing Alexa skill from Custom to Music without creating one.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_manifest="$repo_root/app/music_skill.json"
build_dir="$repo_root/build"
output_manifest="$build_dir/music-skill.json"
backup_manifest="$build_dir/custom-skill-backup.json"
profile="default"
stage="development"
locale="en-IN"
skill_id=""
lambda_arn=""
apply_update=false

usage() {
  printf '%s\n' \
    "Usage:" \
    "  update_existing_music_skill.sh --skill-id ID --lambda-arn ARN [--apply]" \
    "" \
    "Options:" \
    "  --skill-id ID       Existing Alexa skill ID. No skill is created." \
    "  --lambda-arn ARN    Deployed Alexa Music Lambda ARN." \
    "  --profile NAME      ASK CLI profile (default: default)." \
    "  --stage STAGE       Alexa skill stage (default: development)." \
    "  --locale LOCALE     Music model locale (default: en-IN)." \
    "  --apply             Back up and update the existing skill manifest." \
    "  -h, --help          Show this help."
}

while (($#)); do
  case "$1" in
    --skill-id)
      skill_id="$2"
      shift 2
      ;;
    --lambda-arn)
      lambda_arn="$2"
      shift 2
      ;;
    --profile)
      profile="$2"
      shift 2
      ;;
    --stage)
      stage="$2"
      shift 2
      ;;
    --locale)
      locale="$2"
      shift 2
      ;;
    --apply)
      apply_update=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! "$skill_id" =~ ^amzn1\.ask\.skill\.[0-9a-fA-F-]+$ ]]; then
  echo "--skill-id must name the existing Alexa skill" >&2
  exit 2
fi
if [[ -z "$lambda_arn" ]]; then
  echo "--lambda-arn is required" >&2
  exit 2
fi
command -v ask >/dev/null

mkdir -p "$build_dir"
python3 "$repo_root/scripts/build_music_skill_manifest.py" \
  "$source_manifest" \
  "$output_manifest" \
  "$lambda_arn" \
  --locale "$locale"

if [[ "$apply_update" != true ]]; then
  echo "Built $output_manifest; existing skill was not changed."
  echo "Re-run with --apply after the Lambda is deployed and tested."
  exit 0
fi

ask smapi get-skill-manifest \
  --skill-id "$skill_id" \
  --stage "$stage" \
  --profile "$profile" > "$backup_manifest"

python3 - "$backup_manifest" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
apis = manifest.get("manifest", {}).get("apis", {})
if "custom" not in apis:
    raise SystemExit(
        "Existing manifest backup is not the expected Custom model; refusing update"
    )
PY

ask smapi update-skill-manifest \
  --skill-id "$skill_id" \
  --stage "$stage" \
  --manifest "file:$output_manifest" \
  --profile "$profile"

echo "Updated existing skill $skill_id to the Music model."
echo "Rollback manifest: $backup_manifest"
