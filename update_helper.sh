#!/bin/sh
# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

# BlindRSS POSIX update helper (macOS + Linux).
#
# Mirrors update_helper.bat: wait for the running app to exit, swap the install
# target with the staged new build, relaunch, and clean up. It must be run from
# OUTSIDE the install target (the launcher copies it into a temp dir first) so it
# is not removed while running.
#
# Usage:
#   update_helper.sh <parent_pid> <platform> <install_target> <staging_root> <relaunch_path> [temp_root]
#
#   platform       : macos | linux
#   install_target : path to replace (.app bundle on macOS; install dir on Linux)
#   staging_root   : new content (new .app on macOS; new install dir on Linux)
#   relaunch_path  : macOS -> .app to `open`; Linux -> executable to run
#   temp_root      : optional temp working dir to remove on success

set -u

PID="${1:-}"
PLATFORM="${2:-}"
INSTALL_TARGET="${3:-}"
STAGING_ROOT="${4:-}"
RELAUNCH_PATH="${5:-}"
TEMP_ROOT="${6:-}"

STAMP="$(date +%Y%m%d%H%M%S 2>/dev/null || echo 0)"
LOG_FILE="${TMPDIR:-/tmp}/BlindRSS_update_${STAMP}_$$.log"
BACKUP_DIR="${INSTALL_TARGET}.bak.${STAMP}.$$"

log() {
  echo "[BlindRSS Update] $*" >>"$LOG_FILE" 2>&1
}

usage() {
  echo "Usage: update_helper.sh <pid> <platform> <install_target> <staging_root> <relaunch_path> [temp_root]" >&2
  exit 1
}

[ -n "$PID" ] || usage
[ -n "$PLATFORM" ] || usage
[ -n "$INSTALL_TARGET" ] || usage
[ -n "$STAGING_ROOT" ] || usage
[ -n "$RELAUNCH_PATH" ] || usage

log "Log: $LOG_FILE"
log "platform=$PLATFORM install_target=$INSTALL_TARGET staging_root=$STAGING_ROOT"

# --- Wait for the app to exit --------------------------------------------------
wait_for_exit() {
  # Poll for up to ~30s for the parent process to terminate.
  i=0
  while [ "$i" -lt 60 ]; do
    if ! kill -0 "$PID" 2>/dev/null; then
      return 0
    fi
    sleep 0.5
    i=$((i + 1))
  done
  # Last resort: ask it to terminate, then give it a moment.
  kill "$PID" 2>/dev/null || true
  i=0
  while [ "$i" -lt 20 ]; do
    kill -0 "$PID" 2>/dev/null || return 0
    sleep 0.5
    i=$((i + 1))
  done
  return 1
}

relaunch() {
  if [ "$PLATFORM" = "macos" ]; then
    open "$RELAUNCH_PATH" >/dev/null 2>&1 || true
  else
    # Detach the new process from this helper so it keeps running after we exit.
    ( "$RELAUNCH_PATH" >/dev/null 2>&1 & ) || true
  fi
}

rollback() {
  log "Update failed; rolling back."
  if [ -n "$BACKUP_DIR" ] && [ -e "$BACKUP_DIR" ]; then
    rm -rf "$INSTALL_TARGET" 2>/dev/null || true
    mv "$BACKUP_DIR" "$INSTALL_TARGET" 2>/dev/null || true
  fi
  relaunch
  exit 1
}

# Copy a file from backup into the new install only if it is missing there.
restore_file() {
  _src="$BACKUP_DIR/$1"
  _dst="$INSTALL_TARGET/$1"
  if [ -e "$_src" ] && [ ! -e "$_dst" ]; then
    cp -R "$_src" "$_dst" 2>/dev/null || true
  fi
}

restore_user_data_linux() {
  # Linux stores config/db inside the install dir by default; preserve it.
  for f in config.json rss.db rss.db-wal rss.db-shm rss.db-journal; do
    restore_file "$f"
  done
  restore_file "podcasts"
  restore_file "sounds"
}

if ! wait_for_exit; then
  # The app is still running and we couldn't stop it. Leave the (intact) install
  # alone and do NOT relaunch -- relaunching would spawn a duplicate instance.
  log "App (pid $PID) did not exit; aborting to avoid a partial update."
  exit 1
fi
# Give the OS a moment to release file handles.
sleep 1

# From here on the app has exited, so any abort should relaunch the intact install.
if [ ! -e "$STAGING_ROOT" ]; then
  log "Staging path not found: $STAGING_ROOT"
  relaunch
  exit 1
fi

# --- Back up the current install ----------------------------------------------
if [ -e "$INSTALL_TARGET" ]; then
  log "Backing up current install to $BACKUP_DIR"
  if ! mv "$INSTALL_TARGET" "$BACKUP_DIR" 2>>"$LOG_FILE"; then
    log "Backup move failed."
    relaunch
    exit 1
  fi
fi

# --- Apply the staged build ---------------------------------------------------
log "Applying update."
apply_ok=0
if [ "$PLATFORM" = "macos" ] && command -v ditto >/dev/null 2>&1; then
  # ditto preserves bundle metadata and the (ad-hoc) code signature.
  if ditto "$STAGING_ROOT" "$INSTALL_TARGET" >>"$LOG_FILE" 2>&1; then
    apply_ok=1
  fi
else
  # Prefer a fast rename when on the same filesystem; fall back to a copy.
  if mv "$STAGING_ROOT" "$INSTALL_TARGET" 2>/dev/null; then
    apply_ok=1
  elif cp -R "$STAGING_ROOT" "$INSTALL_TARGET" >>"$LOG_FILE" 2>&1; then
    apply_ok=1
  fi
fi

if [ "$apply_ok" != "1" ]; then
  rollback
fi

if [ "$PLATFORM" = "linux" ]; then
  log "Restoring user data."
  restore_user_data_linux
  # Ensure the relaunch binary stays executable.
  [ -e "$RELAUNCH_PATH" ] && chmod +x "$RELAUNCH_PATH" 2>/dev/null || true
fi

# --- Relaunch and clean up ----------------------------------------------------
log "Launching updated app."
relaunch

rm -rf "$BACKUP_DIR" 2>/dev/null || true
if [ -n "$TEMP_ROOT" ] && [ -d "$TEMP_ROOT" ]; then
  case "$TEMP_ROOT" in
    *BlindRSS_update_*) rm -rf "$TEMP_ROOT" 2>/dev/null || true ;;
  esac
fi

rm -f "$LOG_FILE" 2>/dev/null || true
exit 0
