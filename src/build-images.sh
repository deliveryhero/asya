#!/bin/bash

# Build script for Asya Docker images
# Usage: ./src/build-images.sh [OPTIONS] [IMAGE:TAG ...]
# Examples:
#   ./src/build-images.sh                                    # Build all images
#   ./src/build-images.sh asya-operator:latest               # Build only operator
#   ./src/build-images.sh asya-operator asya-sidecar         # Build operator and sidecar (with default tag)

set -euo pipefail

# Enable Docker BuildKit for cache mounts
export DOCKER_BUILDKIT=1

# Default values
PUSH=false
TAG="${TAG:-latest}"
REGISTRY="${REGISTRY:-}"

# Auto-detect platform for macOS ARM64 to avoid Go 1.24 compiler segfault
if [[ "$(uname -s)" == "Darwin" ]] && [[ "$(uname -m)" == "arm64" ]]; then
  DEFAULT_PLATFORM="linux/arm64"
else
  DEFAULT_PLATFORM="linux/amd64"
fi
PLATFORM="${PLATFORM:-$DEFAULT_PLATFORM}"

IMAGE_FILTERS=()

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
      echo "Usage: $0 [OPTIONS] [IMAGE[:TAG] ...]"
      echo ""
      echo "Options:"
      echo "  --push              Push images to registry after building"
      echo "  --tag TAG           Tag for images (default: latest)"
      echo "  --registry REG      Registry prefix (e.g., docker.io/myuser)"
      echo "  --platform PLATFORM Target platform (default: linux/amd64)"
      echo ""
      echo "Image filters (optional):"
      echo "  If no images specified, builds all images. Otherwise, builds only listed images."
      echo "  Format: IMAGE[:TAG] or IMAGE (uses --tag value)"
      echo "  Examples:"
      echo "    $0                              # Build all images"
      echo "    $0 asya-operator:v1.0.0         # Build operator with specific tag"
      echo "    $0 asya-operator asya-sidecar   # Build operator and sidecar with default tag"
      echo ""
      echo "Available images:"
      echo "  - asya-operator"
      echo "  - asya-gateway"
      echo "  - asya-sidecar"
      echo "  - asya-crew"
      echo "  - asya-testing"
      echo ""
      echo "Environment variables:"
      echo "  TAG                 Image tag (default: latest)"
      echo "  REGISTRY            Registry prefix"
      echo "  PLATFORM            Target platform"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1"
      echo "Run with --help for usage information"
      exit 1
      ;;
    *)
      IMAGE_FILTERS+=("$1")
      shift
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
  local index=$4
  local total=$5
  local target=${6:-}
  local tag=${7:-$TAG}

  local image_name="${IMAGE_PREFIX}${name}:${tag}"
  local log_file
  log_file="$(mktemp -t "tmp.XXXXXX-${name}.log")"
  local progress="[$index/$total]"

  log_info "$progress Building ${image_name}, see log ${log_file}"

  local build_args=(
    "--platform" "$PLATFORM"
    "-t" "$image_name"
    "-f" "$context/$dockerfile"
  )

  if [[ -n "$target" ]]; then
    build_args+=("--target" "$target")
  fi

  build_args+=("$context")

  if docker build "${build_args[@]}" > "$log_file" 2>&1; then
    log_info "$progress Successfully built ${image_name}"
    rm -f "$log_file"

    if [[ "$PUSH" == "true" ]]; then
      log_info "$progress Pushing ${image_name}..."
      if docker push "$image_name" > "$log_file" 2>&1; then
        log_info "$progress Successfully pushed ${image_name}"
        rm -f "$log_file"
      else
        log_error "$progress Failed to push ${image_name}"
        cat "$log_file"
        rm -f "$log_file"
        return 1
      fi
    fi
  else
    log_error "$progress Failed to build ${image_name}, see log ${log_file}"
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
if [[ ${#IMAGE_FILTERS[@]} -gt 0 ]]; then
  log_info "Filtered images: ${IMAGE_FILTERS[*]}"
fi
echo ""

# Discover available images from src/ directory
declare -a ALL_IMAGES=(
  "asya-operator"
  "asya-gateway"
  "asya-sidecar"
  "asya-crew"
  "asya-testing"
)

# Filter images if specific ones are requested
declare -a IMAGES=()
if [[ ${#IMAGE_FILTERS[@]} -eq 0 ]]; then
  IMAGES=("${ALL_IMAGES[@]}")
else
  for filter in "${IMAGE_FILTERS[@]}"; do
    filter_name="${filter%%:*}"
    pattern=" $filter_name "
    if [[ ! " ${ALL_IMAGES[*]} " =~ $pattern ]]; then
      log_error "Unknown image: $filter_name"
      echo "Available images: ${ALL_IMAGES[*]}"
      exit 1
    fi
    IMAGES+=("$filter_name")
  done
fi

[[ ${#IMAGES[@]} -eq 0 ]] && log_error "No images to build" && exit 1

# Build all images in parallel
log_info "Starting parallel builds..."
FAILED_BUILDS=()
BUILD_PIDS=()
TOTAL_IMAGES=${#IMAGES[@]}

time {
  for i in "${!IMAGES[@]}"; do
    name="${IMAGES[$i]}"
    index=$((i + 1))

    # Operator needs src/ as context to access asya-runtime symlink target
    if [[ "$name" == "asya-operator" ]]; then
      build_image "$name" "src" "$name/Dockerfile" "$index" "$TOTAL_IMAGES" &
    else
      build_image "$name" "src/$name" "Dockerfile" "$index" "$TOTAL_IMAGES" &
    fi

    BUILD_PIDS+=($!)
  done

  log_info "Waiting for builds to complete..."
  for i in "${!BUILD_PIDS[@]}"; do
    wait "${BUILD_PIDS[$i]}" || FAILED_BUILDS+=("${IMAGES[$i]}")
  done
  echo "[+] All builds completed."
}

# Summary
echo ""
log_info "Build summary:"
if [[ ${#FAILED_BUILDS[@]} -eq 0 ]]; then
  log_info "All ${TOTAL_IMAGES} images built successfully!"
  exit 0
else
  log_error "Failed to build ${#FAILED_BUILDS[@]}/${TOTAL_IMAGES} image(s):"
  for img in "${FAILED_BUILDS[@]}"; do
    echo "  - $img"
  done
  exit 1
fi
