#!/bin/sh
# Prepares BRAIN_ROOT (the api volume) and starts the command.
# - First run: an empty volume gets the image's companies/*.yaml. Later runs keep the volume's
#   own files, so companies added or edited in the UI survive a new image.
# - BRAIN_ROOT/apps links to the code, because company YAML paths resolve from BRAIN_ROOT and
#   synthetic.yaml reads apps/brain/examples/synthetic_company.
set -eu
root="${BRAIN_ROOT:?BRAIN_ROOT must be set}"
mkdir -p "$root/companies" "$root/data"
if ! ls "$root"/companies/*.yaml >/dev/null 2>&1; then
    cp /app/companies/*.yaml "$root/companies/"
    echo "entrypoint: seeded $root/companies from the image"
fi
ln -sfn /app/apps "$root/apps"
exec "$@"
