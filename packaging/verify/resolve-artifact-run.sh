#!/usr/bin/env bash
# OpenCode iOS port — resolve the GitHub Actions run that owns a required artifact.
#
# Cross-workflow artifact reuse without rebuilding anything: both
# package-rootless.yml and test-port.yml call this script with
# `GH_TOKEN`/`GITHUB_TOKEN` in the environment (permissions: actions: read).
#
# Behaviour:
#   * with a pinned run id: fail unless that run exists and has the artifact,
#   * without a pin: scan the latest successful runs of the workflow on `main`
#     and pick the newest one whose artifact exists and is not expired,
#   * if the workflow/artifact does not exist yet, fail with an explicit
#     bring-up message — placeholder binaries are never fabricated.
#
# Usage:
#   resolve-artifact-run.sh WORKFLOW_FILE ARTIFACT_NAME LABEL [PINNED_RUN_ID]
#                          [--optional]
#
# Writes to $GITHUB_OUTPUT (when set):
#   <label>_run_id, <label>_run_url, <label>_head_sha
set -euo pipefail

WORKFLOW_FILE="${1:-}"
ARTIFACT_NAME="${2:-}"
LABEL="${3:-}"
PINNED="${4:-}"
OPTIONAL=0
case "${5:-}" in
    --optional) OPTIONAL=1 ;;
    "") : ;;
    *) echo "resolve-artifact-run: unknown flag: ${5}" >&2; exit 2 ;;
esac

die() { echo "::error::$*" >&2; exit 1; }
notice() { echo "::notice::$*"; }
info() { echo "==> $*"; }

[ -n "$WORKFLOW_FILE" ] || die "usage: resolve-artifact-run.sh WORKFLOW_FILE ARTIFACT_NAME LABEL [RUN_ID] [--optional]"
[ -n "$ARTIFACT_NAME" ] || die "ARTIFACT_NAME is required"
[ -n "$LABEL" ] || die "LABEL is required"
[ -n "${GITHUB_REPOSITORY:-}" ] || die "GITHUB_REPOSITORY is not set (this script is meant for GitHub Actions)"
REPO="$GITHUB_REPOSITORY"

emit() {
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        {
            echo "${LABEL}_run_id=$1"
            echo "${LABEL}_run_url=$2"
            echo "${LABEL}_head_sha=$3"
        } >> "$GITHUB_OUTPUT"
    fi
}

optional_skip() {
    notice "$*"
    emit "" "" ""
    exit 0
}

run_has_artifact() {
    local run_id="$1" count
    # `gh run view --json artifacts` is not available in all gh versions, so
    # query the REST API directly (token comes from GH_TOKEN/GITHUB_TOKEN).
    count="$(gh api "repos/${REPO}/actions/runs/${run_id}/artifacts" \
        --jq "[.artifacts[] | select(.name == \"$ARTIFACT_NAME\" and (.expired == false))] | length" \
        2>/dev/null || echo 0)"
    [ "${count:-0}" -gt 0 ]
}

if [ -n "$PINNED" ]; then
    if ! gh run view "$PINNED" --repo "$REPO" --json databaseId >/dev/null 2>&1; then
        die "${LABEL}: pinned run id ${PINNED} does not exist in ${REPO}."
    fi
    if ! run_has_artifact "$PINNED"; then
        if [ "$OPTIONAL" = "1" ]; then
            optional_skip "${LABEL}: pinned run ${PINNED} has no unexpired '${ARTIFACT_NAME}' artifact; optional component skipped."
        fi
        die "${LABEL}: pinned run ${PINNED} has no unexpired '${ARTIFACT_NAME}' artifact."
    fi
    RUN_ID="$PINNED"
else
    if ! gh api "repos/${REPO}/actions/workflows/${WORKFLOW_FILE}" >/dev/null 2>&1; then
        if [ "$OPTIONAL" = "1" ]; then
            optional_skip "${LABEL}: workflow '${WORKFLOW_FILE}' is not present in ${REPO} yet; optional component skipped."
        fi
        die "${LABEL}: workflow '${WORKFLOW_FILE}' is not present in ${REPO} yet. This pipeline consumes a successful upstream build that uploads '${ARTIFACT_NAME}'; refusing to fabricate inputs."
    fi
    RUN_ID=""
    for candidate in $(gh run list --repo "$REPO" --workflow "$WORKFLOW_FILE" \
            --branch main --status success --limit 10 --json databaseId \
            --jq '.[].databaseId' 2>/dev/null || true); do
        if run_has_artifact "$candidate"; then
            RUN_ID="$candidate"
            break
        fi
    done
    if [ -z "$RUN_ID" ]; then
        if [ "$OPTIONAL" = "1" ]; then
            optional_skip "${LABEL}: no successful '${WORKFLOW_FILE}' run on main currently has an unexpired '${ARTIFACT_NAME}' artifact; optional component skipped."
        fi
        die "${LABEL}: no successful '${WORKFLOW_FILE}' run on main currently has an unexpired '${ARTIFACT_NAME}' artifact. Wait for the upstream build workflow to go green (or pass an explicit run id via workflow_dispatch). Refusing to package placeholder binaries."
    fi
fi

RUN_URL="$(gh run view "$RUN_ID" --repo "$REPO" --json url --jq '.url' 2>/dev/null || true)"
HEAD_SHA="$(gh run view "$RUN_ID" --repo "$REPO" --json headSha --jq '.headSha' 2>/dev/null || true)"
emit "$RUN_ID" "$RUN_URL" "$HEAD_SHA"
info "resolved ${LABEL}: run ${RUN_ID} (${RUN_URL}), head ${HEAD_SHA}, artifact '${ARTIFACT_NAME}'"
