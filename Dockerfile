# syntax=docker/dockerfile:1.7

# renovate: datasource=docker depName=ubuntu
FROM ubuntu:22.04@sha256:0e0a0fc6d18feda9db1590da249ac93e8d5abfea8f4c3c0c849ce512b5ef8982

ARG ASK_CLI_VERSION=2.30.7
ARG DEBUG_PORT=0

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        libssl-dev \
        python3.10 \
        python3.10-venv && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs

WORKDIR /app

# Dependency layers change only when the lock inputs or Dockerfile change.
COPY app/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python3.10 -m venv /app/venv && \
    /app/venv/bin/python -m pip install --upgrade pip && \
    /app/venv/bin/python -m pip install \
        --requirement /app/requirements.txt \
        debugpy

RUN --mount=type=cache,target=/root/.npm \
    npm install --global "ask-cli@${ASK_CLI_VERSION}"

# Patch verifier.py for timezone-aware certificate validity checks.
RUN /app/venv/bin/python - <<'PY'
import os
import sys
import sysconfig

try:
    site = sysconfig.get_paths()['purelib']
except Exception:
    print('Could not determine site-packages path; skipping verifier patch')
    sys.exit(0)

verifier_path = os.path.join(
    site,
    'ask_sdk_webservice_support',
    'verifier.py',
)
if not os.path.exists(verifier_path):
    print('verifier.py not found at', verifier_path, '; skipping patch')
    sys.exit(0)

with open(verifier_path, 'r', encoding='utf-8') as file_handle:
    source = file_handle.read()

needle = (
    '        now = datetime.utcnow()\n'
    '        if not (x509_cert.not_valid_before <= now <=\n'
    '                x509_cert.not_valid_after):\n'
    '            raise VerificationException("Signing Certificate expired")'
)
patch = (
    '        from datetime import timezone\n'
    '        now = datetime.now(timezone.utc)\n'
    '        # Use timezone-aware UTC datetimes and updated cryptography '
    'properties\n'
    "        not_valid_before = getattr(x509_cert, "
    "'not_valid_before_utc', None) or "
    'x509_cert.not_valid_before.replace(tzinfo=timezone.utc)\n'
    "        not_valid_after = getattr(x509_cert, "
    "'not_valid_after_utc', None) or "
    'x509_cert.not_valid_after.replace(tzinfo=timezone.utc)\n'
    '        if not (not_valid_before <= now <= not_valid_after):\n'
    '            raise VerificationException("Signing Certificate expired")'
)

if needle in source:
    with open(verifier_path, 'w', encoding='utf-8') as file_handle:
        file_handle.write(source.replace(needle, patch))
    print('Patched', verifier_path)
else:
    print('No patch needed for verifier.py')
PY

# certvalidator 0.11.1 cannot hash some modern OS trust-root subjects with
# asn1crypto >= 1.5.1. Skip only those incompatible roots.
RUN /app/venv/bin/python - <<'PY'
import os
import sys
import sysconfig

try:
    site = sysconfig.get_paths()['purelib']
except Exception:
    print('Could not determine site-packages path; skipping registry patch')
    sys.exit(0)

registry_path = os.path.join(site, 'certvalidator', 'registry.py')
if not os.path.exists(registry_path):
    print('registry.py not found at', registry_path, '; skipping patch')
    sys.exit(0)

with open(registry_path, 'r', encoding='utf-8') as file_handle:
    source = file_handle.read()

needle = (
    '        for trust_root in trust_roots:\n'
    '            hashable = trust_root.subject.hashable\n'
    '            if hashable not in self._subject_map:\n'
    '                self._subject_map[hashable] = []\n'
    '            self._subject_map[hashable].append(trust_root)\n'
    '            if trust_root.key_identifier:\n'
    '                self._key_identifier_map[trust_root.key_identifier] = '
    'trust_root\n'
    '            self._ca_lookup[trust_root.signature] = True'
)
patch = (
    '        for trust_root in trust_roots:\n'
    '            try:\n'
    '                hashable = trust_root.subject.hashable\n'
    '            except Exception:\n'
    '                # Skip subjects incompatible with this asn1crypto '
    'version\n'
    '                continue\n'
    '            if hashable not in self._subject_map:\n'
    '                self._subject_map[hashable] = []\n'
    '            self._subject_map[hashable].append(trust_root)\n'
    '            if trust_root.key_identifier:\n'
    '                self._key_identifier_map[trust_root.key_identifier] = '
    'trust_root\n'
    '            self._ca_lookup[trust_root.signature] = True'
)

if needle in source:
    with open(registry_path, 'w', encoding='utf-8') as file_handle:
        file_handle.write(source.replace(needle, patch))
    print('Patched', registry_path)
else:
    print('No patch needed for registry.py')
PY

# Runtime source is intentionally copied after all dependency layers.
COPY app /app/src
RUN ln -s /app/src /app/app

COPY assets/icons /app/assets/icons
COPY scripts/ask_create_skill.sh \
    scripts/build_music_skill_manifest.py \
    scripts/build_skill_manifest.py \
    scripts/create_music_skill.sh \
    scripts/find_skills_to_delete.py \
    /app/scripts/
RUN chmod 0755 \
    /app/scripts/ask_create_skill.sh \
    /app/scripts/build_music_skill_manifest.py \
    /app/scripts/create_music_skill.sh

ENV AWS_DEFAULT_REGION=us-east-1 \
    TZ=UTC \
    MA_HOSTNAME="" \
    SKILL_HOSTNAME="" \
    PORT=5000 \
    LOCALE=en-US \
    QUIET_HTTP=1 \
    DEBUG_PORT=${DEBUG_PORT}

EXPOSE 5000

CMD ["/bin/sh", "-lc", "if [ -n \"${DEBUG_PORT}\" ] && [ \"${DEBUG_PORT}\" != \"0\" ]; then exec /app/venv/bin/python -m debugpy --listen 0.0.0.0:${DEBUG_PORT} src/app.py; else exec /app/venv/bin/python src/app.py; fi"]
