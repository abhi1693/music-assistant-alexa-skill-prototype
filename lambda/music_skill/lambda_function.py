"""Alexa Music Skill API adapter for Music Assistant playback commands.

The Lambda function is intentionally stateless. Music Assistant pushes a
correlated playback command to the existing bridge, Alexa resolves that pending
command through GetPlayableContent, and Initiate retrieves the command by ID.
Playback lifecycle events are then written back to the bridge.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any
from urllib import error, parse, request
from uuid import uuid4


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


class BridgeError(RuntimeError):
    """Raised when the Music Assistant bridge cannot satisfy a request."""


class BridgeClient:
    """Small, dependency-free client for the authenticated bridge API."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: float = 0.35,
    ) -> None:
        parsed_url = parse.urlsplit(base_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("BRIDGE_URL must be an absolute HTTPS URL")
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout

    @classmethod
    def from_environment(cls) -> "BridgeClient":
        """Create the client from Lambda environment variables."""
        base_url = os.environ.get("BRIDGE_URL", "").strip()
        username = os.environ.get("BRIDGE_USERNAME", "")
        password = os.environ.get("BRIDGE_PASSWORD", "")
        timeout_text = os.environ.get("BRIDGE_TIMEOUT_SECONDS", "0.35")
        try:
            timeout = float(timeout_text)
        except ValueError as err:
            raise ValueError(
                "BRIDGE_TIMEOUT_SECONDS must be a number"
            ) from err
        if timeout <= 0 or timeout > 2:
            raise ValueError(
                "BRIDGE_TIMEOUT_SECONDS must be greater than 0 and at most 2"
            )
        return cls(base_url, username, password, timeout)

    def claim(self, alexa_user_id: str | None) -> dict[str, Any] | None:
        """Claim the oldest pending command for a Music Skill request."""
        query = parse.urlencode(
            {"alexaUserId": alexa_user_id}
            if alexa_user_id
            else {}
        )
        suffix = f"?{query}" if query else ""
        return self._request("GET", f"/music/claim{suffix}", allow_not_found=True)

    def get_command(self, command_id: str) -> dict[str, Any] | None:
        """Retrieve one correlated playback command."""
        encoded_id = parse.quote(command_id, safe="")
        return self._request(
            "GET",
            f"/playback-status/{encoded_id}",
            allow_not_found=True,
        )

    def record_event(
        self,
        command_id: str,
        event_type: str,
        *,
        alexa_device_id: str | None = None,
        offset_milliseconds: int | None = None,
        event_error: str | None = None,
    ) -> dict[str, Any] | None:
        """Write an Amazon playback lifecycle event to the bridge."""
        payload: dict[str, Any] = {
            "commandId": command_id,
            "eventType": event_type,
        }
        if alexa_device_id:
            payload["alexaDeviceId"] = alexa_device_id
        if isinstance(offset_milliseconds, int):
            payload["offsetMilliseconds"] = offset_milliseconds
        if event_error:
            payload["error"] = event_error
        return self._request(
            "POST",
            "/playback-event",
            payload=payload,
            allow_not_found=True,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        headers = {"Accept": "application/json"}
        data = None
        if self._username or self._password:
            token = base64.b64encode(
                f"{self._username}:{self._password}".encode("utf-8")
            ).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        bridge_request = request.Request(
            f"{self._base_url}/{path.lstrip('/')}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(
                bridge_request,
                timeout=self._timeout,
            ) as response:
                raw_body = response.read(1_048_577)
        except error.HTTPError as err:
            if allow_not_found and err.code == 404:
                return None
            diagnostic_headers = {
                header: value
                for header in (
                    "Server",
                    "Content-Type",
                    "CF-Ray",
                    "CF-Mitigated",
                )
                if (value := err.headers.get(header))
            }
            error_body = err.read(513)
            body_preview = (
                error_body[:512]
                .decode("utf-8", errors="replace")
                .replace("\r", " ")
                .replace("\n", " ")
            )
            LOGGER.warning(
                "Bridge returned HTTP %s headers=%s body=%r truncated=%s",
                err.code,
                diagnostic_headers,
                body_preview,
                len(error_body) > 512,
            )
            raise BridgeError(
                f"bridge returned HTTP {err.code}"
            ) from err
        except (error.URLError, TimeoutError, OSError) as err:
            raise BridgeError("bridge request failed") from err

        if len(raw_body) > 1_048_576:
            raise BridgeError("bridge response exceeded 1 MiB")
        try:
            result = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            raise BridgeError("bridge returned invalid JSON") from err
        if not isinstance(result, dict):
            raise BridgeError("bridge returned a non-object response")
        return result


def _response_header(namespace: str, name: str) -> dict[str, str]:
    return {
        "namespace": namespace,
        "name": name,
        "messageId": str(uuid4()),
        "payloadVersion": "1.0",
    }


def _response(
    namespace: str,
    name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "header": _response_header(namespace, name),
        "payload": payload,
    }


def _media_error(error_type: str, message: str) -> dict[str, Any]:
    return _response(
        "Alexa.Media",
        "ErrorResponse",
        {"type": error_type, "message": message},
    )


def _safe_text(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.split()).strip()
    return cleaned[:512] or fallback


def _metadata(command: dict[str, Any]) -> dict[str, Any]:
    title = _safe_text(command.get("title"), "Music Assistant")
    metadata: dict[str, Any] = {
        "type": "TRACK",
        "name": {
            "speech": {
                "type": "PLAIN_TEXT",
                "text": title,
            },
            "display": title,
        },
    }
    artist = _safe_text(command.get("artist"), "")
    if artist:
        metadata["authors"] = [
            {
                "name": {
                    "speech": {
                        "type": "PLAIN_TEXT",
                        "text": artist,
                    },
                    "display": artist,
                }
            }
        ]
    return metadata


def _playable_item(command: dict[str, Any]) -> dict[str, Any]:
    command_id = command.get("commandId")
    stream_url = command.get("streamUrl")
    if not isinstance(command_id, str) or not command_id:
        raise BridgeError("bridge command has no commandId")
    if not isinstance(stream_url, str):
        raise BridgeError("bridge command has no streamUrl")
    parsed_stream = parse.urlsplit(stream_url)
    if parsed_stream.scheme != "https" or not parsed_stream.netloc:
        raise BridgeError("bridge command streamUrl must use HTTPS")

    return {
        "id": f"item-{command_id}",
        "playbackInfo": {"type": "DEFAULT"},
        "metadata": _metadata(command),
        "controls": [],
        "rules": {"feedbackEnabled": False},
        "stream": {
            "id": f"stream-{command_id}",
            "uri": stream_url,
            "offsetInMilliseconds": 0,
        },
    }


def _alexa_user_id(payload: dict[str, Any]) -> str | None:
    request_context = payload.get("requestContext")
    if not isinstance(request_context, dict):
        return None
    user = request_context.get("user")
    if not isinstance(user, dict):
        return None
    user_id = user.get("id")
    return user_id if isinstance(user_id, str) and user_id else None


def _content_id(payload: dict[str, Any]) -> str | None:
    direct_id = payload.get("contentId")
    if isinstance(direct_id, str) and direct_id:
        return direct_id

    for key in (
        "currentItemReference",
        "itemReference",
        "previousItemReference",
    ):
        reference = payload.get(key)
        if not isinstance(reference, dict):
            continue
        value = reference.get("value")
        if isinstance(value, dict):
            candidate = value.get("contentId")
            if isinstance(candidate, str) and candidate:
                return candidate
        candidate = reference.get("contentId")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _get_playable_content(
    payload: dict[str, Any],
    bridge: BridgeClient,
) -> dict[str, Any]:
    command = bridge.claim(_alexa_user_id(payload))
    if command is None:
        return _media_error(
            "CONTENT_NOT_FOUND",
            "Music Assistant has no pending playback command.",
        )
    command_id = command.get("commandId")
    if not isinstance(command_id, str) or not command_id:
        raise BridgeError("claimed bridge command has no commandId")
    LOGGER.info("Claimed Music Assistant command %s", command_id)
    return _response(
        "Alexa.Media.Search",
        "GetPlayableContent.Response",
        {
            "content": {
                "id": command_id,
                "metadata": _metadata(command),
            }
        },
    )


def _initiate(
    payload: dict[str, Any],
    bridge: BridgeClient,
) -> dict[str, Any]:
    command_id = _content_id(payload)
    if command_id is None:
        return _media_error(
            "CONTENT_NOT_FOUND",
            "The Music Assistant command identifier is missing.",
        )
    command = bridge.get_command(command_id)
    if command is None:
        return _media_error(
            "CONTENT_NOT_FOUND",
            "The Music Assistant command is no longer available.",
        )
    item = _playable_item(command)
    LOGGER.info("Initiating Music Assistant command %s", command_id)
    return _response(
        "Alexa.Media.Playback",
        "Initiate.Response",
        {
            "playbackMethod": {
                "type": "ALEXA_AUDIO_PLAYER_QUEUE",
                "id": f"queue-{command_id}",
                "controls": [],
                "rules": {
                    "feedback": {
                        "type": "PREFERENCE",
                        "enabled": False,
                    }
                },
                "firstItem": item,
            }
        },
    )


def _get_current_item(
    namespace: str,
    response_name: str,
    payload: dict[str, Any],
    bridge: BridgeClient,
) -> dict[str, Any]:
    command_id = _content_id(payload)
    if command_id is None:
        return _media_error(
            "CONTENT_NOT_FOUND",
            "The Music Assistant item identifier is missing.",
        )
    command = bridge.get_command(command_id)
    if command is None:
        return _media_error(
            "CONTENT_NOT_FOUND",
            "The Music Assistant item is no longer available.",
        )
    return _response(
        namespace,
        response_name,
        {"item": _playable_item(command)},
    )


def _handle_directive(
    event: dict[str, Any],
    bridge: BridgeClient,
) -> dict[str, Any]:
    header = event.get("header")
    payload = event.get("payload")
    if not isinstance(header, dict) or not isinstance(payload, dict):
        return _media_error(
            "MEDIA_ERROR_INVALID_REQUEST",
            "The Alexa Music request is malformed.",
        )

    namespace = header.get("namespace")
    name = header.get("name")
    LOGGER.info(
        "Received Alexa Music directive %s.%s messageId=%s",
        namespace,
        name,
        header.get("messageId"),
    )

    if namespace == "Alexa.Media.Search" and name == "GetPlayableContent":
        return _get_playable_content(payload, bridge)
    if namespace == "Alexa.Media.Playback" and name == "Initiate":
        return _initiate(payload, bridge)
    if namespace == "Alexa.Audio.PlayQueue" and name == "GetNextItem":
        return _response(
            namespace,
            "GetNextItem.Response",
            {"isQueueFinished": True, "item": None},
        )
    if namespace == "Alexa.Audio.PlayQueue" and name == "GetPreviousItem":
        return _get_current_item(
            namespace,
            "GetPreviousItem.Response",
            payload,
            bridge,
        )
    if namespace == "Alexa.Media.PlayQueue" and name == "GetItem":
        return _get_current_item(
            namespace,
            "GetItem.Response",
            payload,
            bridge,
        )
    return _media_error(
        "MEDIA_ERROR_INVALID_REQUEST",
        f"Unsupported Alexa Music directive: {namespace}.{name}",
    )


_PLAYBACK_EVENT_NAMES = {
    "ItemPlaybackStarted": "AlexaMusic.PlaybackStarted",
    "ItemPlaybackFinished": "AlexaMusic.PlaybackFinished",
    "ItemPlaybackStopped": "AlexaMusic.PlaybackStopped",
    "ItemPlaybackFailed": "AlexaMusic.PlaybackFailed",
}


def _handle_playback_event(
    event: dict[str, Any],
    bridge: BridgeClient,
) -> dict[str, Any]:
    event_request = event.get("request")
    if not isinstance(event_request, dict):
        return {}
    request_type = event_request.get("type")
    if not isinstance(request_type, str):
        return {}
    event_name = request_type.rsplit(".", 1)[-1]
    bridge_event = _PLAYBACK_EVENT_NAMES.get(event_name)
    if bridge_event is None:
        return {}

    body = event_request.get("body")
    if not isinstance(body, dict):
        return {}
    item = body.get("item")
    if not isinstance(item, dict):
        return {}
    command_id = item.get("contentId")
    if not isinstance(command_id, str) or not command_id:
        return {}

    context = event.get("context")
    system = context.get("System") if isinstance(context, dict) else None
    endpoint_ids = (
        system.get("endpointIds")
        if isinstance(system, dict)
        else None
    )
    alexa_device_id = (
        endpoint_ids[0]
        if isinstance(endpoint_ids, list)
        and endpoint_ids
        and isinstance(endpoint_ids[0], str)
        else None
    )

    event_error = None
    error_data = body.get("error")
    if isinstance(error_data, dict):
        error_type = _safe_text(error_data.get("type"), "")
        error_message = _safe_text(error_data.get("message"), "")
        event_error = ": ".join(
            value for value in (error_type, error_message) if value
        )

    bridge.record_event(
        command_id,
        bridge_event,
        alexa_device_id=alexa_device_id,
        offset_milliseconds=body.get("offsetInMilliseconds"),
        event_error=event_error,
    )
    LOGGER.info(
        "Recorded Alexa Music event %s for command %s",
        event_name,
        command_id,
    )
    return {}


def handle(
    event: dict[str, Any],
    bridge: BridgeClient,
) -> dict[str, Any]:
    """Handle one Alexa directive or subscribed playback event."""
    event_request = event.get("request")
    if isinstance(event_request, dict):
        request_type = event_request.get("type")
        if (
            isinstance(request_type, str)
            and request_type.startswith("AlexaAudioPlayQueueEvent.")
        ):
            return _handle_playback_event(event, bridge)
        if request_type in {
            "AlexaSkillEvent.SkillEnabled",
            "AlexaSkillEvent.SkillDisabled",
            "AlexaSkillEvent.SkillAccountLinked",
        }:
            return {}
    return _handle_directive(event, bridge)


def lambda_handler(
    event: dict[str, Any],
    context: Any,
) -> dict[str, Any]:
    """AWS Lambda entry point."""
    del context
    try:
        return handle(event, BridgeClient.from_environment())
    except (BridgeError, ValueError) as err:
        LOGGER.exception("Alexa Music bridge request failed")
        return _media_error(
            "MEDIA_ERROR_SERVICE_UNAVAILABLE",
            str(err),
        )
