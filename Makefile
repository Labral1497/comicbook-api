# -------- config --------
PROJECT_ID ?= ai-comic-books
REGION     ?= us-central1
REPO       ?= comics-repo
SERVICE    ?= comics-api

IMAGE := $(REGION)-docker.pkg.dev/$(PROJECT_ID)/$(REPO)/$(SERVICE)
# Tag defaults to short git SHA, or timestamp if outside a git repo
TAG   ?= $(shell git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)

# Service account used by Cloud Run
SERVICE_SA ?= $(SERVICE)-sa@$(PROJECT_ID).iam.gserviceaccount.com

# Common deploy flags
DEPLOY_FLAGS = --region $(REGION) \
  --allow-unauthenticated \
  --service-account $(SERVICE_SA) \
  --cpu 2 --memory 1Gi --concurrency 80 \
  --min-instances 0 --max-instances 50 \
  --timeout 600 --port 8080 \
  --set-env-vars API_PREFIX=/api/v1,KEEP_OUTPUTS=false \
  --set-secrets OPENAI_API_KEY=OPENAI_API_KEY:latest

.PHONY: all release build deploy logs url proxy describe ensure-repo configure-docker local docker-run

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
