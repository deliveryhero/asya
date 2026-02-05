def text_analysis_flow(p: dict) -> dict:
    # Flow entrypoint: start_text_analysis_flow

    # Preprocessing
    p = clean_text(p)
    p = tokenize(p)

    # Conditional analysis (creates router)
    if p["language"] == "en":
        p = english_sentiment(p)
    elif p["language"] == "es":
        p = spanish_sentiment(p)
    else:
        p["sentiment"] = "neutral"  # Skip analysis

    # Enrichment
    p = extract_entities(p)
    p["extracted"] = True

    return p  # Flow exitpoint: end_text_analysis_flow

# Define your handler functions (can be in separate files)
def clean_text(p: dict) -> dict:
    ...
    return p

def tokenize(p: dict) -> dict:
    ...
    return p

def english_sentiment(p: dict) -> dict:
    ...
    return p

def spanish_sentiment(p: dict) -> dict:
    ...
    return p

def extract_entities(p: dict) -> dict:
    ...
    return p
