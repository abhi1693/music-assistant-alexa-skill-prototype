# Music Assistant Alexa Skill Prototype
This project connects Music Assistant to Alexa. It provides the retained Flask
bridge, the original Custom Skill handler, and an AWS Lambda adapter for the
Alexa Music Skill API. The Music model is the path for native Amazon
multi-room playback; Amazon does not allow Custom and Music models in the same
skill manifest.

This fork is the maintained source for
`ghcr.io/abhi1693/music-assistant-skill`. It retains the original project
history from
[`alams154/music-assistant-alexa-skill-prototype`](https://github.com/alams154/music-assistant-alexa-skill-prototype).
Published images include both `linux/amd64` and `linux/arm64`.
Image builds use the pinned reusable
[`abhi1693/actions`](https://github.com/abhi1693/actions) Docker workflow with
native ARM execution, registry-backed BuildKit cache, and GitHub Actions cache.
The Dockerfile keeps OS, Python, npm, and application source in separate cache
layers, uses supported Node.js 22 for ASK CLI, and sends only runtime inputs in
the build context.

The fork correlates every Music Assistant playback request with an opaque
command ID. Alexa skill invocations claim pending commands in FIFO order, and
`AudioPlayer` callbacks report whether the matching command was started,
stopped, finished, or failed. This prevents concurrent Echo requests from
sharing a single global stream slot and lets Music Assistant distinguish a sent
Alexa command from confirmed playback. Transient Music Assistant flow URLs are
not re-enqueued after `PlaybackNearlyFinished`, because those URLs can expire
and return `404` while the old queue is being torn down.

Expected `404` responses before the first Music Assistant stream or Alexa skill
invocation are shown as yellow idle states on `/status`; unexpected API
failures remain red. These behaviors have regression coverage under `tests/`.

The Music model uses a separate Alexa skill. Keep the Custom skill available
until the Music skill has played successfully on physical Echo devices.
Music Assistant pushes a correlated command to the bridge,
`GetPlayableContent` claims it, `Initiate` returns its public HTTPS stream, and
Amazon's `ItemPlayback*` events update the original command. The single Music
Assistant flow stream is one Alexa queue item, so `GetNextItem` reports the
queue as complete.

## How to Run

#### Prerequisites

- An Amazon developer account: https://developer.amazon.com/en-US/docs/alexa/ask-overviews/create-developer-account.html
- Skill Access Management enabled for your developer account: [https://developer.amazon.com/alexa/console/ask/settings/access-management](https://developer.amazon.com/alexa/console/ask/settings/access-management)
    ![Skill Access Management](assets/screenshots/skill-access-management.png)
- Docker & Docker Compose installed on your host
- A public HTTPS endpoint for the skill

### 1. Using Docker Compose (Recommended)

The easiest way to run the project is with Docker Compose. This will build and start the Alexa skill container with required environment variables, secrets, and an optional persistent ASK credential volume.

#### Steps:

1. Ensure `docker-compose.yml` is present and edit environment variables as needed (e.g., `SKILL_HOSTNAME`, `MA_HOSTNAME`, `PORT`). See the [Environment Variables](#environment-variables) section below for details on each variable.
2. (Optional) Create `./secrets/app_username.txt` and `./secrets/app_password.txt` to provide `APP_USERNAME` and `APP_PASSWORD` for basic authentication of the web UI and API.
3. (Optional) To persist ASK CLI credentials across container restarts, mount a volume to `./<host directory>:/root/.ask`, `./ask_data` is used by default.
4. Start the service:

    ```sh
    docker compose up -d
    ```

5. The service will be available at `http://localhost:5000` (or the IP/port you configured).
6. In your browser, open the setup UI at `http://localhost:5000/setup`. The setup page will:
   - detect existing persistent ASK credentials (if present) and skip the browser-based auth flow
   - guide you through the ASK CLI authorization flow if credentials are not present
   - run the automated skill creation/update, interaction model upload, model build polling, and testing enablement.

Note: manual creation of the skill in the Alexa Developer Console is no longer required — the `/setup` flow automates creation and enablement when possible.

### 2. Home Assistant add-on (NOT WORKING)

This repository contains an `addons/music-assistant-skill` folder with a simple Home Assistant add-on wrapper. Running it as an add-on in your environment may require additional changes.

If you want to test as an add-on locally:

1. Add this repository as a custom add-on repository in Home Assistant Supervisor (Supervisor > Add-on Store > Repositories).
2. Install the "Music Assistant Alexa Skill" add-on and open the add-on configuration.
3. In the add-on configuration, set the options described above (`MA_HOSTNAME`, `APP_USERNAME`, `APP_PASSWORD`, `PORT`, `DEBUG_PORT`, `AWS_DEFAULT_REGION`) as needed.
4. Start the add-on and check the add-on logs for startup and any missing dependencies or configuration issues.

**Warning**: Treat this add-on as a user convenience and validate thoroughly as this method has not been tested in a Home Assistant environment and may require adjustments to work properly as an add-on.

### 3. Using `docker run`

Run the published GitHub Container Registry image with `docker run`. Replace the image tag below with the appropriate tag or digest if needed.

```sh
docker run --rm \
    -p 5000:5000 \
    -e SKILL_HOSTNAME=alexa.example.com \
    -e MA_HOSTNAME=ma.example.com \
    -e PORT=5000 \
    -e LOCALE=en-US \
    -e AWS_DEFAULT_REGION=us-east-1 \
    -v "$(pwd)/ask_data:/root/.ask" \
    -v "$(pwd)/secrets/app_username.txt:/run/secrets/APP_USERNAME:ro" \
    -v "$(pwd)/secrets/app_password.txt:/run/secrets/APP_PASSWORD:ro" \
    ghcr.io/abhi1693/music-assistant-skill:latest
```

Notes:
- Adjust `SKILL_HOSTNAME` to the public HTTPS host you'll use in the skill manifest.
- The `ask_data` volume persists ASK CLI credentials so the setup flow can reuse them.
- Mounting files into `/run/secrets` is a simple way to provide secrets for local testing; for production use Docker secrets or your platform's secret manager.

### Environment Variables

| Variable | Required | Default | Description |
|---|:---:|:---:|---|
| `SKILL_HOSTNAME` | Yes | — | Must be a publicly reachable HTTPS host (example: `alexa.example.com`). Should proxy to your open port on this container (port **5000** by default).  Public hostname used in the Alexa skill manifest and to validate the skill endpoint. |
| `MA_HOSTNAME` | *No | — | ***REQUIRED** if your device does not have a display (does not support APL). Music Assistant server hostname (example: `ma.example.com`). Should proxy to your stream port on the Music Assistant server (port **8097** by default). Also required if you would like album art on your APL device. |
| `APP_USERNAME` | No | — | Username for the web UI and API basic authentication. In Docker Compose this is provided via a Docker secret (`/run/secrets/APP_USERNAME`) pointing to `./secrets/app_username.txt`, or as a plain env var when not using secrets. |
| `APP_PASSWORD` | No | — | Password for the web UI and API basic authentication. Can be supplied as a Docker secret file or plain env var. |
| `PORT` | No | `5000` | Port the app lives at. Ensure the `ports` mapping in [docker-compose.yml](docker-compose.yml) matches this value. |
| `DEBUG_PORT` | No | `5678` | Remote debug port (if you enable remote debugging). |
| `LOCALE` | *No | `en-US` | ***REQUIRED** if your device is not configured for en-US. Skill locale used by the setup and interaction model operations (examples: `en-US`, `en-GB`, `de-DE`). |
| `AWS_DEFAULT_REGION` | No | `us-east-1` | AWS region used by ASK CLI operations when applicable. |
| `TZ` | No | `UTC` | Container timezone (example: `America/Chicago`) to make logs/timestamps match your locale. |
| `SKIP_URL_VALIDATION` | No | `false` | Skip server-side HEAD/GET validation of the rewritten stream URL before sending it to the Echo. Useful when the skill container cannot reach the external stream URL due to Docker network routing (e.g., macvlan isolation, custom outbound firewall rules). |

**Secrets and persistence**

- The example [docker-compose.yml](docker-compose.yml) demonstrates using Docker secrets for `APP_USERNAME` and `APP_PASSWORD` (files in `./secrets`). When using Docker secrets, the container environment will contain the path to the secret file (for example `/run/secrets/APP_PASSWORD`) and the service reads the file content.
- To persist ASK CLI credentials between container runs, mount a host directory as `/root/.ask` (the example uses `./ask_data:/root/.ask`). This allows the setup flow to reuse existing ASK credentials and skip the browser auth flow when present.

**Notes on values**

- `SKILL_HOSTNAME` must refer to a public HTTPS endpoint reachable by Amazon; it is embedded in the skill manifest and used for endpoint validation.
- If you override `PORT` or `DEBUG_PORT`, update the `ports` mapping in [docker-compose.yml](docker-compose.yml) accordingly (host:container).

## Basic Troubleshooting
### Status Page
`/status`

Returns a simple status page showing the local API health and an ASK CLI driven check for whether the Music Assistant skill exists, whether its endpoint matches `SKILL_HOSTNAME`, and whether testing is enabled. When the check is not green, the status page provides a quick link to `/setup`.

### Playback command API

Music Assistant creates commands with `POST /ma/push-url`. The skill claims one
pending command with `GET /ma/claim-url`, using Alexa's opaque device ID to keep
resume and hardware-control requests device-specific. Music Assistant can wait
for Alexa's acknowledgement through
`GET /ma/playback-status/<commandId>`. These `/ma` endpoints use the configured
`APP_USERNAME` and `APP_PASSWORD`; the public Alexa request endpoint remains
`POST /`.

The Music model uses `GET /ma/music/claim` instead. Music directives identify
the Alexa account rather than one physical Echo, so this endpoint intentionally
does not reuse the Custom model's device-to-serial affinity. That allows Amazon
to route the same correlated command to a multi-room group. The Lambda reads
commands and writes lifecycle events with the same Basic credentials.

### Create the separate Music skill

Do not run the `/setup` Custom Skill flow for the Music skill. Amazon
requires the Music endpoint to be an AWS Lambda function, while the existing
container remains the music-service bridge.

1. Deploy `lambda/music_skill/template.yaml` in `us-east-1` with AWS SAM. For
   the initial deployment, pass the Custom skill ID only as a temporary
   `AlexaSkillId` placeholder, plus `https://<bridge-host>/ma` and the bridge
   Basic credentials. The template restricts the Lambda trigger to the
   configured skill ID.
2. Read the `MusicSkillFunctionArn` stack output.
3. Build and inspect the new manifest without changing Amazon:

   ```sh
   scripts/create_music_skill.sh \
     --lambda-arn arn:aws:lambda:us-east-1:123456789012:function:music-assistant-alexa-music
   ```

4. Re-run the same command with `--apply`. It creates a separate Music skill
   and prints the new skill ID. The command never updates or deletes the Custom
   skill and refuses to create a duplicate when a Music skill already exists.
5. Redeploy the SAM stack with the new Music skill ID as `AlexaSkillId`. Verify
   the Lambda resource policy references the new ID before enabling the skill.
6. Enable the development skill and test a physical Echo before enabling the
   Music Assistant provider's music-model mode. The Custom skill remains
   unchanged as the fallback until this test succeeds.

Alexa Music is a vendor-gated manifest feature. If creation fails with
`DENIED_FEATURE_ACCESS` for `$.manifest.apis.music`, deleting or converting the
Custom skill will not help. Open a case from
[Contact Us](https://developer.amazon.com/alexa/console/contact-us) in the
Alexa Developer Console and ask Amazon to enable the Music feature for the
developer vendor and required locale. Include the failing operation
`POST /v1/skills`, the locale, and the exact violation. Keep the Custom skill
and do not enable Music mode in Music Assistant until Amazon grants access.

The generated Music manifest contains only `manifest.apis.music`, because
Amazon does not permit Music and Custom models together. It declares
`GetPlayableContent`, `Initiate`, `GetNextItem`, `GetPreviousItem`, and
`GetItem`, plus playback lifecycle subscriptions for command correlation.

### TLS Support
TLS 1.3 is not supported

If using Cloudflare, set minimum TLS version to 1.2

---

See [COMPATIBILITY.md](COMPATIBILITY.md) for known supported devices, languages, and regions.

See [LIMITATIONS.md](LIMITATIONS.md) for known limitations.

See [DISCLAIMER.md](DISCLAIMER.md) for security concerns and development disclosures.
