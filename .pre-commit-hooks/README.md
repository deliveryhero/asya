# Pre-commit Hook Scripts

Custom scripts for enforcing repository-specific rules.

## check-symlinks.sh

Ensures critical files remain as symlinks to prevent duplicate content.

### Checked Symlinks

- **`asya_runtime.py`**: The Python runtime script must be symlinked (not copied)
  - Source: `src/asya-runtime/asya_runtime.py`
  - Symlink: `deploy/helm-charts/asya-crossplane/files/asya_runtime.py`

## Why This Matters

- **Symlinks** ensure single source of truth for files used in multiple locations
- **Relative symlinks** work across different machines/git clones (unlike absolute paths)
- Pre-commit hooks prevent accidentally committing duplicate files instead of symlinks
