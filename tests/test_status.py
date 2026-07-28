"""Regression tests for bridge status presentation."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

from endpoints.status import (
    _format_api_status,
    _parse_skill_manifest_output,
)


class ApiStatusTests(unittest.TestCase):
    def test_not_found_is_an_idle_state(self):
        response = SimpleNamespace(ok=False, status_code=404)

        html = _format_api_status(
            response,
            '{"error": "not ready"}',
            "Alexa",
            "/alexa/latest-url",
            "Alexa bridge idle - no skill invocation yet",
        )

        self.assertIn('led yellow', html)
        self.assertIn('Alexa bridge idle - no skill invocation yet', html)
        self.assertIn('background:#fff9e6', html)
        self.assertNotIn('led red', html)

    def test_unexpected_failure_remains_red(self):
        response = SimpleNamespace(ok=False, status_code=503)

        html = _format_api_status(
            response,
            "unavailable",
            "Music Assistant",
            "/ma/latest-url",
            "Music Assistant bridge idle - no stream pushed yet",
        )

        self.assertIn('led red', html)
        self.assertIn(
            'Music Assistant API responded 503 for /ma/latest-url',
            html,
        )
        self.assertIn('background:#fdf2f2', html)

    def test_manifest_parser_reads_custom_endpoint_over_icon_urls(self):
        manifest = {
            "manifest": {
                "publishingInformation": {
                    "locales": {
                        "en-IN": {
                            "smallIconUri": "https://example/icon.png",
                        }
                    }
                },
                "apis": {
                    "custom": {
                        "endpoint": {
                            "uri": "https://alexa.example.com"
                        }
                    }
                },
            }
        }

        model, endpoint, locales = _parse_skill_manifest_output(
            json.dumps(manifest)
        )

        self.assertEqual(model, "Custom")
        self.assertEqual(endpoint, "https://alexa.example.com")
        self.assertEqual(locales, ["en-IN"])


if __name__ == "__main__":
    unittest.main()
