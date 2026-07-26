from flask import Blueprint, request, jsonify, Response, current_app
from markupsafe import escape
import json
import os
import re
import shutil
import subprocess
import urllib.parse

import requests
from requests.exceptions import RequestException
from env_secrets import get_env_secret
from pathlib import Path
from setup_helpers import has_functional_cli_config

status_bp = Blueprint('status_bp', __name__)


def _parse_skill_manifest_output(
    output: str,
) -> tuple[str | None, str | None, list[str]]:
    """Return the Alexa model, endpoint, and locales from ASK CLI output."""
    manifest_data = None
    try:
        manifest_data = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        start = output.find('{') if isinstance(output, str) else -1
        if start >= 0:
            try:
                manifest_data = json.loads(output[start:])
            except json.JSONDecodeError:
                manifest_data = None
    if not isinstance(manifest_data, dict):
        return None, None, []

    manifest = manifest_data.get('manifest')
    if not isinstance(manifest, dict):
        return None, None, []
    apis = manifest.get('apis')
    if not isinstance(apis, dict):
        return None, None, []

    model = None
    api_config = None
    if isinstance(apis.get('music'), dict):
        model = 'Music'
        api_config = apis['music']
    elif isinstance(apis.get('custom'), dict):
        model = 'Custom'
        api_config = apis['custom']

    endpoint = None
    if isinstance(api_config, dict):
        endpoint_config = api_config.get('endpoint')
        if isinstance(endpoint_config, dict):
            endpoint_value = endpoint_config.get('uri')
            if isinstance(endpoint_value, str) and endpoint_value:
                endpoint = endpoint_value

    publishing = manifest.get('publishingInformation')
    publishing_locales = (
        publishing.get('locales')
        if isinstance(publishing, dict)
        else None
    )
    locales = (
        list(publishing_locales)
        if isinstance(publishing_locales, dict)
        else []
    )
    return model, endpoint, locales


def _format_api_status(
    response,
    content_preview,
    service_name,
    endpoint,
    idle_message,
):
    """Render successful, idle, and failed bridge API states consistently."""
    if response.ok:
        return (
            f'<span class="led green"></span> {service_name} API reachable '
            f'({response.status_code}) — {endpoint}'
            f"<pre class='status-box' tabindex='0' "
            "style='white-space:pre-wrap;background:#f6f6f6;padding:8px;"
            "border-radius:4px;max-height:200px;overflow:auto;"
            f"user-select:text'>{content_preview}</pre>"
        )

    if response.status_code == 404:
        status_html = (
            f'<span class="led yellow"></span> {idle_message}'
        )
        background = '#fff9e6'
    else:
        status_html = (
            f'<span class="led red"></span> {service_name} API responded '
            f'{response.status_code} for {endpoint}'
        )
        background = '#fdf2f2'

    return (
        status_html
        + f"<pre class='status-box' tabindex='0' "
        f"style='white-space:pre-wrap;background:{background};padding:8px;"
        "border-radius:4px;max-height:200px;overflow:auto;"
        f"user-select:text'>{content_preview}</pre>"
    )


