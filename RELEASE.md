# Release Process for Turia CLI

## Version Management

The version is managed from a **single source of truth**: the `VERSION` file in the repository root.

```
VERSION              <- Single source of truth (e.g., "0.0.175")
    |
    +-> scripts/global_vars.sh  (reads VERSION at runtime)
    +-> Formula/turia.rb         (updated during release)
```

## How to Release a New Version

### Step 1: Update VERSION file

```bash
# Increment version (e.g., from 0.0.174 to 0.0.175)
echo "0.0.175" > VERSION
```

### Step 2: Commit changes

```bash
git add .
git commit -m "Description of changes

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

### Step 3: Create and push tag

```bash
# Read version from file
NEW_VERSION=$(cat VERSION)

# Create tag (with v prefix) and push
git tag "v${NEW_VERSION}"
git push origin main
git push origin "v${NEW_VERSION}"
```

### Step 4: Update Formula with new SHA256

```bash
# Get SHA256 of new release tarball
NEW_VERSION=$(cat VERSION)
SHA256=$(curl -sL "https://github.com/rudoapps/homebrew-turia/archive/refs/tags/${NEW_VERSION}.tar.gz" | shasum -a 256 | cut -d' ' -f1)

echo "New SHA256: $SHA256"

# Update Formula/turia.rb with new version and SHA256
# Replace the url and sha256 lines with:
#   url "https://github.com/rudoapps/homebrew-turia/archive/refs/tags/${NEW_VERSION}.tar.gz"
#   sha256 "${SHA256}"
```

### Step 5: Commit Formula update

```bash
git add Formula/turia.rb
git commit -m "Update sha256 for v${NEW_VERSION}"
git push origin main
```

### Step 6: Create GitHub Release

Create a release on GitHub based on the tag. Follow the style of previous releases:

```bash
# Title format: "v0.0.XXX - Brief description of the main change"
# Body format: markdown with sections for each major change using emoji headers
#   - 🚀 for new features
#   - 🐛 for bug fixes
#   - ✏️ for improvements/changes
#   - 🔧 for internal/tooling changes
# Always end with an install section:
#   ### 📦 Instalación
#   ```bash
#   brew update && brew upgrade turia
#   ```

NEW_VERSION=$(cat VERSION)
gh release create "v${NEW_VERSION}" \
  --title "v${NEW_VERSION} - Brief description" \
  --notes "$(cat <<'EOF'
## Main change title

Description of changes...

### 📦 Instalación

```bash
brew update && brew upgrade turia
```
EOF
)"
```

## Quick Release (All Steps Combined)

```bash
# 1. Set new version
NEW_VERSION="0.0.175"  # Change this to your new version
echo "$NEW_VERSION" > VERSION

# 2. Commit your changes
git add .
git commit -m "Your commit message

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

# 3. Tag and push
git tag "v${NEW_VERSION}"
git push origin main
git push origin "v${NEW_VERSION}"

# 4. Get SHA256 and update Formula
SHA256=$(curl -sL "https://github.com/rudoapps/homebrew-turia/archive/refs/tags/v${NEW_VERSION}.tar.gz" | shasum -a 256 | cut -d' ' -f1)

# 5. Edit Formula/turia.rb - update url version and sha256
# Then:
git add Formula/turia.rb
git commit -m "Update sha256 for v${NEW_VERSION}"
git push origin main

# 6. Create GitHub Release
gh release create "v${NEW_VERSION}" \
  --title "v${NEW_VERSION} - Brief description" \
  --notes "Release notes in markdown..."
```

## Python Dependencies (venv management)

`turia ai` runs inside a dedicated venv at `~/.config/turia-agent/venv/`. Dependencies are
defined in the `turia` script (the `pip install` line inside the venv setup block).

A **deps version stamp** (`_TURIA_DEPS_VERSION` variable in `turia`) controls when the venv
is recreated. When the stamp changes, all users' venvs are automatically rebuilt on next launch.

### When to bump `_TURIA_DEPS_VERSION`

**Bump it** (increment by 1) when:
- Adding a new Python dependency to the `pip install` line
- Removing a Python dependency
- Changing a minimum version constraint (e.g., `httpx>=0.27`)
- Upgrading Python minimum version requirement

**Do NOT bump it** when:
- Only changing Python source code (`.py` files) — the venv doesn't contain turia code
- Changing non-Python files (bash scripts, Formula, etc.)

The variable is near the top of the `# Manejar comando 'ai'` block in the `turia` script:
```bash
_TURIA_DEPS_VERSION="1"  # ← bump this number
```

## For Claude AI Sessions

When asked to release a new version:

1. **Read current version**: `cat VERSION`
2. **Increment version**: Update VERSION file with new version number
3. **Check if Python deps changed**: If any Python dependency was added/removed/changed
   in the `turia` script's venv setup, bump `_TURIA_DEPS_VERSION` (increment by 1).
   If only `.py` source files changed, do NOT bump it.
4. **Commit changes**: Include all modified files with descriptive message
5. **Create git tag**: Tag must be `v` + VERSION content (e.g., VERSION=`0.0.279` → tag=`v0.0.279`)
6. **Push to remote**: Push both main branch and tag
7. **Update Formula**: Get SHA256 from tarball URL and update Formula/turia.rb
8. **Push Formula update**: Commit and push the sha256 update
9. **Create GitHub Release**: Use `gh release create` with a title in format `"v0.0.XXX - Brief description"` and markdown body. Look at previous releases (`gh release list` / `gh release view <tag>`) for style reference. Use emoji section headers (🚀 features, 🐛 fixes, ✏️ improvements, 🔧 tooling). Always include install section at the end.

Users will receive the update automatically (auto-update runs every hour).
