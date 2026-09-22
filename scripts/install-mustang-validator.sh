#!/usr/bin/env bash
set -euo pipefail

readonly VERSION="2.23.0"
readonly SHA256="344c88b8d9bddccae23899a87d1ef31c4d38532383faa6303c381ee489cabe07"
readonly FILENAME="Mustang-CLI-${VERSION}.jar"
readonly URL="https://github.com/ZUGFeRD/mustangproject/releases/download/core-${VERSION}/${FILENAME}"
readonly TARGET_DIRECTORY="${1:?usage: install-mustang-validator.sh TARGET_DIRECTORY}"

mkdir -p "${TARGET_DIRECTORY}"
temporary_file="$(mktemp)"
trap 'rm -f "${temporary_file}"' EXIT

curl --fail --location --silent --show-error "${URL}" --output "${temporary_file}"
echo "${SHA256}  ${temporary_file}" | sha256sum --check --status
install -m 0644 "${temporary_file}" "${TARGET_DIRECTORY}/${FILENAME}"
