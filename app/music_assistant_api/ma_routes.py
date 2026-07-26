"""Route definitions for Music Assistant playback commands."""

from flask import jsonify, request

from .playback_store import PlaybackCommandStore


_store = PlaybackCommandStore()


def record_playback_event(
    command_id,
    event_type,
    *,
    alexa_device_id=None,
    offset_milliseconds=None,
    error=None,
):
    """Record a skill callback without requiring an internal HTTP request."""
    return _store.record_event(
        command_id,
        event_type,
        alexa_device_id=alexa_device_id,
        offset_milliseconds=offset_milliseconds,
        error=error,
    )


def register_routes(bp):
    @bp.route('/push-url', methods=['POST'])
    def push_url():
        """Create a pending playback command or update its metadata.

        A new command is created when commandId is absent. Supplying an
        existing commandId updates metadata without adding another pending
        skill invocation.
        """
        data = request.get_json(silent=True) or {}
        try:
            command = _store.create_or_update(data)
        except ValueError:
            return jsonify({'error': 'Missing required fields'}), 400
        return jsonify({
            'status': 'ok',
            'commandId': command['commandId'],
            'version': command['version'],
            'commandStatus': command['status'],
        })

    @bp.route('/latest-url', methods=['GET'])
    def latest_url():
        """Return the most recent command for compatibility and diagnostics."""
        command = _store.latest(request.args.get('alexaDeviceId'))
        if command is None:
            return jsonify({'error': 'No URL available, please check if Music Assistant has pushed a URL to the API'}), 404
        return jsonify(command)

    @bp.route('/claim-url', methods=['GET'])
    def claim_url():
        """Claim the oldest pending command for one Alexa invocation."""
        command = _store.claim(request.args.get('alexaDeviceId'))
        if command is None:
            return jsonify({'error': 'No pending playback command'}), 404
        return jsonify(command)

    @bp.route('/music/claim', methods=['GET'])
    def claim_music():
        """Claim a pending command for an Alexa Music Skill directive."""
        command = _store.claim_music(request.args.get('alexaUserId'))
        if command is None:
            return jsonify({'error': 'No pending playback command'}), 404
        return jsonify(command)

    @bp.route('/playback-status/<command_id>', methods=['GET'])
    def playback_status(command_id):
        """Return the correlated playback status for Music Assistant."""
        command = _store.get(command_id)
        if command is None:
            return jsonify({'error': 'Unknown playback command'}), 404
        return jsonify(command)

    @bp.route('/playback-event', methods=['POST'])
    def playback_event():
        """Record a correlated AudioPlayer lifecycle event."""
        data = request.get_json(silent=True) or {}
        command_id = data.get('commandId')
        event_type = data.get('eventType')
        if not command_id or not event_type:
            return jsonify({'error': 'commandId and eventType are required'}), 400
        command = record_playback_event(
            command_id,
            event_type,
            alexa_device_id=data.get('alexaDeviceId'),
            offset_milliseconds=data.get('offsetMilliseconds'),
            error=data.get('error'),
        )
        if command is None:
            return jsonify({'error': 'Unknown playback command'}), 404
        return jsonify({
            'status': 'ok',
            'commandId': command_id,
            'commandStatus': command['status'],
        })
