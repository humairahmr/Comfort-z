# Comfort-z

Comfort-z is an agentic animal-monitoring MVP for Google's **All Things Agentic Hackathon**. It turns a visual observation into a structured, non-diagnostic record, remembers it, compares it with the animal's history, then decides whether to continue monitoring or create an alert.

> Comfort-z is not veterinary care. It only describes visible behaviour and recommends professional veterinary advice when a pattern is potentially concerning.

## Agentic workflow

The `comfort_z` Google ADK agent owns one goal: **monitor this animal over time**. Its `monitor_animal` tool uses Gemini to interpret an image, saves the result, retrieves the same animal's recent history, compares the records, applies an explainable policy, and returns supporting evidence.

```mermaid
flowchart LR
  U[Owner visual input] --> A[comfort_z ADK agent]
  A --> G[Gemini multimodal analysis]
  G --> S[Structured observation]
  S --> R[Observation repository]
  R --> H[Animal history]
  H --> C[Comparison + alert policy]
  C --> D[Monitor or alert]
  D --> U
  R -. local JSON / Cloud Firestore .-> F[Firestore]
```

This is deliberately not `prompt → Gemini → answer`: the tool operates on persistent history and independently decides to record, monitor, or alert. It reports the evidence behind each decision.

## Technology

- **Gemini** (`gemini-3.5-flash`): multimodal, structured visual observations.
- **Google ADK**: the `comfort_z` agent and tool orchestration.
- **Firestore**: optional Cloud-ready observation history; local development defaults to JSON.
- **Cloud Run**: deployment-ready Dockerfile.

The runtime does not use OpenAI APIs or models.

## Structure

```text
comfort_z/
  agent.py                 # ADK agent named comfort_z
  models.py                # Observation, profile, decision, and report schemas
  services/                # Gemini, repositories, comparison, video, orchestration
  tools/monitoring.py      # Agent-callable monitoring workflow tools
tests/                      # Storage and policy tests
```

## Local setup

Prerequisites: Python 3.11+ and a Gemini API key from Google AI Studio. For Vertex AI instead, use Application Default Credentials and set `GOOGLE_GENAI_USE_VERTEXAI=true`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Set either `GEMINI_API_KEY` or `GOOGLE_API_KEY` in `.env` (never commit it), then run:

```powershell
pytest -q
adk web --host 127.0.0.1 --port 8000 .
python -c "from comfort_z.agent import root_agent; print(root_agent.name)"
```

The final command should print `comfort_z` without calling Gemini. In ADK Web, select `comfort_z` and submit a request such as:

```text
Monitor animal_id "milo" using image_path "C:\\demo\\milo_today.jpg". Save it and explain whether I should monitor or act.
```

## Basic video monitoring

OpenCV samples a local video or webcam at a deliberate interval; it does not send every frame to Gemini. Each sample is saved through the existing `monitor_animal` workflow, including a source/frame description in the observation record.

Test a local video (five samples, one every five seconds of video time):

```powershell
python -c "from comfort_z.services.video import VideoMonitoringService; result = VideoMonitoringService().monitor('raku', r'C:\\demo\\raku.mp4', sample_interval_seconds=5, max_samples=5, animal_name='Raku', expected_species='Betta splendens'); print(result.model_dump_json(indent=2))"
```

Test webcam device 0 (five samples, one every five seconds of live time):

```powershell
python -c "from comfort_z.services.video import VideoMonitoringService; result = VideoMonitoringService().monitor('raku', 0, sample_interval_seconds=5, max_samples=5, animal_name='Raku', expected_species='Betta splendens'); print(result.model_dump_json(indent=2))"
```

`max_samples` provides a normal bounded stop and limits total sampled-frame attempts, including failed Gemini analyses. Transient Gemini 429/503 responses retry only once by default, use a server retry delay when supplied (otherwise exponential backoff), and stop the session after retries are exhausted. You can tune `max_transient_retries`, `base_retry_delay_seconds`, and `stop_retry_delay_seconds` when calling `monitor`; conservative defaults protect the hackathon/free-tier quota. Code that runs a longer session can retain the service object and call `service.stop()`; an unavailable device, unreadable frame, encoding failure, or one Gemini failure is recorded in `failures` without crashing the session.

When `expected_species` is supplied, Gemini decides whether that expected animal is sufficiently visible instead of freely identifying another creature. Frames marked `animal_not_visible` or `uncertain` are stored for provenance but excluded from behavioural trends and alert persistence.

