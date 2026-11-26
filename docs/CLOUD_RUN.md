# Deploy to Cloud Run with IAP

[日本語](./CLOUD_RUN.ja.md)

Deploy Hakoniwa with its bundled examples and share it with specific Google accounts. This guide enables Identity-Aware Proxy (IAP) directly on the Cloud Run service. Authorized users can view and modify the same worlds and run history. [Configure IAP for Cloud Run](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

This setup is intended for demos. SQLite lives in the instance's `/tmp` directory, so the database is lost when the instance is replaced or the service is redeployed. If your version has a **Data** menu, export the runs you want to keep as SQLite before updating and import them afterward. HTTP/1 import requests have a 32 MiB limit. [Cloud Run file system](https://docs.cloud.google.com/run/docs/container-contract#file-system) · [Request limits](https://docs.cloud.google.com/run/quotas#request-limits-for-cloud-run)

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
  --min=1 --max=1 --no-cpu-throttling --memory=1Gi --timeout=900s \
  --set-env-vars="HAKONIWA_DB=/tmp/hakoniwa.sqlite3,HAKONIWA_LLM=mock,HAKONIWA_SANDBOX=process,HAKONIWA_ALLOW_UNSAFE_SANDBOX=0"
```

`--max=1` limits the instance count for the SQLite demo. `--min=1 --no-cpu-throttling` keeps CPU available for background runs when the browser is closed. Cloud Run charges for the instance while idle. [Cloud Run billing settings](https://docs.cloud.google.com/run/docs/configuring/billing-settings)

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

## Optional. Enable AI for the bundled examples

This demo setup supports AI for residents and reports in the bundled examples. Designing and running AI-generated Python models requires an isolated sandbox. Use a sandbox separate from Cloud Run or run with [Docker Compose](../README.md#-quick-start).

Enter the API key in Bash and store it in Secret Manager. Grant the runtime service account read access to this secret. If you already have a secret, skip creation and use its actual version number in the last command. Export any SQLite data you want to keep before updating. [Configure secrets in Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

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
