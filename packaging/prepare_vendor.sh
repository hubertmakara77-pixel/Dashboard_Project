#!/bin/sh
set -eu

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
vendor_dir="${project_dir}/packaging/vendor"

case "${vendor_dir}" in
    "${project_dir}/packaging/vendor") ;;
    *)
        echo "Refusing to replace unexpected vendor directory: ${vendor_dir}" >&2
        exit 1
        ;;
esac

command -v python3 >/dev/null 2>&1 || {
    echo "python3 is required" >&2
    exit 1
}
python3 -m pip --version >/dev/null 2>&1 || {
    echo "python3-pip is required to prepare vendored Python dependencies" >&2
    echo "Install it as root with: apt install python3-pip" >&2
    exit 1
}

rm -rf -- "${vendor_dir}"
mkdir -p -- "${vendor_dir}"
python3 -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --no-compile \
    --target "${vendor_dir}" \
    --requirement "${project_dir}/requirements.txt"

find "${vendor_dir}" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "${vendor_dir}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

echo "Prepared private Python dependencies in ${vendor_dir}"
