# Cloud Run に IAP つきでデプロイする

[English](./CLOUD_RUN.md)

Hakoniwa を同梱のサンプルごとデプロイし、特定の Google アカウントにだけ見せる手順です。Cloud Run のサービスに Identity-Aware Proxy（IAP）を直接有効にします。許可された人は、同じ世界と実行の履歴を見て、操作できます。[Cloud Run の IAP を設定する](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

この構成はデモ向けです。SQLite はインスタンスの `/tmp` に置くので、インスタンスが止まる（下の設定では、しばらく誰も使わないと止まります）、入れ替わる、サービスを再デプロイする、のいずれかでデータベースは消えます。また、その分インスタンスのメモリを使います。残したいものを保つ方法は 2 つあります。

- **手で残す。** ヘッダーの **データ** を開き、更新の前に、残したい世界と実行を 1 つの SQLite ファイルに書き出します。更新のあとで読み込みます。Cloud Run への HTTP/1 リクエストは 32 MiB までです。住人 500 人ほどの実行 1 回は、圧縮して 3 MB 前後です。
- **自動で残す。** Cloud Storage のバケットをマウントして、Hakoniwa にデータベース丸ごとの控えを取らせます。[データをバケットに残す](#データをバケットに残す)を見てください。

[Cloud Run のファイルシステム](https://docs.cloud.google.com/run/docs/container-contract#file-system) · [リクエストの上限](https://docs.cloud.google.com/run/quotas#request-limits-for-cloud-run)

## 1. プロジェクトとイメージを用意する

必要なものは、課金が有効な Google Cloud プロジェクト、`gcloud`、Docker です。デプロイする人には、サービスのデプロイ、IAM の設定、Artifact Registry への push、実行用サービスアカウントの利用の権限が要ります。[Cloud Run の IAM ロール](https://docs.cloud.google.com/run/docs/reference/iam/roles) · [Artifact Registry への push](https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling)

コマンドは、リポジトリのルートで Bash から実行します。プロジェクト ID を入れ、`IAP_MEMBERS` に IAP で許可する相手を 1 行に 1 つずつ書きます。Google アカウントは `user:メール`、Google グループは `group:メール` です。

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

# リポジトリとサービスアカウントは、最初のデプロイのときだけ作ります。
gcloud artifacts repositories create "$REPOSITORY" \
  --repository-format=docker --location="$REGION" --project="$PROJECT_ID"
gcloud iam service-accounts create hakoniwa-run \
  --display-name="Hakoniwa Cloud Run" --project="$PROJECT_ID"

gcloud auth configure-docker "$REGION-docker.pkg.dev"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$SERVICE:$(git rev-parse --short HEAD)"
docker buildx build --platform linux/amd64 --tag "$IMAGE" --push .
```

同梱の `Dockerfile` はポート `8787` で待ち受けます。`.dockerignore` が、手元の `.env` と `data` をビルドの対象から外します。

## 2. IAP を有効にしてデプロイする

```bash
gcloud run deploy "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" --image="$IMAGE" \
  --service-account="$RUNTIME_SA" --port=8787 \
  --no-allow-unauthenticated --invoker-iam-check --iap \
  --min=0 --max=1 --no-cpu-throttling --memory=1Gi --timeout=900s \
  --set-env-vars="HAKONIWA_DB=/tmp/hakoniwa.sqlite3,HAKONIWA_LLM=mock,HAKONIWA_SANDBOX=process,HAKONIWA_ALLOW_UNSAFE_SANDBOX=0"
```

`--max=1` は、SQLite のデモなのでインスタンスを 1 つに限るためです。`--min=0` にすると、サービスはインスタンスが 0 の状態まで縮むので、誰も使っていない間は費用がかかりません。`--no-cpu-throttling` は、リクエストの合間にもインスタンスに CPU を割り当てるためです。インスタンスが動いている間、実行は本来の速さで進みます。[Cloud Run の課金設定](https://docs.cloud.google.com/run/docs/configuring/billing-settings) · [インスタンスの自動スケーリング](https://docs.cloud.google.com/run/docs/about-instance-autoscaling)

`--min=0` で実際に起こること：

- **使われていないと、インスタンスは止まります。** 最後のリクエストから長くて 15 分後で、もっと早いこともあります。Cloud Run は、リクエストに応えていないインスタンスを「使われていない」とみなします。裏で実行が進んでいても同じです。
- **実行のページを開いている間は、止まりません**（ページが 1 秒おきくらいに様子を聞きに行くためです）。ブラウザを閉じると、インスタンスが止まった時点で実行は途中で切れます。データをバケットに残していれば失われません。実行は最後のティックで一時停止の状態になり、「進める」を押せば続きます。
- **止まるたびに `/tmp` は空になります。** [バケット](#データをバケットに残す)を使わない場合、次に開いた人が見るのは同梱のサンプルだけです。
- ブラウザを閉じても実行を続けたいなら、代わりに `--min=1` を使います。その場合、インスタンスは常に課金されます（[かかる費用](#かかる費用)を参照）。

組織に属さないプロジェクトなどでは、初回の IAP 有効化をコンソールで行うよう求められることがあります。その場合は、デプロイのコマンドから `--iap` を外して、認証が必要なサービスとして作ります。コンソールで **Cloud Run → 対象のサービス → セキュリティ** を開き、**認証が必要 → Identity-Aware Proxy（IAP）** を選んで保存します。組織の外の人に見せるつもりなら、プロジェクトの OAuth の設定も確かめてください。[初回の設定と、組織外からのアクセス](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

IAP のサービスエージェントに Cloud Run を呼び出す権限を付け、そのあと、列挙した相手に IAP 経由のアクセスを許可します。

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

サービスエージェントがまだない場合は、コンソールで IAP を設定するか、`gcloud beta services identity create --service=iap.googleapis.com --project="$PROJECT_ID"` で作ってから、IAM のコマンドをやり直します。[サービス ID を作る](https://docs.cloud.google.com/sdk/gcloud/reference/beta/services/identity/create)

## 3. アクセスを確かめる

```bash
gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION"
URL=$(gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)')
printf '%s\n' "$URL"
curl -sS -o /dev/null -w '%{http_code}\n' "$URL/api/info"
```

1. サービスの詳細に `Iap Enabled: true` と出ることを確かめます。
2. サインインしていないリクエストが、サインインへ転送されるか、拒否されることを確かめます。
3. ブラウザで URL を開き、許可した Google アカウントでサインインして、同梱のサンプルを動かします。Google グループを入れた場合は、グループのメンバーで確かめます。許可していないアカウントが拒否されることも確かめます。

## 必要な CPU とメモリ

効くのはメモリで、CPU はほとんど要りません。Cloud Run では `/tmp` のファイルはメモリ上にあるので、データベースも、プログラムと一緒にインスタンスのメモリを使います。

この手順の設定（AI なし、同梱のサンプル）で、ノート PC 上で測った値です。Cloud Run では少し違うはずです。

| 項目 | 実測 |
|---|---|
| プログラム（待機中） | 約 50 MB |
| プログラム（実行中） | 85〜120 MB。4 つ同時に実行して 180 MB |
| 規則だけの実行 1 回ぶんの CPU | 0.5〜1.6 CPU 秒（AI の住人を使う場合、インスタンスはほぼ API の返事待ち） |
| 実行 1 回でデータベースが増える量 | 12〜24 MB（どのティックからでも分岐できるよう、毎ティックの状態を丸ごと残すため） |
| 控えを取るとき、全部を書き出すとき | データベースと同じ大きさの一時コピー ＋ 圧縮したファイル（その約 10 分の 1） |

インスタンスのメモリの目安：

```
メモリ  ≈  200 MB  ＋  データベースの大きさ × 2.1
```

2.1 倍は、コピーを作る瞬間のぶんです（控えの保存先を使うとき、全部を書き出すとき）。実行 1 回を約 18 MB とすると、次のようになります。

| `--memory` | 収まるデータベース | おおよそ |
|---|---|---|
| `512Mi`（この設定で Cloud Run が許す下限） | 約 150 MB | 実行 8 回 |
| `1Gi`（この手順で使っている値） | 約 390 MB | 実行 20 回 |
| `2Gi` | 約 870 MB | 実行 45 回 |

- **CPU：** 既定の 1 vCPU で十分です。
- **いっぱいになると**、メモリの使いすぎでインスタンスが止められ、`/tmp` のデータベースは消えます。その前に、**履歴** から不要な実行を消してください。実行を消すと、データベースのファイルの中に、新しい実行のための空きができます。ファイル自体は小さくなりません。
- 同梱のサンプルより人数やティック数の多い世界は、実行 1 回あたりの増え方も大きくなります。**データ** のダイアログで、実行ごとの大きさを確かめられます。

### かかる費用

`--min=0` では、インスタンスが起動してから止められるまでが課金の対象です。止まる前の「使われていない数分」も含みます（1 回あたり最低 1 分）。インスタンスが 0 の間は課金されません。

| | 毎月の無料枠（インスタンスベースの課金） | 1 vCPU・1 GiB の場合 |
|---|---|---|
| CPU | 240,000 vCPU 秒 | インスタンスが動いている時間で約 66 時間 |
| メモリ | 450,000 GiB 秒 | 約 125 時間 |

つまり、ときどき使うデモなら無料枠に収まります。月に約 66 時間、1 日あたり 2 時間あまりです。それを超えた分は、Tier 1 の単価（東京は Tier 1 のリージョンです。1 vCPU 秒 $0.000018、1 GiB 秒 $0.000002）で、インスタンスが動いている 1 時間あたり約 $0.07 です。メモリの分は小さく、`1Gi` を `2Gi` にしても 1 時間あたり 1 セント未満の増加です（メモリの無料時間は半分になります）。無料枠は、請求先アカウントの中のすべてで共有されます。最新の数字は[料金ページ](https://cloud.google.com/run/pricing)で確かめてください。

`--min=1` にすると、インスタンスは常に動きます。30 日で 2,592,000 秒になり、無料枠で賄える CPU は約 3 日ぶん、費用は月におよそ $47 です。

もっと節約しようとして `--no-cpu-throttling` を外すのは、おすすめしません。外すと、CPU はリクエストに応えている間しか割り当てられません。実行は裏で進む処理なので、ほとんど進まないか、止まります。[バックグラウンドの処理](https://docs.cloud.google.com/run/docs/tips/general)

## データをバケットに残す

`--min=0` では、使われていないとインスタンスが止まるので、この設定をおすすめします。Cloud Run だけでは、ファイルは残りません。Cloud Storage のバケットを 1 つ、ボリュームとしてマウントすれば、Hakoniwa がデータベース丸ごとの控えをインスタンスの外に置けます。データベースのサービス、VPC、ファイルサーバーは要りません。

仕組み：動いているデータベースは `/tmp` に置いたままです。`HAKONIWA_BACKUP_DIR` で指定したフォルダへ、圧縮した完全な控え（`hakoniwa-backup.sqlite3.gz`）を 1 つ書きます。書くタイミングは 3 種類です。

1. **キリのいいとき。** 実行が終わった・一時停止した・失敗したとき、世界ができたとき、ファイルを読み込んだとき。
2. **数分ごと。** 変更があった場合だけです。長い実行が進んでいる最中を、これで拾います。
3. **インスタンスが停止を告げられたときに、もう一度。** これは最後の保険で、当てにするものではありません。猶予は 10 秒で、異常終了のときはそもそも走りません。

新しいインスタンスは、データベースがなければ控えから始めます。`HAKONIWA_BACKUP_DIR` を設定していなければ、これらは一切動きません。

`HAKONIWA_DB` をマウント先に向けてはいけません。マウントしたバケットにはファイルのロックがなく、POSIX のファイルシステムではなく、オブジェクトを丸ごと書き込みます。Google のドキュメントも、データベースの置き場所に使うべきではないとしています。出来上がったファイルをコピーする使い方なら問題ありません。[Cloud Storage のボリュームマウント](https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts) · [Cloud Storage FUSE の制限](https://docs.cloud.google.com/storage/docs/cloud-storage-fuse/overview)

```bash
BUCKET="$PROJECT_ID-hakoniwa-data"

# バケットを作り、実行用サービスアカウントが書き込めるようにします（最初だけ）。
gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT_ID" --location="$REGION" \
  --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$RUNTIME_SA" --role="roles/storage.objectUser"

gcloud run services update "$SERVICE" --project="$PROJECT_ID" --region="$REGION" \
  --add-volume="name=hakoniwa-data,type=cloud-storage,bucket=$BUCKET" \
  --add-volume-mount="volume=hakoniwa-data,mount-path=/mnt/hakoniwa" \
  --update-env-vars="HAKONIWA_BACKUP_DIR=/mnt/hakoniwa,HAKONIWA_BACKUP_MINUTES=5"
```

知っておくこと：

- **`--max=1` のままにします。** インスタンスが 2 つ以上あると、最後に書いた控えだけが残り、ほかは失われます。
- **通常の停止では、最後にもう一度控えを取ります。** 使われていないことによる停止も同じです。Cloud Run は SIGTERM を送ってから 10 秒待ちます。ノート PC では、150 MB のデータベースの控えを作るのに約 2.5 秒かかりました（バケットへのアップロードを除く）。ずっと大きなデータベースは間に合わないことがあるので、定期的な控えが大事です。インスタンスが異常終了したり、メモリを使い切ったりした場合は、**最大で `HAKONIWA_BACKUP_MINUTES` 分の作業が失われることがあります。** [コンテナのライフサイクル](https://docs.cloud.google.com/run/docs/container-contract)
- **メモリ。** `/tmp` のデータベースはインスタンスのメモリを使います。控えを作る間は、一時的にほぼ同じ量がもう一度要ります。データベースが大きくなったら `--memory` を上げるか、古い実行を消してください。
- **ボリュームのマウントには第 2 世代の実行環境が要ります。** Cloud Run が自動で選びます。メモリは 512 MiB 以上が必要です。
- **データ** のダイアログに、保存先、最後の控えの時刻と大きさ、**今すぐ控えを取る** ボタンが出ます。

この流れは、マウントの代わりに手元の普通のフォルダを使って確かめました（サーバーを止め、データベースを消し、起動し直すと、実行が戻っている）。この手順書の作成者は、Cloud Run 上では試していません。`gcloud` のフラグは、上にリンクしたドキュメントと照らし合わせてあります。

## 任意：同梱のサンプルで AI を使う

このデモ構成では、同梱のサンプルの住人とレポートに AI を使えます。AI が書いた Python のモデルを設計して動かすには、隔離されたサンドボックスが要ります。Cloud Run とは別のサンドボックスを使うか、[Docker Compose](../README.ja.md#-始め方) で動かしてください。**データ** から読み込んだ世界は、AI が作った世界として扱われます。この構成では、履歴は見られますが、新しい実行は始まりません。

API キーは Bash で入力して、Secret Manager に入れます。実行用サービスアカウントに、このシークレットの読み取りを許可します。すでにシークレットがある場合は、作成を飛ばし、最後のコマンドで実際のバージョン番号を使います。データをバケットに残していない場合は、更新の前に、残したいデータを書き出してください。[Cloud Run でシークレットを設定する](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

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
