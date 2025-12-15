# Asya Landing Page

This directory contains the landing page for https://asya.sh

## Structure

- `index.html` - Main landing page with links to documentation and resources
- `assets/` - Static assets (images, additional CSS/JS if needed)

## Deployment

The landing page is automatically deployed to https://asya.sh via GitHub Actions (`.github/workflows/docs.yml`) when changes are pushed to the `main` branch.

The deployment structure on GitHub Pages:
```
asya.sh/
├── index.html          # This landing page
├── docs/              # MkDocs documentation
└── charts/            # Helm repository (published on releases)
```

## Local Preview

Simply open `index.html` in your browser to preview the landing page locally.
