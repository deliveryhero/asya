---
title: "Research: SOCI/Stargz lazy image loading for scale-to-zero with large ML images"
status: open
priority: 3
parent: 00000
---

Research availability of lazy image loading (SOCI, Stargz) on major cloud K8s providers for KEDA scale-to-zero with large ML images.

## Context

Large ML images (5-20GB with model weights, CUDA, frameworks) make scale-to-zero impractical — cold start is dominated by image pull time. Lazy loading (pull only the layers needed at startup) could reduce cold start from minutes to seconds.

## Questions to answer

1. **EKS**: SOCI (Seekable OCI) index support — GA? Requires specific AMI? Works with Fargate?
2. **GKE**: Stargz/eStargz support via containerd — enabled by default? Autopilot support?
3. **AKS**: Any lazy loading support? containerd configuration options?
4. **Image format**: SOCI vs eStargz vs zstd:chunked — which is becoming the standard?
5. **Build integration**: Can apko/buildpacks produce SOCI-indexed or eStargz images?
6. **Practical impact**: What cold start improvement can we expect for a 10GB ML image?

## References

- research-seamless-build.md open question #6
- AWS SOCI: https://aws.amazon.com/about-aws/whats-new/2023/07/aws-fargate-seekable-oci/
- Google eStargz: containerd stargz snapshotter
