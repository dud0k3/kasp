#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
MINIKUBE=${MINIKUBE:-minikube}
PROFILE=${PROFILE:-kasp}
command -v "$MINIKUBE" >/dev/null
command -v docker >/dev/null
command -v kubectl >/dev/null
if ! "$MINIKUBE" -p "$PROFILE" status >/dev/null 2>&1; then
    "$MINIKUBE" start -p "$PROFILE" --driver=docker --cpus=6 --memory=6144 --kubernetes-version=v1.34.1
fi
"$MINIKUBE" -p "$PROFILE" update-context
kubectl config use-context "$PROFILE"
docker build -t kasp-model-downloader:0.27.0 -f Dockerfile.downloader .
docker build -t kasp-vllm-cpu:0.27.0 .
docker save kasp-model-downloader:0.27.0 | "$MINIKUBE" -p "$PROFILE" image load --overwrite -
docker save kasp-vllm-cpu:0.27.0 | "$MINIKUBE" -p "$PROFILE" image load --overwrite -
PYTHON=${PYTHON:-python3}
"$PYTHON" scripts/create_secret.py
kubectl apply -k k8s
kubectl -n vllm-cpu rollout restart deployment/vllm
kubectl -n vllm-cpu rollout status deployment/vllm --timeout=1200s
echo 'Ready. Run: kubectl -n vllm-cpu port-forward service/vllm 8000:8000'