## Bounded continuous monitoring demo

Comfort-z can save a persistent goal such as **“Keep an eye on Raku”** without opening an endless process. A profile stores the video source, normal/elevated sample intervals, daily sample budget, cursor, active state, and report schedule. Each `next-window` invocation is intentionally finite: it reads the saved cursor, analyzes at most its small requested sample count (and never more than the remaining daily budget), writes observations through the existing workflow, and saves the next cursor. Calling it again resumes after the prior attempted video timestamp instead of restarting at zero.

For a private Cloud Storage video, set a video profile's `source_reference` to a generic object URI such as `gs://YOUR_BUCKET/path/to/video.mp4`. Each bounded window uses Application Default Credentials (the Cloud Run runtime service account in Cloud Run) to download that object directly to a temporary file, passes only that file to OpenCV, then deletes it when the window completes or fails. The saved profile and observation provenance retain the original `gs://` URI, never the temporary path. Local paths and integer webcam sources continue to bypass Cloud Storage entirely. No signed URL, public bucket access, credential file, or new environment variable is required.

Grant the runtime service account the bucket-scoped Storage Object Viewer role (`roles/storage.objectViewer`), or a custom role containing `storage.objects.get`, on each private media bucket it must read. The service does not list, upload, or modify media objects.

For local development, monitoring profiles and reports are stored in `data/monitoring_state.json`; set `LOCAL_MONITORING_STATE_FILE` to use another ignored path. With `OBSERVATION_STORE=firestore`, profiles use `animals/{animal_id}/monitoring/profile` and reports use `animals/{animal_id}/reports/{report_id}`. No credentials are stored in either repository.

Create a Raku video profile through the API:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/monitoring/profiles -ContentType 'application/json' -Body '{"animal_id":"raku","animal_name":"Raku","expected_species":"Betta splendens","monitoring_goal":"Keep an eye on Raku.","source_reference":"C:\\demo\\Raku.mp4","source_type":"video","normal_sampling_interval_seconds":5,"elevated_sampling_interval_seconds":1,"daily_sample_budget":24,"report_time":"08:00","timezone":"Asia/Kuala_Lumpur"}'
```

Process the next two selected frames only:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/monitoring/raku/next-window -ContentType 'application/json' -Body '{"window_max_samples":2}'
```

The first valid non-normal observation changes the saved profile to elevated sampling for a later invocation. Non-visible or uncertain frames never change the behavioural trend or sampling mode. Existing Gemini 429/503 bounds still apply inside each window. An inactive profile and an exhausted daily budget return a normal bounded result without opening the source.

