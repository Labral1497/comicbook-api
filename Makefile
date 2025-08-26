# -------- config --------
PROJECT_ID ?= ai-comic-books
REGION     ?= us-central1
REPO       ?= comics-repo
SERVICE    ?= comics-api
TASKS_QUEUE ?= comic-worker-queue

# GCS bucket for generated assets (override with: make ... BUCKET=my-bucket)
BUCKET     ?= ai-comic-books-assets

IMAGE := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(REPO)/$(SERVICE)
# Tag defaults to short git SHA, or timestamp if outside a git repo
TAG   ?= $(shell git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)

# Service account used by Cloud Run
SERVICE_SA ?= $(SERVICE)-sa@$(PROJECT_ID).iam.gserviceaccount.com
GCS_SIGNING_SERVICE_ACCOUNT ?= $(SERVICE_SA)
GCS_SIGNED_URL_TTL ?= 3600

# Common deploy flags
DEPLOY_FLAGS = --region $(REGION) \
  --allow-unauthenticated \
  --service-account $(SERVICE_SA) \
  --cpu 2 --memory 1Gi --concurrency 80 \
  --min-instances 0 --max-instances 50 \
  --timeout 1200 --port 8080 \
  --set-env-vars API_PREFIX=/api/v1,KEEP_OUTPUTS=false,USE_CLOUD_TASKS=true,TASKS_QUEUE=$(TASKS_QUEUE),GCS_BUCKET=$(BUCKET),GCS_SIGNED_URL_TTL=$(GCS_SIGNED_URL_TTL),GCS_SIGNING_SERVICE_ACCOUNT=$(GCS_SIGNING_SERVICE_ACCOUNT) \
  --set-secrets OPENAI_API_KEY=OPENAI_API_KEY:latest


.PHONY: all release build deploy logs url proxy describe ensure-repo configure-docker local docker-run \
        ensure-bucket bucket-iam bucket-cors bucket-lifecycle set-bucket-env gcs-status

all: release

# Build+push+deploy in one go
release: build deploy

# Build & push linux/amd64 image (for Apple Silicon hosts)
build: configure-docker
	@echo "Building $(IMAGE):$(TAG)"
	docker buildx create --use >/dev/null 2>&1 || true
	docker buildx build --platform linux/amd64 -t "$(IMAGE):$(TAG)" --push .

# Deploy the already-pushed image tag (no build here)
deploy:
	@echo "Deploying $(IMAGE):$(TAG) to Cloud Run service $(SERVICE)"
	gcloud run deploy "$(SERVICE)" --image "$(IMAGE):$(TAG)" $(DEPLOY_FLAGS)

# Tail live logs
logs:
	gcloud run services logs tail "$(SERVICE)" --region $(REGION)

# Print service URL
url:
	@gcloud run services describe "$(SERVICE)" --region $(REGION) --format='value(status.url)'

# Local uvicorn (no Docker)
local:
	python -m uvicorn server:app --host 0.0.0.0 --port 8080

# Run the built image locally
docker-run:
	docker run --rm -e PORT=8080 -p 8080:8080 "$(IMAGE):$(TAG)"

# Show current revision/env/image
describe:
	gcloud run services describe "$(SERVICE)" --region $(REGION) \
	  --format='yaml(status.url,status.latestReadyRevisionName,spec.template.spec.containers[0].image,spec.template.spec.containers[0].env)'

# One-time helpers
ensure-repo:
	gcloud artifacts repositories create "$(REPO)" --repository-format=docker --location="$(REGION)" || true

configure-docker:
	gcloud auth configure-docker "$(REGION)-docker.pkg.dev"

# ---------- GCS: bucket creation, IAM, CORS, lifecycle ----------

# Create the bucket (idempotent), enable Storage API, lock down basics
ensure-bucket:
	gcloud services enable storage.googleapis.com
	- gcloud storage buckets create gs://$(BUCKET) --project $(PROJECT_ID) --location $(REGION)
	gcloud storage buckets update gs://$(BUCKET) --uniform-bucket-level-access --pap

# Grant Cloud Run SA upload + signed-URL capability
bucket-iam:
	# allow object uploads
	gcloud storage buckets add-iam-policy-binding gs://$(BUCKET) \
	  --member="serviceAccount:$(SERVICE_SA)" \
	  --role="roles/storage.objectCreator"
	# allow V4 signed URLs without key files
	gcloud iam service-accounts add-iam-policy-binding "$(SERVICE_SA)" \
	  --member="serviceAccount:$(SERVICE_SA)" \
	  --role="roles/iam.serviceAccountTokenCreator"

# Set CORS so browsers can fetch signed URLs from your frontend origins
bucket-cors:
	@echo 'Writing cors.json'
	@printf '%s\n' '[' \
	'  {' \
	'    "origin": ["https://lovable.dev/*","https://*.lovable.app", "http://localhost:8080"],' \
	'    "method": ["GET","HEAD"],' \
	'    "responseHeader": ["Content-Type"],' \
	'    "maxAgeSeconds": 3600' \
	'  }' \
	']' > cors.json
	gcloud storage buckets update gs://$(BUCKET) --cors-file=cors.json

# Optional lifecycle: auto-delete covers after 30 days
bucket-lifecycle:
	@echo 'Writing lifecycle.json'
	@printf '%s\n' '{' \
	'  "rule": [' \
	'    { "action": {"type": "Delete"}, "condition": {"age": 30, "matchesPrefix": ["covers/"]} }' \
	'  ]' \
	'}' > lifecycle.json
	gcloud storage buckets update gs://$(BUCKET) --lifecycle-file=lifecycle.json

# Wire bucket name into the service as env var (picked up on next deploy/update)
set-bucket-env:
	gcloud run services update "$(SERVICE)" --region $(REGION) \
	  --set-env-vars GCS_BUCKET=$(BUCKET)

# Quick status for the bucket (location, IAM members)
gcs-status:
	gcloud storage buckets describe gs://$(BUCKET) --format='yaml(location,iamConfiguration,labels,metageneration)'
	gcloud storage buckets get-iam-policy gs://$(BUCKET) --format='table(bindings.role,bindings.members)'

ensure-tasks-queue:
	gcloud services enable cloudtasks.googleapis.com
	- gcloud tasks queues create $(TASKS_QUEUE) \
	    --project $(PROJECT_ID) \
	    --location $(REGION) || true

tasks-iam:
	gcloud projects add-iam-policy-binding $(PROJECT_ID) \
	  --member="serviceAccount:$(SERVICE_SA)" \
	  --role="roles/cloudtasks.enqueuer"
