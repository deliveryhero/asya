---
title: Dataset visualization tool for image pair browsing and labeling
status: open
priority: 1 # high
tags: [tier-1, autoresearch, tier-1, dataset, visualization]
---

## Context

For the over-upscaling classifier task: ~5K original food images, each with N
generated upscaled versions at different quality levels. Need to browse them in
a grid, visually identify where quality degrades, and one-click label pairs as
"good upscale" or "over-upscaled."

## Requirements

- Spreadsheet-like grid view: rows = original images, columns = generation variants
- Side-by-side image comparison (original vs upscaled)
- One-click labeling: good / over-upscaled / skip
- Filter by label, sort by metadata (e.g., predicted quality score from VLM)
- Export labels as CSV/JSON (for training pipeline)
- Runs locally on workbench (no hosted service for tier 1)
- Works with images on S3 (mounted via S3 Mountpoint CSI or loaded to local)

## Options

### FiftyOne (Voxel51) — Recommended

- Purpose-built for CV dataset exploration
- Grid view, filtering, tagging, comparison views
- `pip install fiftyone`, load dataset, `fo.launch_app()`
- Supports custom fields (generation params, quality scores)
- One-click tagging in web UI
- Can handle 5K+ images easily
- Optional: VLM pre-labeling → load scores → review in FiftyOne

### Streamlit (DIY)

- More control over exact layout (custom grid with N variants per row)
- More work to build (~200 lines for image grid + labeling buttons)
- Better for highly custom workflows

### Label Studio

- Full labeling platform, comparison templates available
- Overkill for quick annotation, but good if labeling scales beyond 5K

## Recommendation

Start with **FiftyOne** for tier 1. If the grid layout doesn't match the
"original + N variants in a row" pattern well enough, build a thin Streamlit
app on top of the same data.

## VLM Pre-Labeling Pipeline

1. Load images into FiftyOne dataset
2. Run VLM (Claude/GPT-4V) on each pair: "Is this image over-upscaled?"
3. Store VLM scores as FiftyOne fields
4. Sort by VLM confidence, review uncertain cases manually
5. Export cleaned labels

This could be a simple Python script or an Asya flow (for parallelizing VLM
calls across many images).

## Deliverables

1. FiftyOne dataset loading script (reads S3 image paths + metadata)
2. VLM pre-labeling script (optional, can run as Asya flow)
3. Label export script (FiftyOne → CSV for training pipeline)
