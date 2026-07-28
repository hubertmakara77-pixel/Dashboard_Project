#!/bin/sh
set -eu

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
version="$(tr -d '[:space:]' < "${project_dir}/packaging/VERSION")"
temporary_parent="${TMPDIR:-/tmp}"
build_root=""

cleanup() {
    [ -n "${build_root}" ] || return 0
    case "${build_root}" in
        "${temporary_parent}"/amp-panel-build.*)
            rm -rf -- "${build_root}"
            ;;
        *)
            echo "Refusing to remove unexpected build directory: ${build_root}" >&2
            ;;
    esac
}
trap cleanup EXIT HUP INT TERM

[ "$(uname -s)" = "Linux" ] || {
    echo "Build the Debian package on Linux for the target device architecture." >&2
    exit 1
}

command -v dpkg-buildpackage >/dev/null 2>&1 || {
    echo "dpkg-buildpackage is required (install build-essential and debhelper)" >&2
    exit 1
}
command -v git >/dev/null 2>&1 || {
    echo "git is required to prepare a clean package source tree" >&2
    exit 1
}
command -v tar >/dev/null 2>&1 || {
    echo "tar is required to prepare a clean package source tree" >&2
    exit 1
}

changelog_version="$(
    cd "${project_dir}" &&
        dpkg-parsechangelog --show-field Version
)"
[ "${changelog_version}" = "${version}" ] || {
    echo "Version mismatch: packaging/VERSION=${version}, changelog=${changelog_version}" >&2
    exit 1
}

chmod +x \
    "${project_dir}/packaging/prepare_vendor.sh"

if [ ! -d "${project_dir}/packaging/vendor/fastapi" ]; then
    "${project_dir}/packaging/prepare_vendor.sh"
fi

build_root="$(mktemp -d "${temporary_parent}/amp-panel-build.XXXXXX")"
build_tree="${build_root}/source"
source_archive="${build_root}/source.tar"
mkdir -p -- "${build_tree}"

# Build from committed files only. Runtime data, local configuration,
# documentation drafts and other untracked files never enter this tree.
git -C "${project_dir}" archive --format=tar --output="${source_archive}" HEAD
tar -xf "${source_archive}" -C "${build_tree}"
cp -a "${project_dir}/packaging/vendor" "${build_tree}/packaging/vendor"

chmod +x \
    "${build_tree}/debian/rules" \
    "${build_tree}/debian/config" \
    "${build_tree}/debian/postinst" \
    "${build_tree}/debian/prerm" \
    "${build_tree}/debian/postrm" \
    "${build_tree}/packaging/prepare_vendor.sh"

cd "${build_tree}"
dpkg-buildpackage --build=binary --no-sign

architecture="$(dpkg-architecture -qDEB_HOST_ARCH)"
artifact="${build_root}/amp-panel_${version}_${architecture}.deb"
destination="$(dirname "${project_dir}")/amp-panel_${version}_${architecture}.deb"
[ -f "${artifact}" ] || {
    echo "Expected package was not produced: ${artifact}" >&2
    exit 1
}
install -m 0644 "${artifact}" "${destination}"
echo "Built ${destination}"
