#!/bin/bash

# Load Docker images into Minikube
# Usage: ./scripts/load-images-minikube.sh [--tag TAG] [--registry REGISTRY] [--build]

set -euo pipefail

# Default values
TAG="${TAG:-latest}"
REGISTRY="${REGISTRY:-}"
BUILD=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --build)
            BUILD=true
            shift
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --registry)
            REGISTRY="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Load Docker images into Minikube's Docker daemon."
            echo ""
            echo "Options:"
            echo "  --build             Build images before loading (runs build-images.sh)"
            echo "  --tag TAG           Tag for images (default: latest)"
            echo "  --registry REG      Registry prefix (e.g., docker.io/myuser)"
            echo ""
            echo "Environment variables:"
            echo "  TAG                 Image tag (default: latest)"
            echo "  REGISTRY            Registry prefix"
            echo ""
            echo "Examples:"
            echo "  $0                              # Load existing images"
            echo "  $0 --build                      # Build and load"
            echo "  $0 --tag v1.0.0                 # Load specific tag"
            echo "  $0 --build --tag dev            # Build with dev tag and load"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage information"
            exit 1
            ;;
    esac
done

# Set image prefix based on registry
if [[ -n "$REGISTRY" ]]; then
    IMAGE_PREFIX="${REGISTRY}/"
else
    IMAGE_PREFIX=""
fi

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Check if minikube is running
if ! minikube status &>/dev/null; then
    log_error "Minikube is not running. Start it with: minikube start"
    exit 1
fi

log_info "Minikube status: $(minikube status -o json | jq -r '.Host')"

# Build images if requested
if [[ "$BUILD" == "true" ]]; then
    log_info "Building images first..."
    if [[ -n "$REGISTRY" ]]; then
        TAG="$TAG" REGISTRY="$REGISTRY" ./scripts/build-images.sh
    else
        TAG="$TAG" ./scripts/build-images.sh
    fi
    echo ""
fi

# Define images to load
IMAGES=(
    "asya-operator"
    "asya-gateway"
    "asya-sidecar"
)

log_info "Loading Docker images into Minikube..."
log_info "Tag: ${TAG}"
log_info "Registry: ${REGISTRY:-<none>}"
echo ""

# Track loading status
FAILED_LOADS=()

# Load each image into minikube
for img in "${IMAGES[@]}"; do
    image_name="${IMAGE_PREFIX}${img}:${TAG}"

    log_info "Loading ${image_name}..."

    # Check if image exists locally
    if ! docker image inspect "$image_name" &>/dev/null; then
        log_warn "Image ${image_name} not found locally. Skipping..."
        FAILED_LOADS+=("$image_name (not found)")
        continue
    fi

    # Load into minikube
    if minikube image load "$image_name"; then
        log_info "Successfully loaded ${image_name}"
    else
        log_error "Failed to load ${image_name}"
        FAILED_LOADS+=("$image_name (load failed)")
    fi
done

# Summary
echo ""
log_info "Load summary:"
if [[ ${#FAILED_LOADS[@]} -eq 0 ]]; then
    log_info "All images loaded successfully into Minikube!"
    echo ""
    log_info "Verify with: minikube image ls | grep asya"
    exit 0
else
    log_warn "Some images failed to load:"
    for img in "${FAILED_LOADS[@]}"; do
        echo "  - $img"
    done
    echo ""
    log_info "Successfully loaded $((${#IMAGES[@]} - ${#FAILED_LOADS[@]})) of ${#IMAGES[@]} images"
    exit 1
fi
