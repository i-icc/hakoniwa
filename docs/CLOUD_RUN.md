# Deploy to Cloud Run with IAP

[日本語](./CLOUD_RUN.ja.md)

Deploy Hakoniwa with its bundled examples and share it with specific Google accounts. This guide enables Identity-Aware Proxy (IAP) directly on the Cloud Run service. Authorized users can view and modify the same worlds and run history. [Configure IAP for Cloud Run](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

This setup is intended for demos. SQLite lives in the instance's `/tmp` directory, so the database is lost when the instance stops (which, with the settings below, happens whenever nobody has used it for a while), is replaced, or the service is redeployed. It also counts against the instance's memory. There are two ways to keep what matters:

- **By hand.** Open **Data** in the header, save the worlds and runs you want to keep as one SQLite file before updating, and bring the file back in afterward. HTTP/1 requests to Cloud Run have a 32 MiB limit; a compressed run with about 500 residents is around 3 MB.
- **Automatically.** Mount a Cloud Storage bucket and let Hakoniwa keep a whole copy of the database there. See [Keep the data in a bucket](#keep-the-data-in-a-bucket).

[Cloud Run file system](https://docs.cloud.google.com/run/docs/container-contract#file-system) · [Request limits](https://docs.cloud.google.com/run/quotas#request-limits-for-cloud-run)

## 1. Prepare the project and image

You need a Google Cloud project with billing enabled, `gcloud`, and Docker. The person deploying needs permission to deploy the service, configure IAM, push to Artifact Registry, and use the runtime service account. [Cloud Run IAM roles](https://docs.cloud.google.com/run/docs/reference/iam/roles) · [Push to Artifact Registry](https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling)

Run the commands in Bash from the repository root. Set your project ID and list one IAP principal per line in `IAP_MEMBERS`. Use `user:EMAIL` for a Google account and `group:EMAIL` for a Google group.

```bash
PROJECT_ID="your-project-id"
REGION="asia-northeast1"
SERVICE="hakoniwa"
REPOSITORY="hakoniwa"
IAP_MEMBERS=(
  "user:you@example.com"
  "user:teammate@example.com"
  "group:demo-team@example.com"
)
RUNTIME_SA="hakoniwa-run@$PROJECT_ID.iam.gserviceaccount.com"

gcloud auth login
gcloud services enable run.googleapis.com artifactregistry.googleapis.com iap.googleapis.com \
  --project="$PROJECT_ID"

# Create the repository and service account on the first deployment only.
gcloud artifacts repositories create "$REPOSITORY" \
  --repository-format=docker --location="$REGION" --project="$PROJECT_ID"
gcloud iam service-accounts create hakoniwa-run \
  --display-name="Hakoniwa Cloud Run" --project="$PROJECT_ID"

gcloud auth configure-docker "$REGION-docker.pkg.dev"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$SERVICE:$(git rev-parse --short HEAD)"
docker buildx build --platform linux/amd64 --tag "$IMAGE" --push .
```

The existing `Dockerfile` listens on port `8787`. The `.dockerignore` file excludes the local `.env` and `data` from the build context.

## 2. Deploy with IAP enabled

```bash
gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
  --service-account="$RUNTIME_SA" --port=8787 \
  --no-allow-unauthenticated --invoker-iam-check --iap \
  --min=0 --max=1 --no-cpu-throttling --memory=1Gi --timeout=900s \
  --set-env-vars="HAKONIWA_DB=/tmp/hakoniwa.sqlite3,HAKONIWA_LLM=mock,HAKONIWA_SANDBOX=process,HAKONIWA_ALLOW_UNSAFE_SANDBOX=0"
```

`--max=1` limits the instance count for the SQLite demo. `--min=0` lets the service go down to no instance at all, so it costs nothing while nobody uses it. `--no-cpu-throttling` gives the instance its CPU between requests too, so runs move at full speed while it is up. [Cloud Run billing settings](https://docs.cloud.google.com/run/docs/configuring/billing-settings) · [Instance autoscaling](https://docs.cloud.google.com/run/docs/about-instance-autoscaling)

What `--min=0` means in practice:

- **The instance stops when it is idle**, at most 15 minutes after its last request and possibly sooner. Cloud Run calls an instance idle when it is not answering a request, even if a run is going on in the background.
- **An open run page keeps it awake** (the page asks for news every second or so). With the browser closed, a run is cut off when the instance stops. It is not lost if the data is kept in a bucket: the run is paused at its last tick and goes on when you press Run.
- **Each stop empties `/tmp`.** Without [a bucket](#keep-the-data-in-a-bucket) the next visitor finds only the bundled examples.
- If runs must go on with the browser closed, use `--min=1` instead. The instance is then billed around the clock (see [What it costs](#what-it-costs)).

If Google Cloud requires the console to enable IAP for the first time, which can happen for projects outside an organization, omit `--iap` from the deployment command to create a service that requires authentication. In the console, open **Cloud Run → your service → Security**, select **Require authentication → Identity-Aware Proxy (IAP)**, and save. Check the project's OAuth configuration if you intend to grant access outside your organization. [First-time setup and external access](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

Grant the IAP service agent permission to invoke Cloud Run, then grant each listed principal access through IAP.

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

gcloud run services add-iam-policy-binding "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-iap.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

for member in "${IAP_MEMBERS[@]}"; do
  gcloud iap web add-iam-policy-binding \
    --project="$PROJECT_ID" --region="$REGION" --resource-type=cloud-run --service="$SERVICE" \
    --member="$member" --role="roles/iap.httpsResourceAccessor" || break
done
```

If the service agent is missing, configure IAP in the console or create the service identity with `gcloud beta services identity create --service=iap.googleapis.com --project="$PROJECT_ID"`, then rerun the IAM commands. [Create a service identity](https://docs.cloud.google.com/sdk/gcloud/reference/beta/services/identity/create)

## 3. Verify access

```bash
gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION"
URL=$(gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
printf '%s\n' "$URL"
curl -sS -o /dev/null -w '%{http_code}\n' "$URL/api/info"
```

1. Confirm that the service details show `Iap Enabled: true`.
2. Confirm that a request without a signed-in session redirects to sign-in or is denied.
3. Open the URL in a browser, sign in with an authorized Google account, and start a bundled example. If you included a Google group, verify access with a group member. Also verify that an account outside the allowed list is denied.

## How much CPU and memory

Memory is what matters; CPU hardly does. On Cloud Run the files in `/tmp` live in memory, so the database counts against the instance's memory along with the program.

Measured on a laptop with the settings of this guide (no AI, bundled examples; Cloud Run will differ a little):

| What | Measured |
|---|---|
| The program, idle | about 50 MB |
| The program during a run | 85 to 120 MB; 180 MB with four runs at once |
| CPU for one whole run with fixed rules | 0.5 to 1.6 CPU-seconds (with AI residents the instance mostly waits for the API) |
| What one run adds to the database | 12 to 24 MB (every tick's full state is kept so that any tick can be forked) |
| A backup copy, or exporting everything | a temporary copy the size of the database, plus the compressed file (about a tenth of it) |

A rule of thumb for the instance's memory:

```
memory  ≈  200 MB  +  database size × 2.1
```

The factor 2.1 is for the moment a copy is made (the backup folder, or exporting everything). With about 18 MB per run:

| `--memory` | Database that fits | Roughly |
|---|---|---|
| `512Mi` (the least Cloud Run allows with these settings) | about 150 MB | 8 runs |
| `1Gi` (used in this guide) | about 390 MB | 20 runs |
| `2Gi` | about 870 MB | 45 runs |

- **CPU:** the default of 1 vCPU is plenty.
- **When it fills up**, the instance is stopped for using too much memory and the database in `/tmp` is gone. Remove runs you no longer need from **History** before that. Removing a run frees room inside the database file for new runs; the file itself does not shrink.
- Worlds with more people or more ticks than the bundled examples add more per run. The **Data** dialog shows the size of every run.

### What it costs

With `--min=0` an instance is billed from the moment it starts until it is stopped, including the idle minutes before the stop (at least one minute each time), and nothing is billed while there is no instance.

| | Free each month (instance-based billing) | That is, at 1 vCPU and 1 GiB |
|---|---|---|
| CPU | 240,000 vCPU-seconds | about 66 hours of the instance being up |
| Memory | 450,000 GiB-seconds | about 125 hours |

So an occasional demo stays inside the free tier: about 66 hours a month, a little over two hours a day. Beyond that, at Tier 1 prices (Tokyo is a Tier 1 region; $0.000018 per vCPU-second and $0.000002 per GiB-second) an hour of the instance being up costs about $0.07. Memory is the small part: `2Gi` instead of `1Gi` adds less than a cent an hour and halves the free memory hours. The free tier is shared by everything on the billing account. Check the [pricing page](https://cloud.google.com/run/pricing) for current figures.

With `--min=1` the instance is up around the clock: 2,592,000 seconds in a 30-day month, of which the free tier covers about 3 days of CPU, and roughly $47 a month.

Do not drop `--no-cpu-throttling` to save more. Without it CPU is given only while a request is being answered, and runs are background work: they would crawl or stall. [Background activity](https://docs.cloud.google.com/run/docs/tips/general)

## Keep the data in a bucket

Recommended with `--min=0`, where the instance stops whenever it is idle. Cloud Run on its own keeps no files. With one Cloud Storage bucket mounted as a volume, Hakoniwa can keep a whole copy of its database outside the instance. No database service, VPC or file server is needed.

How it works: the live database stays in `/tmp`. Hakoniwa writes one complete, compressed copy (`hakoniwa-backup.sqlite3.gz`) into the folder named by `HAKONIWA_BACKUP_DIR` at three kinds of moment:

1. **When something has just been completed**: a run finishes, pauses or fails, a world is built, a file is brought in.
2. **Every few minutes** when something has changed, which covers a long run that is still going.
3. **Once more when the instance is told to stop.** This one is a last resort, not the plan: it has ten seconds and does not happen at all after a crash.

A new instance that finds no database starts from the copy. None of this runs unless `HAKONIWA_BACKUP_DIR` is set.

Do not point `HAKONIWA_DB` at the mount. A mounted bucket has no file locking, is not a POSIX file system, and writes whole objects; Google's documentation says it should not be used as the backend for a database. Copying a finished file there is what it is for. [Cloud Storage volume mounts](https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts) · [Cloud Storage FUSE limitations](https://docs.cloud.google.com/storage/docs/cloud-storage-fuse/overview)

```bash
BUCKET="$PROJECT_ID-hakoniwa-data"

# Create the bucket and let the runtime service account write to it (first time only).
gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT_ID" --location="$REGION" \
  --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$RUNTIME_SA" --role="roles/storage.objectUser"

gcloud run services update "$SERVICE" --project="$PROJECT_ID" --region="$REGION" \
  --add-volume="name=hakoniwa-data,type=cloud-storage,bucket=$BUCKET" \
  --add-volume-mount="volume=hakoniwa-data,mount-path=/mnt/hakoniwa" \
  --update-env-vars="HAKONIWA_BACKUP_DIR=/mnt/hakoniwa,HAKONIWA_BACKUP_MINUTES=5"
```

What to know:

- **Keep `--max=1`.** With more than one instance the last copy written wins and the others are lost.
- **A normal stop, including every idle stop, gets one last copy**: Cloud Run sends SIGTERM and allows 10 seconds. On a laptop, copying a 150 MB database took about 2.5 seconds before the upload to the bucket; a much larger one may not make it, so the timed copies matter. **Up to `HAKONIWA_BACKUP_MINUTES` of work can be lost** if the instance crashes or runs out of memory. [Container lifecycle](https://docs.cloud.google.com/run/docs/container-contract)
- **Memory.** The database in `/tmp` uses instance memory, and making a copy briefly needs about as much again. Raise `--memory` as the database grows, or remove old runs.
- **Volume mounts use the second-generation execution environment**, which Cloud Run selects by itself and which needs at least 512 MiB of memory.
- The **Data** dialog shows the folder, the time and size of the last copy, and a **Copy now** button.

This flow was tested with an ordinary local folder standing in for the mount (stop the server, delete the database, start again: the runs are back). It has not been tested on Cloud Run by the authors of this guide; the `gcloud` flags were checked against the documentation linked above.

## Optional. Enable AI for the bundled examples

This demo setup supports AI for residents and reports in the bundled examples. Designing and running AI-generated Python models requires an isolated sandbox. Use a sandbox separate from Cloud Run or run with [Docker Compose](../README.md#-quick-start). Worlds brought in through **Data** count as AI-generated: their history can be viewed here, but new runs of them will not start in this setup.

Enter the API key in Bash and store it in Secret Manager. Grant the runtime service account read access to this secret. If you already have a secret, skip creation and use its actual version number in the last command. Unless you keep the data in a bucket, save any data you want to keep before updating. [Configure secrets in Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

```bash
SECRET="hakoniwa-openai-key"
gcloud services enable secretmanager.googleapis.com --project="$PROJECT_ID"
read -r -s -p 'OpenAI API key: ' HAKONIWA_OPENAI_KEY
printf '\n'
printf '%s' "$HAKONIWA_OPENAI_KEY" | gcloud secrets create "$SECRET" \
  --project="$PROJECT_ID" --replication-policy=automatic --data-file=-
unset HAKONIWA_OPENAI_KEY

gcloud secrets add-iam-policy-binding "$SECRET" --project="$PROJECT_ID" \
  --member="serviceAccount:$RUNTIME_SA" --role="roles/secretmanager.secretAccessor"
gcloud run services update "$SERVICE" --project="$PROJECT_ID" --region="$REGION" \
  --update-env-vars="HAKONIWA_LLM=auto" --update-secrets="OPENAI_API_KEY=$SECRET:1"
```
