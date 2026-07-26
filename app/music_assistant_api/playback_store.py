"""Thread-safe playback command state for the Music Assistant bridge."""

from __future__ import annotations

from collections import OrderedDict, deque
from copy import deepcopy
import threading
import time
from typing import Any
from uuid import uuid4


class PlaybackCommandStore:
    """Track pending Music Assistant commands and Alexa playback events."""

    def __init__(self, max_commands: int = 200, ttl_seconds: int = 900):
        self._max_commands = max_commands
        self._ttl_seconds = ttl_seconds
        self._commands: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._pending: deque[str] = deque()
        self._device_targets: dict[str, str] = {}
        self._version = 0
        self._lock = threading.RLock()

    def create_or_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a pending playback command or update an existing command."""
        stream_url = payload.get("streamUrl")
        if not isinstance(stream_url, str) or not stream_url:
            raise ValueError("streamUrl is required")

        supplied_command_id = payload.get("commandId")
        command_id = (
            supplied_command_id
            if isinstance(supplied_command_id, str) and supplied_command_id
            else uuid4().hex
        )
        now = time.time()

        with self._lock:
            self._purge(now)
            if command_id in self._commands:
                command = self._commands[command_id]
                for key in (
                    "streamUrl",
                    "title",
                    "artist",
                    "album",
                    "imageUrl",
                ):
                    if key in payload:
                        command[key] = payload.get(key)
                command["updatedAt"] = now
                self._commands.move_to_end(command_id)
                return deepcopy(command)

            self._version += 1
            command = {
                "commandId": command_id,
                "streamUrl": stream_url,
                "title": payload.get("title"),
                "artist": payload.get("artist"),
                "album": payload.get("album"),
                "imageUrl": payload.get("imageUrl"),
                "playerId": payload.get("playerId"),
                "targetDeviceSerial": payload.get("targetDeviceSerial"),
                "targetDeviceFamily": payload.get("targetDeviceFamily"),
                "targetDeviceName": payload.get("targetDeviceName"),
                "status": "pending",
                "lastEvent": "pending",
                "version": self._version,
                "createdAt": now,
                "updatedAt": now,
            }
            self._commands[command_id] = command
            self._pending.append(command_id)
            self._trim()
            return deepcopy(command)

    def claim(self, alexa_device_id: str | None = None) -> dict[str, Any] | None:
        """Claim the oldest pending command for an Alexa skill invocation."""
        now = time.time()
        with self._lock:
            self._purge(now)
            known_target = (
                self._device_targets.get(alexa_device_id)
                if alexa_device_id
                else None
            )
            command_id = None
            for pending_id in tuple(self._pending):
                pending_command = self._commands.get(pending_id)
                if (
                    pending_command is None
                    or pending_command["status"] != "pending"
                ):
                    self._pending.remove(pending_id)
                    continue
                if (
                    known_target is None
                    or pending_command.get("targetDeviceSerial") == known_target
                ):
                    command_id = pending_id
                    self._pending.remove(pending_id)
                    break

            if command_id is not None:
                command = self._commands.get(command_id)
                assert command is not None
                command["status"] = "claimed"
                command["lastEvent"] = "claimed"
                command["alexaDeviceId"] = alexa_device_id
                command["claimedAt"] = now
                command["updatedAt"] = now
                target_serial = command.get("targetDeviceSerial")
                if alexa_device_id and isinstance(target_serial, str):
                    self._device_targets[alexa_device_id] = target_serial
                return deepcopy(command)
        return None

    def record_event(
        self,
        command_id: str,
        event_type: str,
        *,
        alexa_device_id: str | None = None,
        offset_milliseconds: int | None = None,
        error: Any = None,
    ) -> dict[str, Any] | None:
        """Record an AudioPlayer lifecycle event for a command."""
        normalized_event = event_type.rsplit(".", 1)[-1].lower()
        status_by_event = {
            "playbackstarted": "started",
            "playbackstopped": "stopped",
            "playbackfinished": "finished",
            "playbackfailed": "failed",
        }
        now = time.time()

        with self._lock:
            self._purge(now)
            command = self._commands.get(command_id)
            if command is None:
                return None

            command["lastEvent"] = normalized_event
            if normalized_event in status_by_event:
                command["status"] = status_by_event[normalized_event]
            if alexa_device_id:
                command["alexaDeviceId"] = alexa_device_id
            if isinstance(offset_milliseconds, int):
                command["offsetMilliseconds"] = offset_milliseconds
            if error is not None:
                command["error"] = str(error)
            command["updatedAt"] = now
            command[f"{normalized_event}At"] = now
            self._commands.move_to_end(command_id)
            return deepcopy(command)

    def get(self, command_id: str) -> dict[str, Any] | None:
        """Return a command by ID."""
        with self._lock:
            self._purge(time.time())
            command = self._commands.get(command_id)
            return deepcopy(command) if command is not None else None

    def latest(
        self,
        alexa_device_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the most recent command, optionally for one Alexa device."""
        with self._lock:
            self._purge(time.time())
            if not self._commands:
                return None
            for command in reversed(self._commands.values()):
                if (
                    alexa_device_id is None
                    or command.get("alexaDeviceId") == alexa_device_id
                ):
                    return deepcopy(command)
            return None

    def _purge(self, now: float) -> None:
        expired = [
            command_id
            for command_id, command in self._commands.items()
            if now - float(command["updatedAt"]) > self._ttl_seconds
        ]
        for command_id in expired:
            self._commands.pop(command_id, None)

    def _trim(self) -> None:
        while len(self._commands) > self._max_commands:
            self._commands.popitem(last=False)
