"""Tests for building the separate Alexa Music skill manifest."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_music_skill_manifest.py"
SPEC = importlib.util.spec_from_file_location(
    "build_music_skill_manifest",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class MusicManifestTests(unittest.TestCase):
    def test_builder_keeps_only_music_model_and_existing_locale(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "manifest.json"
            arn = (
                "arn:aws:lambda:us-east-1:123456789012:"
                "function:music-assistant-alexa-music"
            )

            builder.build_manifest(
                REPO_ROOT / "app" / "music_skill.json",
                output_path,
                arn,
                "en-IN",
            )

            manifest = json.loads(
                output_path.read_text(encoding="utf-8")
            )["manifest"]
            self.assertEqual(set(manifest["apis"]), {"music"})
            self.assertNotIn("custom", manifest["apis"])
            self.assertEqual(
                manifest["apis"]["music"]["endpoint"]["uri"],
                arn,
            )
            self.assertEqual(
                manifest["events"]["endpoint"]["uri"],
                arn,
            )
            self.assertEqual(
                set(manifest["apis"]["music"]["locales"]),
                {"en-IN"},
            )

    def test_builder_rejects_non_lambda_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "lambda ARN"):
                builder.build_manifest(
                    REPO_ROOT / "app" / "music_skill.json",
                    Path(temporary_directory) / "manifest.json",
                    "https://alexa.example",
                    "en-IN",
                )


if __name__ == "__main__":
    unittest.main()
