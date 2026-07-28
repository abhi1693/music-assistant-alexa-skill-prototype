"""Regression tests for correlated playback command state."""

import sys
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_ROOT))

from music_assistant_api import ma_routes
from music_assistant_api.playback_store import (
    PlaybackCommandStore,
    UnknownPlaybackCommandError,
)


class PlaybackCommandStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = PlaybackCommandStore()

    def test_commands_are_claimed_fifo_and_correlated_to_events(self):
        first = self.store.create_or_update({
            "streamUrl": "http://ma/flow/first.mp3",
            "playerId": "echo-1",
        })
        second = self.store.create_or_update({
            "streamUrl": "http://ma/flow/second.mp3",
            "playerId": "echo-2",
        })

        claimed_first = self.store.claim("alexa-device-1")
        claimed_second = self.store.claim("alexa-device-2")

        self.assertEqual(claimed_first["commandId"], first["commandId"])
        self.assertEqual(claimed_second["commandId"], second["commandId"])
        self.assertEqual(claimed_first["status"], "claimed")
        self.assertEqual(
            claimed_first["alexaDeviceId"],
            "alexa-device-1",
        )

        started = self.store.record_event(
            first["commandId"],
            "AudioPlayer.PlaybackStarted",
            alexa_device_id="alexa-device-1",
            offset_milliseconds=0,
        )
        self.assertEqual(started["status"], "started")
        self.assertEqual(started["offsetMilliseconds"], 0)
        self.assertEqual(
            self.store.get(second["commandId"])["status"],
            "claimed",
        )
        self.assertEqual(
            self.store.latest("alexa-device-1")["commandId"],
            first["commandId"],
        )
        self.assertEqual(
            self.store.latest("alexa-device-2")["commandId"],
            second["commandId"],
        )

    def test_metadata_update_does_not_create_another_pending_command(self):
        command = self.store.create_or_update({
            "streamUrl": "http://ma/flow/song.mp3",
            "title": "Original",
        })
        updated = self.store.create_or_update({
            "commandId": command["commandId"],
            "streamUrl": "http://ma/flow/song.mp3",
            "title": "Updated",
        })

        self.assertEqual(updated["commandId"], command["commandId"])
        self.assertEqual(updated["title"], "Updated")
        self.assertEqual(
            self.store.claim("alexa-device")["commandId"],
            command["commandId"],
        )
        self.assertIsNone(self.store.claim("another-device"))

    def test_unknown_metadata_update_does_not_create_pending_command(self):
        with self.assertRaises(UnknownPlaybackCommandError):
            self.store.create_or_update({
                "commandId": "lost-after-bridge-restart",
                "streamUrl": "http://ma/flow/stale.mp3",
                "title": "Stale",
            })

        self.assertIsNone(self.store.claim("alexa-device"))

    def test_known_alexa_device_claims_only_its_target(self):
        initial = self.store.create_or_update({
            "streamUrl": "http://ma/flow/initial.mp3",
            "targetDeviceSerial": "serial-a",
        })
        self.assertEqual(
            self.store.claim("alexa-device-a")["commandId"],
            initial["commandId"],
        )

        other = self.store.create_or_update({
            "streamUrl": "http://ma/flow/other.mp3",
            "targetDeviceSerial": "serial-b",
        })
        matching = self.store.create_or_update({
            "streamUrl": "http://ma/flow/matching.mp3",
            "targetDeviceSerial": "serial-a",
        })

        self.assertEqual(
            self.store.claim("alexa-device-a")["commandId"],
            matching["commandId"],
        )
        self.assertEqual(
            self.store.claim("alexa-device-b")["commandId"],
            other["commandId"],
        )

    def test_resume_lifecycle_waits_for_new_playback_started_event(self):
        command = self.store.create_or_update({
            "streamUrl": "http://ma/flow/song.mp3",
        })
        self.store.claim("alexa-device")
        self.store.record_event(
            command["commandId"],
            "AudioPlayer.PlaybackStopped",
            alexa_device_id="alexa-device",
        )

        pending = self.store.record_event(
            command["commandId"],
            "MusicAssistant.ResumeRequested",
        )
        self.assertEqual(pending["status"], "resume_pending")

        started = self.store.record_event(
            command["commandId"],
            "AudioPlayer.PlaybackStarted",
            alexa_device_id="alexa-device",
        )
        self.assertEqual(started["status"], "started")


class PlaybackCommandRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_store = ma_routes._store
        ma_routes._store = PlaybackCommandStore()
        from music_assistant_api import create_ma_app
        self.client = create_ma_app().test_client()

    def tearDown(self):
        ma_routes._store = self.previous_store

    def test_command_claim_and_status_lifecycle(self):
        pushed = self.client.post("/push-url", json={
            "streamUrl": "http://ma/flow/song.mp3",
            "playerId": "echo-1",
            "targetDeviceFamily": "ECHO",
        })
        self.assertEqual(pushed.status_code, 200)
        command_id = pushed.get_json()["commandId"]

        claimed = self.client.get(
            "/claim-url?alexaDeviceId=opaque-device-id"
        )
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(claimed.get_json()["commandId"], command_id)

        event = self.client.post("/playback-event", json={
            "commandId": command_id,
            "eventType": "AudioPlayer.PlaybackStarted",
            "alexaDeviceId": "opaque-device-id",
            "offsetMilliseconds": 0,
        })
        self.assertEqual(event.status_code, 200)
        self.assertEqual(event.get_json()["commandStatus"], "started")

        status = self.client.get(f"/playback-status/{command_id}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["status"], "started")

    def test_claim_without_pending_command_is_idle(self):
        response = self.client.get("/claim-url")
        self.assertEqual(response.status_code, 404)

    def test_unknown_metadata_update_returns_not_found(self):
        response = self.client.post("/push-url", json={
            "commandId": "lost-after-bridge-restart",
            "streamUrl": "http://ma/flow/stale.mp3",
            "title": "Stale",
        })

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {"error": "Unknown playback command"},
        )
        self.assertEqual(self.client.get("/claim-url").status_code, 404)


if __name__ == "__main__":
    unittest.main()
