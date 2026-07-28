#!/bin/sh
set -eu

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
version="$(tr -d '[:space:]' < "${project_dir}/packaging/VERSION")"

[ "$(uname -s)" = "Linux" ] || {
    echo "Build the Debian package on Linux for the target device architecture." >&2
    exit 1
}

command -v dpkg-buildpackage >/dev/null 2>&1 || {
    echo "dpkg-buildpackage is required (install build-essential and debhelper)" >&2
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
    "${project_dir}/debian/rules" \
    "${project_dir}/debian/config" \
    "${project_dir}/debian/postinst" \
    "${project_dir}/debian/prerm" \
    "${project_dir}/debian/postrm" \
    "${project_dir}/packaging/prepare_vendor.sh"

if [ ! -d "${project_dir}/packaging/vendor/fastapi" ]; then
    "${project_dir}/packaging/prepare_vendor.sh"
fi

cd "${project_dir}"
dpkg-buildpackage --build=binary --no-sign

architecture="$(dpkg-architecture -qDEB_HOST_ARCH)"
echo "Built ../amp-panel_${version}_${architecture}.deb"
