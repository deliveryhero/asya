# Release Process

## Overview

The release process consists of three GitHub Actions workflows:

1. **Release Drafter** - Automatically drafts release notes from pull requests
2. **Release** - Builds and publishes Docker images to GitHub Container Registry
3. **Changelog** - Updates CHANGELOG.md after release

## Workflow Details

### 1. Release Drafter (.github/workflows/release-drafter.yml)

**Triggers**: On every push to `main` and on pull request events (opened/reopened/synchronized)

**Purpose**: Automatically maintains a draft release with categorized changelog based on PR labels

**Behavior**:
- Creates/updates a draft release on GitHub
- Categorizes changes by PR labels (Features, Bug Fixes, Documentation, Testing, Performance, Infrastructure, Breaking Changes)
- Auto-labels PRs based on file paths (e.g., `src/asya-operator/**/*` → `operator` label)
- Automatically determines semantic version (major/minor/patch) based on PR labels

**Configuration**: `.github/release-drafter.yml`

**Version Resolution**:
- **Major**: `major`, `breaking`, `breaking-change` labels
- **Minor**: `minor`, `feature`, `enhancement` labels
- **Patch**: `patch`, `fix`, `bugfix`, `bug`, `documentation`, `chore`, `ci`, `build`, `dependencies`, `test`, `testing`, `performance`, `optimization` labels
- **Default**: patch

### 2. Release (.github/workflows/release.yml)

**Triggers**: When a release is published on GitHub

**Purpose**: Build and publish Docker images for all Asya components

**Steps**:
1. Extract version from release tag (removes `v` prefix: `v1.2.3` → `1.2.3`)
2. Build Docker images for all components:
   - asya-operator
   - asya-gateway
   - asya-sidecar
   - asya-crew
   - asya-testing
3. Push images to `ghcr.io/<owner>/<image>:<version>`
4. For non-prerelease versions: Tag and push images as `latest`

**Image Registry**: GitHub Container Registry (`ghcr.io`)

### 3. Changelog (.github/workflows/changelog.yml)

**Triggers**: When a release is published (non-prerelease only)

**Purpose**: Automatically update CHANGELOG.md with release notes

**Behavior**:
1. Extracts release information (version, tag, date)
2. Creates new CHANGELOG.md entry with:
   - Version header: `## [VERSION] - YYYY-MM-DD`
   - Release notes from GitHub release body
   - Links to release tag and unreleased changes
3. Creates pull request with changelog update

**PR Details**:
- Branch: `changelog-<tag>`
- Labels: `documentation`, `automated`
- Auto-deleted after merge

## Release Steps

### Creating a New Release

1. **Merge PRs to main**
   - Ensure PRs have appropriate labels (release-drafter will categorize them)
   - Release drafter automatically updates draft release

2. **Review draft release**
   - Navigate to GitHub Releases page
   - Review auto-generated release notes
   - Edit if necessary (add context, reorder items, etc.)

3. **Publish release**
   - Click "Publish release" button
   - For prerelease: Check "This is a pre-release" checkbox

4. **Automated actions**
   - Release workflow builds and publishes Docker images (~5-10 min)
   - Changelog workflow creates PR to update CHANGELOG.md
   - Review and merge changelog PR

### Version Tagging Convention

All releases use semantic versioning with `v` prefix:
- Major: `v2.0.0`
- Minor: `v1.5.0`
- Patch: `v1.4.3`
- Prerelease: `v1.5.0-rc.1`, `v2.0.0-beta.1`

### PR Labeling Best Practices

Release notes quality depends on PR labels. Use these guidelines:

**Change Type Labels** (affects version):
- `breaking`, `breaking-change` - Breaking API changes (major bump)
- `feature`, `enhancement` - New features (minor bump)
- `fix`, `bugfix`, `bug` - Bug fixes (patch bump)

**Category Labels** (affects changelog organization):
- `documentation`, `docs` - Documentation changes
- `test`, `testing` - Test additions/changes
- `performance`, `optimization` - Performance improvements
- `ci`, `build`, `chore` - Build/CI/tooling changes
- `dependencies` - Dependency updates

**Component Labels** (auto-labeled by file paths):
- `operator`, `gateway`, `sidecar`, `runtime`, `crew`

**Example**: A PR adding sidecar retry logic should have labels: `feature`, `sidecar`

## Docker Image Artifacts

After release publication, images are available at:

```
ghcr.io/<owner>/asya-operator:<version>
ghcr.io/<owner>/asya-gateway:<version>
ghcr.io/<owner>/asya-sidecar:<version>
ghcr.io/<owner>/asya-crew:<version>
ghcr.io/<owner>/asya-testing:<version>
```

Non-prerelease versions also tagged as `:latest`.

## Troubleshooting

**Release workflow fails**:
- Check GitHub Actions logs for build errors
- Verify `src/build-images.sh` script works locally: `make build-images`
- Ensure all components build successfully: `make build`

**Changelog PR not created**:
- Workflow only runs for non-prerelease versions
- Check workflow permissions (requires `contents: write`)

**Draft release not updating**:
- Verify release-drafter workflow runs on PR merge
- Check PR labels match release-drafter config
- Review `.github/release-drafter.yml` configuration
