"""Regression tests for screenless Echo queue continuation."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

from ask_sdk_model.interfaces.audioplayer import PlayBehavior, PlayDirective
from skill import util


class StubResponseBuilder:
    def __init__(self):
        self.directives = []
        self.should_end_session = None

    def add_directive(self, directive):
        self.directives.append(directive)
        return self

    def set_should_end_session(self, value):
        self.should_end_session = value
        return self

    @property
    def response(self):
        return self


class PlayLaterTests(unittest.TestCase):
    def test_replaces_enqueued_stream_with_public_https_url(self):
        builder = StubResponseBuilder()

        with (
            patch.dict(
                os.environ,
                {"MA_HOSTNAME": "music-stream.example.com"},
                clear=False,
            ),
            patch.object(util, "push_alexa_metadata") as push_metadata,
        ):
            response = util.play_later(
                "http://192.168.4.10:8097/flow/My Song.mp3",
                builder,
            )

        self.assertIs(response, builder)
        self.assertTrue(builder.should_end_session)
        self.assertEqual(len(builder.directives), 1)
        directive = builder.directives[0]
        self.assertIsInstance(directive, PlayDirective)
        self.assertEqual(
            directive.play_behavior,
            PlayBehavior.REPLACE_ENQUEUED,
        )
        stream = directive.audio_item.stream
        self.assertEqual(
            stream.url,
            "https://music-stream.example.com/flow/My%20Song.mp3",
        )
        self.assertEqual(stream.token, stream.url)
        self.assertEqual(stream.offset_in_milliseconds, 0)
        self.assertIsNone(stream.expected_previous_token)
        push_metadata.assert_called_once_with(stream.url)

    def test_missing_hostname_returns_directive_free_response(self):
        builder = StubResponseBuilder()

        with patch.dict(os.environ, {"MA_HOSTNAME": ""}, clear=False):
            response = util.play_later(
                "http://192.168.4.10:8097/flow/song.mp3",
                builder,
            )

        self.assertIs(response, builder)
        self.assertEqual(builder.directives, [])
        self.assertIsNone(builder.should_end_session)

    def test_uses_correlated_tokens_when_provided(self):
        builder = StubResponseBuilder()

        with (
            patch.dict(
                os.environ,
                {"MA_HOSTNAME": "music-stream.example.com"},
                clear=False,
            ),
            patch.object(util, "push_alexa_metadata") as push_metadata,
        ):
            util.play_later(
                "http://192.168.4.10:8097/flow/song.mp3",
                builder,
                playback_token="command-next",
                expected_previous_token="command-current",
            )

        stream = builder.directives[0].audio_item.stream
        self.assertEqual(stream.token, "command-next")
        self.assertEqual(
            stream.expected_previous_token,
            "command-current",
        )
        push_metadata.assert_called_once_with(
            stream.url,
            command_id="command-next",
        )


if __name__ == "__main__":
    unittest.main()
