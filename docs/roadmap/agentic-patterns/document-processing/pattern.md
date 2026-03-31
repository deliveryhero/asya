# High-Volume Document Processing (Map-Reduce)

## Use-Case

Batch processing of documents at scale — insurance claims (100K PDFs/day),
legal contract analysis, invoice extraction, medical record summarization.
Each document flows through: ingestion, OCR/parsing, classification,
extraction, validation, optional human review, storage.

## Why Asya

- **Map-reduce fan-out**: Split a batch into individual documents, process N
  in parallel, aggregate results. KEDA scales processor pods by queue depth.
- **Per-step scaling**: OCR actors (GPU) scale to 20 pods; classification
  actors (CPU) stay at 3. Each step scales independently.
- **State-in-message**: Each document's envelope carries its full extraction
  history — no central DB for intermediate state. The envelope IS the audit
  trail.
- **State-proxy for artifacts**: OCR output (images, PDFs) stored in S3;
  downstream actors read via `open("/state/ocr/page1.png")`.
- **Pause/resume**: Ambiguous documents route to `x-pause` for human review.
  Reviewer sees the envelope in a dashboard, approves/corrects, resumes.
- **DLQ for failures**: Unparseable documents route to `x-sump` — no silent
  failures, every document accounted for.

## Architecture

```
Batch Ingester
      |
  [fan-out: 1 msg per document]
      |
  OCR Actor (GPU, scales 1-20)
      |
  Classifier Actor (CPU, scales 1-5)
      |
  Extractor Actor (model-specific per class)
      |
  Validator Actor
      |
  +--> [if ambiguous] --> x-pause --> Human Review --> x-resume
  |
  Storage Actor --> x-sink
```

## Example Flow

```python
@flow
async def process_document(p):
    p = await ocr_parser(p)
    p = await classifier(p)

    if p["doc_class"] == "invoice":
        p = await invoice_extractor(p)
    elif p["doc_class"] == "contract":
        p = await contract_extractor(p)
    else:
        p = await generic_extractor(p)

    p = await validator(p)

    if p["confidence"] < 0.7:
        p = await human_review(p)  # pause/resume

    p = await store_results(p)
    return p
```

## Batch Fan-Out Pattern

```python
@flow
async def process_batch(p):
    p = await split_batch(p)  # returns list of doc refs
    p["results"] = [process_single(doc) for doc in p["documents"]]
    p = await aggregate_report(p)
    return p
```
