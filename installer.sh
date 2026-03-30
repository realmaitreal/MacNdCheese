#!/bin/sh
set -eu



export PATH="${HOME}/Library/Application Support/MacNCheese/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

ACTION="${1:-}"
PREFIX_DIR="${2:-}"
DXVK_SRC="${3:-}"
DXVK_INSTALL64="${4:-}"
DXVK_INSTALL32="${5:-}"
MESA_DIR="${6:-}"
MESA_URL="${7:-}"
DXMT_DIR="${8:-}"
DXMT_URL="${9:-}"
VKD3D_DIR="${10:-}"
VKD3D_URL="${11:-}"

MNC_DATA_DIR="${HOME}/Library/Application Support/MacNCheese"
MNC_BIN_DIR="${MNC_DATA_DIR}/bin"
MNC_RUNTIME_DIR="${MNC_DATA_DIR}/runtime"
REPO_BASE_URL="https://github.com/mont127/MacNdCheese/releases/download/v5.2.3"

XQUARTZ_URL="${REPO_BASE_URL}/XQuartz-portable.tar.gz"
GSTREAMER_URL="${REPO_BASE_URL}/gstreamer-portable.tar.xz"
DXVK_PREBUILT_URL="${REPO_BASE_URL}/dxvk-macOS.tar.gz"
WINE_STABLE_URL="${REPO_BASE_URL}/wine-portable.tar.xz"
DXMT_DEFAULT_URL="${REPO_BASE_URL}/dxmt.tar.gz"
VKD3D_DEFAULT_URL="${REPO_BASE_URL}/vkd3d-proton.tar.zst"
TOOLS_URL="${REPO_BASE_URL}/tools-macos.tar.gz"

WORK_DIR="$(mktemp -d /tmp/macncheese-installer.XXXXXX)"
mkdir -p "$MNC_BIN_DIR" "$MNC_RUNTIME_DIR"

trap 'rm -rf "$WORK_DIR"' EXIT

if [ -z "$ACTION" ]; then
  echo "Missing action"
  exit 1
fi

echo "Starting installer action: $ACTION"

download_file() {
    url="$1"
    out="$2"
    expected_sha="${3:-}"
    echo "Downloading $url..."
    curl -L --fail --retry 3 --retry-delay 2 -o "$out" "$url"
    if [ -n "$expected_sha" ]; then
        actual_sha="$(shasum -a 256 "$out" | awk '{print $1}')"
        if [ "$actual_sha" != "$expected_sha" ]; then
            echo "Checksum mismatch for $out"
            rm -f "$out"
            exit 1
        fi
    fi
}

bootstrap_tools() {
    if ! command -v 7z >/dev/null 2>&1 || ! command -v zstd >/dev/null 2>&1; then
        echo "Bootstrapping tools (7z, zstd) into $MNC_BIN_DIR..."
        archive="$WORK_DIR/tools.tar.gz"
        download_file "$TOOLS_URL" "$archive"
        tar -xzf "$archive" -C "$MNC_BIN_DIR"
    fi
}

install_wine() {
    bootstrap_tools
    archive="$WORK_DIR/wine.tar.xz"
    unpack_dir="$MNC_RUNTIME_DIR/wine"
    rm -rf "$unpack_dir"
    mkdir -p "$unpack_dir"
    echo "Installing portable Wine..."
    download_file "$WINE_STABLE_URL" "$archive"
    tar -xJf "$archive" -C "$unpack_dir" --strip-components=1
}

install_dxvk() {
    bootstrap_tools
    [ -z "$DXVK_INSTALL64" ] || [ -z "$DXVK_INSTALL32" ] && { echo "Missing DXVK paths"; exit 1; }
    archive="$WORK_DIR/dxvk.tar.gz"
    extract_dir="$WORK_DIR/dxvk-prebuilt"
    mkdir -p "$DXVK_INSTALL64/bin" "$DXVK_INSTALL32/bin"
    echo "Installing portable DXVK..."
    download_file "$DXVK_PREBUILT_URL" "$archive"
    mkdir -p "$extract_dir"
    tar -xzf "$archive" -C "$extract_dir" --strip-components=1
    cp "$extract_dir/x64/"*.dll "$DXVK_INSTALL64/bin/"
    cp "$extract_dir/x32/"*.dll "$DXVK_INSTALL32/bin/"
}

install_mesa() {
    bootstrap_tools
    archive="$WORK_DIR/mesa.7z"
    echo "Installing portable Mesa..."
    download_file "${MESA_URL:-$REPO_BASE_URL/mesa-portable.7z}" "$archive"
    mkdir -p "$MNC_RUNTIME_DIR/mesa"
    7z x "$archive" -o"$MNC_RUNTIME_DIR/mesa" -y >/dev/null
}

install_dxmt() {
    [ -z "$DXMT_DIR" ] && { echo "Missing DXMT dir"; exit 1; }
    archive="$WORK_DIR/dxmt.tar.gz"
    unpack_dir="$WORK_DIR/dxmt-tmp"
    echo "Installing portable DXMT..."
    download_file "$DXMT_DEFAULT_URL" "$archive"
    mkdir -p "$unpack_dir"
    tar -xzf "$archive" -C "$unpack_dir"
    found_dir="$(find "$unpack_dir" -type f -name d3d11.dll -print | head -n1 | xargs dirname 2>/dev/null || echo "$unpack_dir")"
    mkdir -p "$DXMT_DIR"
    cp -f "$found_dir/"*.dll "$DXMT_DIR/"
}

install_vkd3d() {
    bootstrap_tools
    [ -z "$VKD3D_DIR" ] && { echo "Missing VKD3D dir"; exit 1; }
    archive="$WORK_DIR/vkd3d.tar.zst"
    unpack_dir="$WORK_DIR/vkd3d-tmp"
    echo "Installing portable VKD3D-Proton..."
    download_file "$VKD3D_DEFAULT_URL" "$archive"
    mkdir -p "$unpack_dir"
    zstd -d "$archive" -o "$WORK_DIR/vkd3d.tar"
    tar -xf "$WORK_DIR/vkd3d.tar" -C "$unpack_dir"
    found_dir="$(find "$unpack_dir" -type f -name d3d12.dll -print | head -n1 | xargs dirname 2>/dev/null || echo "$unpack_dir")"
    mkdir -p "$VKD3D_DIR"
    cp -f "$found_dir/"*.dll "$VKD3D_DIR/"
}

init_prefix() {
    [ -z "$PREFIX_DIR" ] && { echo "Missing prefix path"; exit 1; }
    mkdir -p "$PREFIX_DIR"
    export WINEPREFIX="$PREFIX_DIR"
    wine_bin="$MNC_RUNTIME_DIR/wine/bin/wine"
    if [ -x "$wine_bin" ]; then
        "$wine_bin" wineboot
    else
        echo "Portable wine not found at $wine_bin"
        exit 1
    fi
}

quick_setup() {
    install_wine
    install_dxvk
    install_mesa
}

case "$ACTION" in
  install_wine)  install_wine ;;
  install_dxvk)  install_dxvk ;;
  install_mesa)  install_mesa ;;
  install_dxmt)  install_dxmt ;;
  install_vkd3d) install_vkd3d ;;
  init_prefix)   init_prefix ;;
  quick_setup)   quick_setup ;;
  *) echo "Unknown action: $ACTION"; exit 1 ;;
esac
