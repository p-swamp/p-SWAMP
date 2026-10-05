#!/usr/bin/env bash
# Scaffold a new module over the core pipeline, and the page that shows it.
#
#   scripts/generate-new-module-with-frontend.sh peak-frequency "Peak frequency"
#
# What comes out already works: a module reading every PMU frame and publishing
# a result (a placeholder: the station with the highest frequency), its
# pipeline, its web API, a page at /peak-frequency showing the latest result,
# unit tests, and the module added to the module-worker in docker-compose.yml and
# k8s/p-swamp-local.yaml.
#
# The module goes to modules/pswamp_modules/<pkg>/ with its tests in a
# tests/ folder beside it, and its pipeline to pswamp_modules/pipelines/
# (pswamp_modules depends on the core only); the web API goes to
# app/server-python/src/<pkg>/ and the page to app/client-web/. Replacing the
# analysis in modules/pswamp_modules/<pkg>/module.py is the work left.
# doc/module-cookbook.md walks through every file.
#
# The same engine as generate-new-subapp.sh, with the templates in
# scripts/templates/module/. NO_CHECK=1 skips the error_check.sh run.
# scripts/check-generators.sh proves the output works.
set -euo pipefail

TEMPLATE_SET=module GENERATOR=scripts/generate-new-module-with-frontend.sh \
  exec "$(dirname "$0")/generate-new-subapp.sh" "$@"
