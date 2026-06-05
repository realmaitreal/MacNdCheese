#!/usr/bin/env bash
# build-wine-msync.sh — Build Wine Staging 11.9 + msync for MacNCheese.
#
# What this does:
#   1. Downloads vanilla Wine 11.9 source (winehq mirror)
#   2. Clones wine-staging v11.9 patches (gitlab.winehq.org)
#   3. Applies wine-staging patches → produces the same base as the prebuilt
#      Wine Staging.app in MacNCheese deps
#   4. Applies the msync patch (Mach semaphore backend for macOS)
#   5. Builds and packages as Wine Staging.app in MacNCheese deps
#
# Prerequisites (install via Homebrew):
#   brew install git autoconf automake libtool pkg-config \
#                freetype gettext gnutls jpeg-turbo libpng bison flex
#
# Usage:
#   bash build-wine-msync.sh [--skip-download] [--skip-staging] [--skip-msync]
#
set -euo pipefail

PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_ROOT="${HOME}/wine-msync-build"
WINE_SRC="${BUILD_ROOT}/wine-src"
STAGING_PATCHES="${BUILD_ROOT}/wine-staging-patches"
WINE_INSTALL="${BUILD_ROOT}/wine-msync-install"
BUNDLE_NAME="Wine Staging.app"
BUNDLE_DST="${HOME}/Library/Application Support/MacNCheese/deps/${BUNDLE_NAME}"

SKIP_DOWNLOAD=0
SKIP_STAGING=0
SKIP_MSYNC=0
for arg in "$@"; do
    case "$arg" in
        --skip-download) SKIP_DOWNLOAD=1 ;;
        --skip-staging)  SKIP_STAGING=1 ;;
        --skip-msync)    SKIP_MSYNC=1 ;;
    esac
done

NCPU=$(sysctl -n hw.ncpu)
BREW_PREFIX=$(brew --prefix 2>/dev/null || echo "/opt/homebrew")

echo "=== MacNCheese: Wine Staging 11.9 + msync build ==="
echo "Build root : ${BUILD_ROOT}"
echo "Install to : ${BUNDLE_DST}"
echo ""

mkdir -p "${BUILD_ROOT}"

# ── 1. Vanilla Wine 11.9 source ────────────────────────────────────────────
if [[ $SKIP_DOWNLOAD -eq 0 ]]; then
    echo "→ Downloading vanilla Wine 11.9 source..."
    cd "${BUILD_ROOT}"
    WINE_URL="https://dl.winehq.org/wine/source/11.x/wine-11.9.tar.xz"
    echo "  ${WINE_URL}"
    curl -L --progress-bar "${WINE_URL}" -o wine-11.9.tar.xz
    rm -rf "${WINE_SRC}"
    mkdir -p "${WINE_SRC}"
    tar -xf wine-11.9.tar.xz -C "${WINE_SRC}" --strip-components=1
    rm wine-11.9.tar.xz
    echo "  Extracted to ${WINE_SRC}"
else
    echo "→ Skipping download (using existing ${WINE_SRC})"
    [[ -d "${WINE_SRC}" ]] || { echo "ERROR: ${WINE_SRC} missing — run without --skip-download"; exit 1; }
fi

# ── 2. Wine Staging patches ────────────────────────────────────────────────
if [[ $SKIP_STAGING -eq 0 ]]; then
    echo ""
    echo "→ Fetching wine-staging v11.9 patch set..."
    if [[ -d "${STAGING_PATCHES}/.git" ]]; then
        git -C "${STAGING_PATCHES}" fetch --tags -q
        git -C "${STAGING_PATCHES}" checkout v11.9 -q
        echo "  Updated existing clone"
    else
        rm -rf "${STAGING_PATCHES}"
        git clone --depth 1 --branch v11.9 \
            https://gitlab.winehq.org/wine/wine-staging.git \
            "${STAGING_PATCHES}" -q
        echo "  Cloned wine-staging v11.9"
    fi

    echo "→ Applying wine-staging patches to source tree..."
    cd "${WINE_SRC}"
    python3 "${STAGING_PATCHES}/staging/patchinstall.py" \
        DESTDIR="${WINE_SRC}" --all 2>&1 \
        | grep -E "^(Applying|ERROR|FAILED|warning)" || true
    echo "  wine-staging patches applied"
else
    echo "→ Skipping wine-staging patches."
fi

# ── 3. msync patch ─────────────────────────────────────────────────────────
if [[ $SKIP_MSYNC -eq 0 ]]; then
    echo ""
    echo "→ Applying msync patch..."
    cd "${WINE_SRC}"
    python3 "${PATCH_DIR}/apply.py"
else
    echo "→ Skipping msync patch."
fi

# ── 4. Configure ───────────────────────────────────────────────────────────
echo ""
echo "→ Running autoreconf and configure..."
cd "${WINE_SRC}"

if [[ ! -f configure ]]; then
    autoreconf -fi
fi

HOMEBREW_LIBS="${BREW_PREFIX}/lib"
HOMEBREW_INCS="${BREW_PREFIX}/include"

./configure \
    --prefix="${WINE_INSTALL}" \
    --enable-archs=x86_64 \
    --without-x \
    --without-opengl \
    --without-vulkan \
    --with-freetype \
    --with-gnutls \
    --with-gettext \
    CFLAGS="-O2 -I${HOMEBREW_INCS}" \
    LDFLAGS="-L${HOMEBREW_LIBS}" \
    PKG_CONFIG_PATH="${HOMEBREW_LIBS}/pkgconfig" \
    2>&1 | tail -20

# ── 5. Build ───────────────────────────────────────────────────────────────
echo ""
echo "→ Building Wine with ${NCPU} parallel jobs (this takes 20-40 min)..."
make -j"${NCPU}" 2>&1 | grep -E "^(make\[1\]|error:|msync)" || true
make -j"${NCPU}"

# ── 6. Install ─────────────────────────────────────────────────────────────
echo ""
echo "→ Installing to ${WINE_INSTALL}..."
make install

# ── 7. Package as .app bundle ──────────────────────────────────────────────
echo ""
echo "→ Packaging as ${BUNDLE_NAME}..."

BUNDLE="${BUNDLE_DST}"
WINE_RES="${BUNDLE}/Contents/Resources/wine"

mkdir -p "${BUNDLE}/Contents/MacOS" "${WINE_RES}"

cat > "${BUNDLE}/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>org.winehq.wine-staging-msync</string>
    <key>CFBundleName</key>
    <string>Wine Staging (msync)</string>
    <key>CFBundleVersion</key>
    <string>11.9-msync</string>
</dict>
</plist>
PLIST

cat > "${BUNDLE}/Contents/MacOS/wine" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")/../../Resources/wine/bin" && pwd)"
exec "$DIR/wine64" "$@"
LAUNCHER
chmod +x "${BUNDLE}/Contents/MacOS/wine"

rsync -a --delete "${WINE_INSTALL}/" "${WINE_RES}/"

echo ""
echo "=== Done! ==="
echo ""
echo "Wine Staging 11.9 + msync installed to:"
echo "  ${BUNDLE_DST}"
echo ""
echo "MacNCheese will automatically use it as 'Wine Staging'."
echo "Enable msync per-game in the launch options (or set WINEMSYNC=1)."
echo "DXMT works with this build — set it up separately via ~/dxmt/ as usual."