Generate a daily report after the configured monitoring period:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/monitoring/raku/daily-report
Invoke-RestMethod -Uri http://127.0.0.1:8080/animals/raku/reports?limit=5
```

The report sends Gemini only structured saved observations, never the historical images or video frames. It separates valid behavioural evidence from `animal_not_visible` and `uncertain` counts, includes saved alert decisions, and persists the resulting report. A future Cloud Scheduler configuration can call the already-bounded `POST /monitoring/{animal_id}/next-window` and daily-report endpoints; this repository does not configure a scheduler.

### Conditional research context

Comfort-z evaluates optional external research only after a valid observation shows a worsening, recurring, alerting, or explicitly unresolved non-normal pattern. It does not search for normal, non-visible, uncertain-visibility, or first isolated mild observations. The current repository provides a mockable provider interface only—no web provider or network request is enabled by default. Any future provider is limited to five short source summaries, persisted with the triggering observation. Source quality is explicit (`authoritative`, `manufacturer_documentation`, `community`, or `unknown`); community material is always labelled anecdotal and cannot override authoritative guidance. Matching successful research is reused for 24 hours, and daily reports consume the saved context without refetching it.

### Optional outdoor weather and enclosure readings

A monitoring profile may include `location_name`, `latitude`, `longitude`, `enclosure_type`, and owner-provided `direct_environment_readings`. Weather is requested only when both coordinates are present. The built-in Open-Meteo adapter retrieves current outdoor 2 m air temperature, humidity, and weather condition without a configured API key; lookup failure is ignored so normal monitoring continues.

Outdoor weather is supporting context only. Comfort-z explicitly tells Gemini that it must not equate outdoor conditions with an aquarium, terrarium, cage, room, or other enclosure. Owner readings are distinct structured records with `reading_type`, `value`, `unit`, `recorded_at`, and `source: "owner"`. For broadly hot or cold outdoor conditions, if no direct temperature reading is provided, Comfort-z can persist a request for an owner measurement; it does not change behavioural severity or fabricate an enclosure temperature.

For example, an optional profile payload can include:

```json
{
  "location_name": "Owner-provided location",
  "latitude": 0.0,
  "longitude": 0.0,
  "enclosure_type": "aquarium",
  "direct_environment_readings": [
    {
      "reading_type": "water_temperature",
      "value": 26.0,
      "unit": "C",
      "source": "owner"
    }
  ]
}
```

## Storage and alerts

Default storage is `data/observations.json`. Firestore is used only when `OBSERVATION_STORE=firestore` and `GOOGLE_CLOUD_PROJECT` are set. It uses Application Default Credentials and stores records at `animals/{animal_id}/observations/{observation_id}`: the parent stores stable animal metadata and every observation document retains the existing structured observation payload. `FIRESTORE_OBSERVATIONS_COLLECTION` defaults to `observations`; leave `OBSERVATION_STORE=local` for the validated local fallback. The policy is intentionally simple: a first uncertain/concerning observation is saved for follow-up, while a visible worsening or at least two concerning results among the newest three observations creates an alert. It never makes medical diagnoses.

### Enable Firestore locally

1. Create or select a Google Cloud project, then enable the Firestore API and create a Firestore database in Native mode.
2. Install and initialize the Google Cloud CLI, set the active project, and create Application Default Credentials:

   ```powershell
   gcloud config set project YOUR_PROJECT_ID
   gcloud auth application-default login
   ```

3. In `.env`, set `OBSERVATION_STORE=firestore` and `GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID`. Optionally set `FIRESTORE_OBSERVATIONS_COLLECTION=observations`.
4. Run the normal Comfort-z command. If Firestore cannot initialize or respond, Comfort-z reports a storage error with credential/network guidance; it never silently changes the configured store.

## Cloud Run deployment preparation

The container starts the minimal HTTP API with Uvicorn at `0.0.0.0:$PORT`. It provides:

- `GET /health` — process health, selected store, ADK agent, and model; no external request.
- `POST /monitor` — calls the existing `monitor_animal` ADK tool with `animal_id`, `image_path`, and optional animal metadata.
- `GET /animals/{animal_id}/observations?limit=5` — calls the existing repository-backed history tool.
- `POST /monitoring/profiles` — saves an active/inactive bounded monitoring profile.
- `GET /monitoring/{animal_id}/profile` — retrieves a saved profile.
- `POST /monitoring/{animal_id}/next-window` — processes one finite source window.
- `POST /monitoring/{animal_id}/daily-report` — generates one persisted daily report from structured history.
- `GET /animals/{animal_id}/reports?limit=5` — retrieves persisted reports.

Before deploying, create a Firestore Native database, enable Cloud Run, Cloud Build, Artifact Registry, Firestore, and Secret Manager APIs, then create a dedicated Cloud Run service account. Grant it `roles/datastore.user` for Firestore and `roles/secretmanager.secretAccessor` for the Gemini API-key secret. Cloud Run uses this service account as Application Default Credentials for Firestore; do not upload service-account JSON files.

Create a Secret Manager secret named `comfort-z-gemini-api-key` containing only your Gemini Developer API key. Then deploy from the repository root:

```powershell
gcloud run deploy comfort-z --source . --region YOUR_REGION --project YOUR_PROJECT_ID --service-account comfort-z-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com --set-env-vars OBSERVATION_STORE=firestore,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,FIRESTORE_OBSERVATIONS_COLLECTION=observations,GEMINI_MODEL=gemini-3.5-flash --set-secrets GOOGLE_API_KEY=comfort-z-gemini-api-key:latest
```

The container image excludes `.env`, virtual environments, local JSON data, ADC files, service-account/credential JSON files, tests, and demo videos. Use `GET /health` after deployment to confirm startup. For a Vertex AI configuration instead of a Gemini API-key secret, set `GOOGLE_GENAI_USE_VERTEXAI=true` and grant the service account the appropriate Vertex AI role.

## Demo flow and limitations

Submit an image for Milo to establish a baseline; submit a second image with the same potential issue to demonstrate retrieved history and a persistence alert; submit an improved image to show the trend change. The MVP accepts image files (or any simple Gemini-supported visual MIME type accessible by the server). It does not diagnose disease, provide multi-instance local persistence, or yet ingest full videos/scheduled rechecks—those are natural next steps.