def _build_status_json():
    api_user = get_env_secret('APP_USERNAME')
    api_pass = get_env_secret('APP_PASSWORD')
    skill_html = '<span class="led green"></span> Skill running'

    skill_ask_html = '<span class="muted">ASK CLI check unavailable</span>'
    try:
        skill_host = os.environ.get('SKILL_HOSTNAME', '').strip()
        if shutil.which('ask') and skill_host:
            if not has_functional_cli_config(profile='default'):
                skill_ask_html = '<span class="led yellow"></span> ASK CLI credentials are not configured for profile default'
                try:
                    skill_ask_html += ' <button onclick="window.location=\'/setup\'" style="margin-left:8px">Open Setup</button>'
                except Exception:
                    pass
            else:
                ls = subprocess.run(['ask', 'smapi', 'list-skills-for-vendor', '--profile', 'default'], capture_output=True, text=True)
                out = ls.stdout or ls.stderr or ''
                m = re.search(r'amzn1\.ask\.skill\.[0-9a-fA-F\-]+', out)
                if not m:
                    skill_ask_html = '<span class="led red"></span> Music Assistant Skill interaction model not found via ASK CLI'
                else:
                    sid = m.group(0)
                    mf = subprocess.run(['ask', 'smapi', 'get-skill-manifest', '--skill-id', sid, '--profile', 'default'], capture_output=True, text=True)
                    mf_out = mf.stdout or mf.stderr or ''
                    model, endpoint_uri, locale_list = (
                        _parse_skill_manifest_output(mf_out)
                    )
                    try:
                        if skill_host.startswith('http://') or skill_host.startswith('https://'):
                            cfg_host = urllib.parse.urlparse(skill_host).netloc
                        else:
                            cfg_host = skill_host
                    except Exception:
                        cfg_host = skill_host

                    testing_enabled = False
                    try:
                        en = subprocess.run(['ask', 'smapi', 'get-skill-enablement-status', '--skill-id', sid, '--stage', 'development', '--profile', 'default'], capture_output=True, text=True)
                        en_out = en.stdout or en.stderr or ''
                        if en.returncode == 0 or 'Command executed successfully' in en_out:
                            testing_enabled = True
                        else:
                            if re.search(r'\[Error\]:\s*\{', en_out) or re.search(r'404', en_out):
                                testing_enabled = False
                            elif re.search(r'"isEnabled"\s*:\s*true', en_out, re.IGNORECASE) or re.search(r'"enabled"\s*:\s*true', en_out, re.IGNORECASE):
                                testing_enabled = True
                    except Exception:
                        testing_enabled = False

                    is_green = False
                    if not endpoint_uri:
                        testing_msg = 'testing enabled' if testing_enabled else 'testing not enabled'
                        model_display = model or 'unknown'
                        skill_ask_html = f'<span class="led yellow"></span> Music Assistant {escape(model_display)} model {escape(sid)} found; endpoint not set ({testing_msg})'
                    else:
                        try:
                            locale_display = ','.join(locale_list) if locale_list else 'unknown'
                            if model == 'Music':
                                lambda_configured = bool(
                                    re.fullmatch(
                                        r'arn:(aws|aws-us-gov|aws-cn):'
                                        r'lambda:[a-z0-9-]+:\d{12}:'
                                        r'function:[A-Za-z0-9-_]+'
                                        r'(?::[A-Za-z0-9-_]+)?',
                                        endpoint_uri,
                                    )
                                )
                                if lambda_configured and testing_enabled:
                                    skill_ask_html = f'<span class="led green"></span> Music Assistant Music model found; Lambda endpoint configured; testing enabled; locale: {escape(locale_display)}'
                                    is_green = True
                                elif lambda_configured:
                                    skill_ask_html = '<span class="led yellow"></span> Music Assistant Music model found; Lambda endpoint configured; testing NOT enabled'
                                else:
                                    skill_ask_html = '<span class="led red"></span> Music Assistant Music model endpoint is not a Lambda ARN'
                            else:
                                parsed = urllib.parse.urlparse(endpoint_uri)
                                manifest_host = parsed.netloc
                                if manifest_host == cfg_host:
                                    if testing_enabled:
                                        skill_ask_html = f'<span class="led green"></span> Music Assistant Custom model found; endpoint matches ({escape(manifest_host)}); testing enabled; locale: {escape(locale_display)}'
                                        is_green = True
                                    else:
                                        skill_ask_html = f'<span class="led yellow"></span> Music Assistant Custom model found and endpoint matches ({escape(manifest_host)}); testing NOT enabled'
                                else:
                                    testing_note = 'testing enabled' if testing_enabled else 'testing not enabled'
                                    skill_ask_html = f'<span class="led red"></span> Music Assistant Custom model endpoint mismatch (manifest: {escape(manifest_host)} vs configured: {escape(cfg_host)}); {testing_note}'
                        except Exception:
                            testing_msg = 'testing enabled' if testing_enabled else 'testing not enabled'
                            model_display = model or 'unknown'
                            skill_ask_html = f'<span class="led yellow"></span> Music Assistant {escape(model_display)} model found; endpoint parse failed ({testing_msg})'

                    try:
                        if not is_green and model != 'Music':
                            skill_ask_html += ' <button onclick="window.location=\'/setup\'" style="margin-left:8px">Open Setup</button>'
                    except Exception:
                        pass
        else:
            if not shutil.which('ask'):
                skill_ask_html = '<span class="muted">ask CLI not available in container</span>'
            else:
                skill_ask_html = '<span class="muted">SKILL_HOSTNAME not configured</span>'
    except Exception as e:
        skill_ask_html = f'<span class="muted">ASK check error: {escape(str(e))}</span>'

    # MA API check
    endpoint_url = request.host_url.rstrip('/') + '/ma/latest-url'
    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(endpoint_url, timeout=2, auth=auth)
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)
        try:
            parsed = json.loads(content_text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            content_preview = escape(pretty)
        except Exception:
            content_preview = escape(content_text)
        ma_api_html = _format_api_status(
            resp,
            content_preview,
            'Music Assistant',
            '/ma/latest-url',
            'Music Assistant bridge idle - no stream pushed yet',
        )
    except RequestException as e:
        ma_api_html = f'<span class="led red"></span> Error: {str(e)}'

    # Alexa API check
    alexa_endpoint = request.host_url.rstrip('/') + '/alexa/latest-url'
    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(alexa_endpoint, timeout=2, auth=auth)
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)
        try:
            parsed = json.loads(content_text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            content_preview = escape(pretty)
        except Exception:
            content_preview = escape(content_text)
        alexa_api_html = _format_api_status(
            resp,
            content_preview,
            'Alexa',
            '/alexa/latest-url',
            'Alexa bridge idle - no skill invocation yet',
        )
    except RequestException as e:
        alexa_api_html = f'<span class="led red"></span> Error: {str(e)}'

    # Metadata Refresh display (APL updates)
    try:
        from skill import data as skill_data
        metadata_info = dict(skill_data.info)  # Create a copy
        pretty_metadata = json.dumps(metadata_info, indent=2, ensure_ascii=False)
        content_preview = escape(pretty_metadata)
        
        if metadata_info.get('audioSources') or metadata_info.get('primaryText'):
            metadata_html = (
                f'<span class="led green"></span> APL Metadata Refresh (current data)'
                f"<pre class='status-box' tabindex='0' style='white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:4px;max-height:200px;overflow:auto;user-select:text'>"
                f"{content_preview}</pre>"
            )
        else:
            metadata_html = (
                f'<span class="led yellow"></span> APL Metadata Refresh (no data loaded yet)'
                f"<pre class='status-box' tabindex='0' style='white-space:pre-wrap;background:#fff9e6;padding:8px;border-radius:4px;max-height:200px;overflow:auto;user-select:text'>"
                f"{content_preview}</pre>"
            )
    except Exception as e:
        metadata_html = f'<span class="led red"></span> Error loading metadata: {escape(str(e))}'

    # lightweight invocations link
    intent_logs = current_app.config.get('INTENT_LOGS', [])
    count = len(intent_logs) if intent_logs else 0
    if count:
        invocations_html = f'<a href="/invocations" target="_blank" rel="noopener noreferrer">View {count} invocations</a>'
    else:
        invocations_html = '<span class="muted">No recent invocations</span>'

    return {'skill_html': skill_html, 'skill_ask_html': skill_ask_html, 'ma_api_html': ma_api_html, 'alexa_api_html': alexa_api_html, 'metadata_html': metadata_html, 'invocations_html': invocations_html, 'created': False}


def _compute_ma_api_html(api_user=None, api_pass=None):
    api_user = api_user or get_env_secret('APP_USERNAME')
    api_pass = api_pass or get_env_secret('APP_PASSWORD')
    endpoint_url = (request.host_url.rstrip('/') if request else '') + '/ma/latest-url'
    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(endpoint_url, timeout=2, auth=auth)
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)
        try:
            parsed = json.loads(content_text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            content_preview = escape(pretty)
        except Exception:
            content_preview = escape(content_text)
        return _format_api_status(
            resp,
            content_preview,
            'Music Assistant',
            '/ma/latest-url',
            'Music Assistant bridge idle - no stream pushed yet',
        )
    except RequestException as e:
        return f'<span class="led red"></span> Error: {str(e)}'


def _compute_alexa_api_html(api_user=None, api_pass=None):
    api_user = api_user or get_env_secret('APP_USERNAME')
    api_pass = api_pass or get_env_secret('APP_PASSWORD')
    alexa_endpoint = (request.host_url.rstrip('/') if request else '') + '/alexa/latest-url'
    try:
        auth = (api_user, api_pass) if api_user and api_pass else None
        resp = requests.get(alexa_endpoint, timeout=2, auth=auth)
        try:
            content_text = resp.content.decode('utf-8', errors='replace')
        except Exception:
            content_text = str(resp.content)
        try:
            parsed = json.loads(content_text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            content_preview = escape(pretty)
        except Exception:
            content_preview = escape(content_text)
        return _format_api_status(
            resp,
            content_preview,
            'Alexa',
            '/alexa/latest-url',
            'Alexa bridge idle - no skill invocation yet',
        )
    except RequestException as e:
        return f'<span class="led red"></span> Error: {str(e)}'


@status_bp.route('/status/ma', methods=['GET'])
def status_ma():
    return jsonify({'ma_api_html': _compute_ma_api_html()})


@status_bp.route('/status/alexa', methods=['GET'])
def status_alexa():
    return jsonify({'alexa_api_html': _compute_alexa_api_html()})


def _compute_metadata_html():
    """Compute HTML showing the current APL metadata being sent in refreshes."""
    try:
        from skill import data as skill_data
        from skill.util import get_ma_hostname, replace_ip_in_url
        
        metadata_info = dict(skill_data.info)  # Create a copy
        
        # Apply MA_HOSTNAME replacement to image URLs for display
        try:
            hostname = get_ma_hostname(raise_on_http_scheme=False)
            if hostname:
                if metadata_info.get('coverImageSource'):
                    metadata_info['coverImageSource'] = replace_ip_in_url(metadata_info['coverImageSource'], hostname)
                if metadata_info.get('backgroundImageSource'):
                    metadata_info['backgroundImageSource'] = replace_ip_in_url(metadata_info['backgroundImageSource'], hostname)
        except Exception:
            pass  # If hostname replacement fails, show original URLs
        
        pretty_metadata = json.dumps(metadata_info, indent=2, ensure_ascii=False)
        content_preview = escape(pretty_metadata)
        
        if metadata_info.get('audioSources') or metadata_info.get('primaryText'):
            return (
                f'<span class="led green"></span> APL Metadata Refresh (current data)'
                f"<pre class='status-box' tabindex='0' style='white-space:pre-wrap;background:#f6f6f6;padding:8px;border-radius:4px;max-height:200px;overflow:auto;user-select:text'>"
                f"{content_preview}</pre>"
            )
        else:
            return (
                f'<span class="led yellow"></span> APL Metadata Refresh (no data loaded yet)'
                f"<pre class='status-box' tabindex='0' style='white-space:pre-wrap;background:#fff9e6;padding:8px;border-radius:4px;max-height:200px;overflow:auto;user-select:text'>"
                f"{content_preview}</pre>"
            )
    except Exception as e:
        return f'<span class="led red"></span> Error loading metadata: {escape(str(e))}'


@status_bp.route('/status/metadata', methods=['GET'])
def status_metadata():
    return jsonify({'metadata_html': _compute_metadata_html()})

@status_bp.route('/status', methods=['GET'])
def status():
    # If client requested JSON, return the aggregated checks
    want_json = request.args.get('format') == 'json' or 'application/json' in (request.headers.get('Accept') or '')
    if want_json:
        return jsonify(_build_status_json())

    # Non-JSON: render status template
    try:
        tpl_path = Path(__file__).parent.parent / 'templates' / 'status.html'
        tpl = tpl_path.read_text()
        tpl = tpl.replace('__SKILL_HTML__', '<span class="led green"></span> Skill running')
        tpl = tpl.replace('__SKILL_ASK_HTML__', '<span class="muted">Checking ASK CLI status...</span>')
        tpl = tpl.replace('__MA_API_HTML__', '<span class="muted">Checking Music Assistant API...</span>')
        tpl = tpl.replace('__ALEXA_API_HTML__', '<span class="muted">Checking Alexa API...</span>')
        tpl = tpl.replace('__METADATA_HTML__', '<span class="muted">Loading APL metadata...</span>')
        intent_logs = current_app.config.get('INTENT_LOGS', [])
        count = len(intent_logs) if intent_logs else 0
        if count:
            invocations_html = f'<a href="/invocations" target="_blank" rel="noopener noreferrer">View {count} invocations</a>'
        else:
            invocations_html = '<span class="muted">No recent invocations</span>'
        tpl = tpl.replace('__INVOCATIONS_HTML__', invocations_html)
        return Response(tpl, status=200, mimetype='text/html')
    except Exception:
        html = """<!doctype html>
            <html>
            <head><meta charset="utf-8"><title>Service Status</title></head>
            <body>
                <h1>Service Status</h1>
                <div><span class=\"led green\"></span> Skill running</div>
                <div><span class=\"muted\">Checking ASK CLI status...</span></div>
                <div><span class=\"muted\">Checking Music Assistant API...</span></div>
            </body>
            </html>"""
        return Response(html, status=200, mimetype='text/html')


@status_bp.route('/status/api', methods=['GET'])
def status_api():
    """Lightweight API used by the status UI to fetch aggregated checks."""
    return jsonify(_build_status_json())


@status_bp.route('/status/ask', methods=['GET'])
def status_ask():
    """Return only the ASK CLI check fragment used by the client UI."""
    data = _build_status_json()
    return jsonify({'skill_ask_html': data.get('skill_ask_html')})


@status_bp.route('/status/invocations', methods=['GET'])
def status_invocations():
    """Return the current invocation count and invocation HTML so the UI can refresh it live."""
    intent_logs = current_app.config.get('INTENT_LOGS', [])
    count = len(intent_logs) if intent_logs else 0
    if count:
        invocations_html = f'<a href="/invocations" target="_blank" rel="noopener noreferrer">View {count} invocations</a>'
    else:
        invocations_html = '<span class="muted">No recent invocations</span>'
    return jsonify({'count': count, 'invocations_html': invocations_html})
