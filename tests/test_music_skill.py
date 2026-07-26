"""Regression tests for the Alexa Music Skill API Lambda adapter."""

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

lambda_function = importlib.import_module(
    "lambda.music_skill.lambda_function"
)


class FakeBridge:
    def __init__(self):
        self.command = {
            "commandId": "command-123",
            "streamUrl": "https://music-stream.example/flow.mp3",
            "title": "Track title",
            "artist": "Track artist",
            "status": "claimed",
        }
        self.claimed_user_id = None
        self.events = []

    def claim(self, alexa_user_id):
        self.claimed_user_id = alexa_user_id
        return self.command

    def get_command(self, command_id):
        if command_id == self.command["commandId"]:
            return self.command
        return None

    def record_event(
        self,
        command_id,
        event_type,
        *,
        alexa_device_id=None,
        offset_milliseconds=None,
        event_error=None,
    ):
        self.events.append({
            "commandId": command_id,
            "eventType": event_type,
            "alexaDeviceId": alexa_device_id,
            "offsetMilliseconds": offset_milliseconds,
            "error": event_error,
        })
        return {"status": "ok"}


def music_directive(namespace, name, payload):
    return {
        "header": {
            "namespace": namespace,
            "name": name,
            "messageId": "request-message-id",
            "payloadVersion": "1.0",
        },
        "payload": payload,
    }


class MusicSkillTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()

    def test_get_playable_content_claims_pending_command(self):
        event = music_directive(
            "Alexa.Media.Search",
            "GetPlayableContent",
            {
                "requestContext": {
                    "user": {"id": "opaque-alexa-account"},
                }
            },
        )

        response = lambda_function.handle(event, self.bridge)

        self.assertEqual(
            response["header"]["name"],
            "GetPlayableContent.Response",
        )
        self.assertEqual(
            response["payload"]["content"]["id"],
            "command-123",
        )
        self.assertEqual(
            response["payload"]["content"]["metadata"]["name"]["display"],
            "Track title",
        )
        self.assertEqual(
            self.bridge.claimed_user_id,
            "opaque-alexa-account",
        )

    def test_get_playable_content_returns_content_not_found_when_idle(self):
        self.bridge.command = None
        event = music_directive(
            "Alexa.Media.Search",
            "GetPlayableContent",
            {"requestContext": {}},
        )

        response = lambda_function.handle(event, self.bridge)

        self.assertEqual(response["header"]["name"], "ErrorResponse")
        self.assertEqual(
            response["payload"]["type"],
            "CONTENT_NOT_FOUND",
        )

    def test_initiate_returns_correlated_https_stream(self):
        event = music_directive(
            "Alexa.Media.Playback",
            "Initiate",
            {"contentId": "command-123"},
        )

        response = lambda_function.handle(event, self.bridge)

        playback = response["payload"]["playbackMethod"]
        self.assertEqual(response["header"]["name"], "Initiate.Response")
        self.assertEqual(playback["id"], "queue-command-123")
        self.assertEqual(
            playback["firstItem"]["stream"]["uri"],
            "https://music-stream.example/flow.mp3",
        )
        self.assertEqual(
            playback["firstItem"]["metadata"]["authors"][0]["name"]["display"],
            "Track artist",
        )

    def test_get_next_item_finishes_single_flow_stream_queue(self):
        event = music_directive(
            "Alexa.Audio.PlayQueue",
            "GetNextItem",
            {},
        )

        response = lambda_function.handle(event, self.bridge)

        self.assertEqual(response["header"]["name"], "GetNextItem.Response")
        self.assertTrue(response["payload"]["isQueueFinished"])
        self.assertIsNone(response["payload"]["item"])

    def test_playback_started_event_updates_original_command(self):
        event = {
            "version": "1.0",
            "context": {
                "System": {
                    "endpointIds": ["opaque-group-endpoint"],
                }
            },
            "request": {
                "type": "AlexaAudioPlayQueueEvent.ItemPlaybackStarted",
                "requestId": "event-request-id",
                "body": {
                    "offsetInMilliseconds": 12,
                    "item": {
                        "id": "item-command-123",
                        "queueId": "queue-command-123",
                        "contentId": "command-123",
                    },
                },
            },
        }

        response = lambda_function.handle(event, self.bridge)

        self.assertEqual(response, {})
        self.assertEqual(
            self.bridge.events,
            [{
                "commandId": "command-123",
                "eventType": "AlexaMusic.PlaybackStarted",
                "alexaDeviceId": "opaque-group-endpoint",
                "offsetMilliseconds": 12,
                "error": None,
            }],
        )

    def test_initiate_rejects_non_https_stream(self):
        self.bridge.command["streamUrl"] = "http://private/flow.mp3"
        event = music_directive(
            "Alexa.Media.Playback",
            "Initiate",
            {"contentId": "command-123"},
        )

        with self.assertRaises(lambda_function.BridgeError):
            lambda_function.handle(event, self.bridge)

    @mock.patch.object(lambda_function.request, "urlopen")
    def test_bridge_uses_explicit_api_user_agent(self, mock_urlopen):
        response = mock.MagicMock()
        response.read.return_value = b'{"status":"ok"}'
        mock_urlopen.return_value.__enter__.return_value = response
        bridge = lambda_function.BridgeClient(
            "https://bridge.example/ma",
            "user",
            "password",
        )

        bridge.get_command("command-123")

        sent_request = mock_urlopen.call_args.args[0]
        self.assertEqual(
            sent_request.get_header("User-agent"),
            lambda_function.BRIDGE_USER_AGENT,
        )


if __name__ == "__main__":
    unittest.main()
