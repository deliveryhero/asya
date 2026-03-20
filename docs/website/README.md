# MkDocs Shadcn Search Fix

## Issue

The official mkdocs-shadcn v0.9.7 has a critical search indexing bug where the search index is empty (0 documents indexed). This affects both the official demo site and all installations using this version.

- **GitHub Issue**: https://github.com/asiffer/mkdocs-shadcn/issues/30
- **Symptom**: Search bar appears but returns no results; `search_index.json` contains `"docs": []`

## Fix Applied

We're using a patched version from the `30-search-indexing-broken` branch that fixes the search indexing:

```bash
uv pip install "git+https://github.com/asiffer/mkdocs-shadcn@30-search-indexing-broken"
```

## Installation

```bash
uv pip install -r docs/mkdoc/requirements.txt
```

## Configuration

Enable prebuilt search index for faster page loads:

```yaml
# mkdocs.yml
plugins:
  - shadcn/search:
      prebuild_index: true  # Build search index at build time
```

With `prebuild_index: true`, the Lunr search index is built during `mkdocs build` instead of in the browser, reducing initial page load time from 15-30 seconds to instant search.

## Verification

After building, verify the search index is populated:

```bash
mkdocs build
cat site/search/search_index.json | jq '.docs | length'
# Should output: 440 (or your doc count)
```

## When to Remove This Patch

Monitor the upstream issue. When mkdocs-shadcn releases a new version (likely v0.9.8+) with this fix, switch back to PyPI:

```bash
uv pip install mkdocs-shadcn --upgrade
# Then update docs/requirements.txt to use: mkdocs-shadcn>=0.9.8
```

## Alternative: Material Theme

If you don't need shadcn styling, mkdocs-material has fully working search out of the box:

```yaml
theme:
  name: material
  features:
    - search.suggest
    - search.highlight
```
