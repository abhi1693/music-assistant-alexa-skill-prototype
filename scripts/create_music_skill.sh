#!/usr/bin/env bash
# Build or create a separate Alexa Music skill without changing Custom skills.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_manifest="$repo_root/app/music_skill.json"
build_dir="$repo_root/build"
output_manifest="$build_dir/music-skill.json"
profile="default"
locale="en-IN"
lambda_arn=""
apply_create=false

usage() {
  printf '%s\n' \
    "Usage:" \
    "  create_music_skill.sh --lambda-arn ARN [--apply]" \
    "" \
    "Options:" \
    "  --lambda-arn ARN    Deployed Alexa Music Lambda ARN." \
    "  --profile NAME      ASK CLI profile (default: default)." \
    "  --locale LOCALE     Music model locale (default: en-IN)." \
    "  --apply             Create the separate Music skill in Amazon." \
    "  -h, --help          Show this help." \
    "" \
    "The command never updates or deletes an existing Alexa skill."
}

while (($#)); do
  case "$1" in
    --lambda-arn)
      lambda_arn="$2"
      shift 2
      ;;
    --profile)
      profile="$2"
      shift 2
      ;;
    --locale)
      locale="$2"
      shift 2
      ;;
    --apply)
      apply_create=true
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

if [[ -z "$lambda_arn" ]]; then
  echo "--lambda-arn is required" >&2
  exit 2
fi
command -v python3 >/dev/null

mkdir -p "$build_dir"
python3 "$repo_root/scripts/build_music_skill_manifest.py" \
  "$source_manifest" \
  "$output_manifest" \
  "$lambda_arn" \
  --locale "$locale"

if [[ "$apply_create" != true ]]; then
  echo "Built $output_manifest; Amazon was not changed."
  echo "Re-run with --apply after inspecting the manifest."
  exit 0
fi

command -v ask >/dev/null

skills_file="$(mktemp)"
create_output="$(mktemp)"
cleanup() {
  rm -f "$skills_file" "$create_output"
}
trap cleanup EXIT

ask smapi list-skills-for-vendor \
  --profile "$profile" > "$skills_file"

existing_music_skill="$(
  python3 - "$skills_file" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
skill_ids = [
    skill["skillId"]
    for skill in data.get("skills", [])
    if "music" in skill.get("apis", [])
]
if len(skill_ids) > 1:
    raise SystemExit(
        "Multiple Music skills already exist; refusing to choose one"
    )
print(skill_ids[0] if skill_ids else "")
PY
)"

if [[ -n "$existing_music_skill" ]]; then
  echo "Music skill already exists: $existing_music_skill"
  echo "No skill was created or changed."
  exit 0
fi

if ! ask smapi create-skill-for-vendor \
  --manifest "file:$output_manifest" \
  --profile "$profile" > "$create_output" 2>&1; then
  cat "$create_output" >&2
  printf '%s\n' \
    "" \
    "Amazon rejected the Music skill creation request." \
    "If the response is HTTP 400, ask Alexa Developer Support to enable" \
    "the Music feature for this developer vendor. Do not delete the" \
    "working Custom skill while Music access is unavailable." >&2
  exit 1
fi

skill_id="$(
  python3 - "$create_output" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
try:
    skill_id = json.loads(text).get("skillId", "")
except json.JSONDecodeError:
    match = re.search(r"amzn1\.ask\.skill\.[0-9a-fA-F-]+", text)
    skill_id = match.group(0) if match else ""
print(skill_id)
PY
)"

if [[ -z "$skill_id" ]]; then
  cat "$create_output"
  echo "Amazon returned success without a detectable skill ID" >&2
  exit 1
fi

echo "Created separate Music skill: $skill_id"
echo "Redeploy the Lambda stack with AlexaSkillId=$skill_id before enabling it."
