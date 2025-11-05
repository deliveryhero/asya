#!/bin/bash

# Build script for Asya Docker images
# Usage: ./scripts/build-images.sh [--push] [--tag TAG] [--registry REGISTRY]

set -euo pipefail

# Default values
PUSH=false
TAG="${TAG:-latest}"
REGISTRY="${REGISTRY:-}"
PLATFORM="${PLATFORM:-linux/amd64}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH=true
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
        --platform)
            PLATFORM="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --push              Push images to registry after building"
            echo "  --tag TAG           Tag for images (default: latest)"
            echo "  --registry REG      Registry prefix (e.g., docker.io/myuser)"
            echo "  --platform PLATFORM Target platform (default: linux/amd64)"
            echo ""
            echo "Environment variables:"
            echo "  TAG                 Image tag (default: latest)"
            echo "  REGISTRY            Registry prefix"
            echo "  PLATFORM            Target platform"
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
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# shellcheck disable=SC2317
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

# shellcheck disable=SC2317,SC2329
log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# shellcheck disable=SC2317
log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Build function
build_image() {
    local name=$1
    local context=$2
    local dockerfile=${3:-Dockerfile}

    local image_name="${IMAGE_PREFIX}${name}:${TAG}"

    log_info "Building ${image_name}..."

    if docker build \
        --platform "$PLATFORM" \
        -t "$image_name" \
        -f "$context/$dockerfile" \
        "$context"; then
        log_info "Successfully built ${image_name}"

        if [[ "$PUSH" == "true" ]]; then
            log_info "Pushing ${image_name}..."
            if docker push "$image_name"; then
                log_info "Successfully pushed ${image_name}"
            else
                log_error "Failed to push ${image_name}"
                return 1
            fi
        fi
    else
        log_error "Failed to build ${image_name}"
        return 1
    fi
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

log_info "Building Asya Docker images..."
log_info "Tag: ${TAG}"
log_info "Registry: ${REGISTRY:-<none>}"
log_info "Platform: ${PLATFORM}"
log_info "Push: ${PUSH}"
echo ""

# Track build status
FAILED_BUILDS=()

# Build operator
if ! build_image "asya-operator" "operator"; then
    FAILED_BUILDS+=("asya-operator")
fi

# Build gateway
if ! build_image "asya-gateway" "src/asya-gateway"; then
    FAILED_BUILDS+=("asya-gateway")
fi

# Build sidecar
if ! build_image "asya-sidecar" "src/asya-sidecar"; then
    FAILED_BUILDS+=("asya-sidecar")
fi

# Summary
echo ""
log_info "Build summary:"
if [[ ${#FAILED_BUILDS[@]} -eq 0 ]]; then
    log_info "All images built successfully!"
    exit 0
else
    log_error "Failed to build ${#FAILED_BUILDS[@]} image(s):"
    for img in "${FAILED_BUILDS[@]}"; do
        echo "  - $img"
    done
    exit 1
fi
