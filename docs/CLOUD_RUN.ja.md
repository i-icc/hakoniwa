# Cloud Run に IAP 付きでデプロイする

同梱サンプルを試せる Hakoniwa を、Google アカウントでアクセスを許可した人に共有します。Cloud Run サービスで IAP を有効にします。許可された利用者は、同じ世界・実行履歴を閲覧、変更できます。 [Cloud Run の IAP 設定](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

この構成はデモ向けです。SQLite はインスタンス内の `/tmp` に置くため、インスタンスの交換や再デプロイで消えます。「データ」メニューがある版では、残したい実行を SQLite に書き出してから更新し、更新後に取り込めます。HTTP/1 の取り込みリクエストには 32 MiB の上限があります。 [Cloud Run のファイルシステム](https://docs.cloud.google.com/run/docs/container-contract#file-system) · [リクエスト上限](https://docs.cloud.google.com/run/quotas#request-limits-for-cloud-run)

## 1. プロジェクトとイメージを用意する

課金を有効にした Google Cloud プロジェクト、`gcloud`、Docker を用意します。実行者には、サービスのデプロイと IAM 設定、Artifact Registry への push、実行用サービスアカウントの使用に必要な権限を付与してください。 [Cloud Run の IAM ロール](https://docs.cloud.google.com/run/docs/reference/iam/roles) · [Artifact Registry への push](https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling)

リポジトリのルートで、プロジェクト ID とアクセスを許可するメールアドレスを入れて実行します。グループを許可する場合は `IAP_MEMBER` を `group:グループのメールアドレス` にしてください。

```bash
PROJECT_ID="your-project-id"
REGION="asia-northeast1"
SERVICE="hakoniwa"
REPOSITORY="hakoniwa"
IAP_MEMBER="user:you@example.com"
RUNTIME_SA="hakoniwa-run@$PROJECT_ID.iam.gserviceaccount.com"

gcloud auth login
gcloud services enable run.googleapis.com artifactregistry.googleapis.com iap.googleapis.com \
  --project="$PROJECT_ID"

# リポジトリとサービスアカウントの作成は初回のみ
gcloud artifacts repositories create "$REPOSITORY" \
  --repository-format=docker --location="$REGION" --project="$PROJECT_ID"
gcloud iam service-accounts create hakoniwa-run \
  --display-name="Hakoniwa Cloud Run" --project="$PROJECT_ID"

gcloud auth configure-docker "$REGION-docker.pkg.dev"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$SERVICE:$(git rev-parse --short HEAD)"
docker buildx build --platform linux/amd64 --tag "$IMAGE" --push .
```

既存の `Dockerfile` はポート `8787` で待ち受けます。`.dockerignore` により、ローカルの `.env` と `data` はビルド対象から外れます。

## 2. IAP を有効にしてデプロイする

```bash
gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
  --service-account="$RUNTIME_SA" --port=8787 \
  --no-allow-unauthenticated --invoker-iam-check --iap \
  --min=1 --max=1 --no-cpu-throttling --memory=1Gi --timeout=900s \
  --set-env-vars="HAKONIWA_DB=/tmp/hakoniwa.sqlite3,HAKONIWA_LLM=mock,HAKONIWA_SANDBOX=process,HAKONIWA_ALLOW_UNSAFE_SANDBOX=0"
```

`--max=1` は SQLite を使うデモのインスタンス数を抑えるためです。`--min=1 --no-cpu-throttling` で画面を閉じている間もバックグラウンドの実行に CPU を割り当てます。アイドル時にもインスタンス料金が発生します。 [Cloud Run の課金設定](https://docs.cloud.google.com/run/docs/configuring/billing-settings)

組織に属さないプロジェクトなどで、初回の IAP 有効化に Google Cloud コンソールが必要と表示された場合は、上のコマンドから `--iap` だけを外し、認証必須のサービスを作成します。コンソールの **Cloud Run → サービス → セキュリティ** で **認証を必須にする → Identity-Aware Proxy (IAP)** を選んで保存します。組織外のアカウントを許可する場合は、プロジェクトの OAuth 設定も確認してください。 [初回設定と組織外アクセス](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

続いて、IAP サービスエージェントに Cloud Run 呼び出し権限を、利用者に IAP のアクセス権限を付与します。

```bash
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

gcloud run services add-iam-policy-binding "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-iap.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

gcloud iap web add-iam-policy-binding \
  --project="$PROJECT_ID" --region="$REGION" --resource-type=cloud-run --service="$SERVICE" \
  --member="$IAP_MEMBER" --role="roles/iap.httpsResourceAccessor"
```

サービスエージェントが見つからない場合は、コンソールで IAP を設定するか、CLI でサービス ID を作成してから権限付与を再実行します。CLI では `gcloud beta services identity create --service=iap.googleapis.com --project="$PROJECT_ID"` を使います。 [サービス ID の作成](https://docs.cloud.google.com/sdk/gcloud/reference/beta/services/identity/create)

## 3. アクセスを確認する

```bash
gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION"
URL=$(gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
printf '%s\n' "$URL"
curl -sS -o /dev/null -w '%{http_code}\n' "$URL/api/info"
```

1. サービスの詳細に `Iap Enabled: true` が表示されていることを確認します。
2. 未ログインのリクエストでは、ログインへのリダイレクトかアクセス拒否が返ることを確認します。
3. ブラウザーで URL を開き、許可した Google アカウントでサインインして、同梱サンプルの実行を開始します。別の許可していないアカウントでもアクセスが拒否されることを確認できます。

## オプションでサンプルの AI を有効にする

この簡易構成では、サンプルの住人やレポートに AI を使えます。AI が生成した Python モデルの設計・実行には隔離環境が必要です。Cloud Run と別に隔離したサンドボックスを用意するか、[Docker Compose](../Readme.jp.md#-クイックスタート) で動かしてください。

Bash でキーを入力し、Secret Manager に保存します。実行用サービスアカウントにこのシークレットだけの読み取り権限を付けます。既存のシークレットを使う場合は作成を省き、最後のコマンドで実際のバージョン番号を指定します。更新に先立ち、必要な SQLite データを書き出してください。 [Cloud Run のシークレット設定](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

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
