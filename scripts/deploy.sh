#!/usr/bin/env bash
#
# House of Desserts — one-command deployment.
#
#   ./scripts/deploy.sh              deploy the latest code (asks first)
#   ./scripts/deploy.sh --yes        same, no questions (for a cron job)
#   ./scripts/deploy.sh --dry-run    show what would happen, change nothing
#   ./scripts/deploy.sh --rollback   undo the last deployment
#   ./scripts/deploy.sh --status     is everything healthy right now?
#   ./scripts/deploy.sh --test       run the test suite first, and stop if it fails
#
# What it does, in order, and why:
#
#   1. Preflight   — is this the right machine, is git clean, is there disk,
#                    is another deploy already running
#   2. Show        — exactly which commits are about to land, and whether the
#                    release changes the database
#   2b. Release    — that the release is complete: it has a dated entry in
#                    CHANGELOG.md, and that entry is not older than the code.
#                    A release nobody can read about later may as well not
#                    have happened, so this is a stop, not a warning.
#   3. Back up     — a consistent snapshot of bakery.db, verified, BEFORE
#                    anything is touched
#   4. Update      — git pull, pip install
#   5. Migrate     — alembic upgrade head (a no-op when nothing changed)
#   6. Restart     — systemctl restart, then wait for the app to answer
#   7. Verify      — /health plus four real pages, and the schema revision
#   8. Report      — what happened, in plain words, with the log path
#
# If anything fails after step 3, it puts everything back the way it was and
# says so. Nothing is left half-deployed.
#
# Designed to be run by someone who does not know Unix: every line of output
# says what is happening and what to do if it goes wrong.
#
# THIS SCRIPT MUST GROW WITH THE APP. Every release that adds something a
# person could check — a version, a config value, a required file — adds a
# check here, and a test in tests/test_deploy_script.py fails if a known
# check disappears. See the checklist in that file.
#
set -uo pipefail

# ---------------------------------------------------------------------------
# Configuration. Every value can be overridden with an environment variable,
# which is how the test harness exercises this script without a real server.
# ---------------------------------------------------------------------------
# The app folder is wherever this script lives, minus the scripts/ level —
# so the same file works on the server, in a container, or in a test harness
# without editing paths.
# Resolve symlinks, so the script can be linked into PATH (e.g.
# /usr/local/bin/hod-deploy) and still find the app it belongs to.
SELF="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
  SELF="$(readlink -f "$SELF" 2>/dev/null || printf '%s' "$SELF")"
fi
SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"
APP_DIR="${HOD_APP_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# Data and backup folders are read from .env below, because that is the one
# place the app already keeps them. HOD_* overrides win when set.
DATA_DIR="${HOD_DATA_DIR:-}"
BACKUP_DIR="${HOD_BACKUP_DIR:-}"

SERVICE="${HOD_SERVICE:-hod}"
BASE_URL="${HOD_URL:-http://127.0.0.1:8000}"
BRANCH="${HOD_BRANCH:-main}"
LOG_DIR="${HOD_LOG_DIR:-$HOME/hod-deploys}"
STATE_FILE="$LOG_DIR/last-deploy"

SYSTEMCTL_BIN="${HOD_SYSTEMCTL:-systemctl}"     # override only for testing
HEALTH_RETRIES="${HOD_HEALTH_RETRIES:-30}"      # seconds to wait for the app
MIN_FREE_MB="${HOD_MIN_FREE_MB:-300}"

ASSUME_YES=0
DRY_RUN=0
RUN_TESTS=0
FORCE=0
ACTION="deploy"

for arg in "$@"; do
  case "$arg" in
    -y|--yes)      ASSUME_YES=1 ;;
    -n|--dry-run)  DRY_RUN=1; ASSUME_YES=1 ;;
    --force)       FORCE=1 ;;
    --rollback)    ACTION="rollback" ;;
    --status)      ACTION="status" ;;
    --test)        RUN_TESTS=1 ;;
    -h|--help)     sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg  (try --help)"; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# Output helpers. Plain words, no jargon.
# ---------------------------------------------------------------------------
BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
YELLOW=$'\033[33m'; BLUE=$'\033[36m'; OFF=$'\033[0m'

[ -t 1 ] || { BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""; }

say()  { printf '%s\n' "$*"; }
hr()   { printf '%s\n' "────────────────────────────────────────────────────────────"; }
step() { printf '\n%s%s%s\n' "$BOLD" "$*" "$OFF"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$OFF" "$*"; }
info() { printf '  %s·%s %s\n' "$DIM" "$OFF" "$*"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$OFF" "$*"; }
bad()  { printf '  %s✗%s %s\n' "$RED" "$OFF" "$*"; }

die() {
  printf '\n%s✗ STOPPED%s  %s\n\n' "$RED" "$OFF" "$*"
  [ -n "${LOG_FILE:-}" ] && printf '%sFull log: %s%s\n\n' "$DIM" "$LOG_FILE" "$OFF"
  exit 1
}

# ---------------------------------------------------------------------------
# Rollback state. Filled in as the deploy progresses so the cleanup handler
# knows how far it got.
# ---------------------------------------------------------------------------
PREV_SHA=""
NEW_SHA=""
BACKUP_FILE=""
MIGRATION_RAN=0
CODE_UPDATED=0
SUDO=""

# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Required command '$1' is not installed."; }

py() { "$APP_DIR/.venv/bin/python" "$@"; }

alembic_() { ( cd "$APP_DIR" && "$APP_DIR/.venv/bin/alembic" "$@" 2>/dev/null ); }

schema_current() {
  local out
  out="$(alembic_ current | grep -oE '[0-9a-f]{12}' | head -1)"
  printf '%s' "${out:-none}"
}

schema_head() {
  local out
  out="$( cd "$APP_DIR" && "$APP_DIR/.venv/bin/alembic" heads 2>/dev/null | grep -oE '[0-9a-f]{12}' | head -1 )"
  printf '%s' "${out:-none}"
}

# -L: the app answers /orders with a 307 to /orders/ (canonical form).
# Without following it, every check would report a failure that is not one.
http_code() { curl -sL -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || printf '000'; }

http_has() {  # url, needle
  # Read the whole body first, then match. Piping straight into `grep -q`
  # makes grep exit early, curl die of SIGPIPE, and with `set -o pipefail`
  # the pipeline reports failure even though the match was found — which
  # would fail a perfectly good deploy.
  local body
  body="$(curl -sL --max-time 10 "$1" 2>/dev/null)" || return 1
  grep -qi -- "$2" <<<"$body"
}

# 9>&- : do not hand the deploy lock to the service we are starting. On a
# real systemd the unit is forked by systemd, not by us, but a wrapper or a
# test shim would inherit it and hold the lock for as long as the app runs.
ctl() { $SUDO "$SYSTEMCTL_BIN" "$@" 2>/dev/null 9>&-; }

service_state() { ctl is-active "$SERVICE" || printf 'unknown'; }

restart_service() { ctl restart "$SERVICE"; }

stop_service() { ctl stop "$SERVICE"; }

start_service() { ctl start "$SERVICE"; }

wait_for_app() {
  local i
  for ((i = 1; i <= HEALTH_RETRIES; i++)); do
    if [ "$(http_code "$BASE_URL/health")" = "200" ]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

confirm() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  printf '\n%sProceed?%s [y/N] ' "$BOLD" "$OFF"
  local answer
  read -r answer || answer=""
  case "$answer" in
    y|Y|yes|YES) return 0 ;;
    *) say "Nothing was changed."; exit 0 ;;
  esac
}

# ---------------------------------------------------------------------------
# The sanity checks that run after the app is back up. These are the point of
# the whole exercise: "the service started" is not the same as "the app works".
# ---------------------------------------------------------------------------
run_checks() {
  local failures=0

  if [ "$(http_code "$BASE_URL/health")" = "200" ]; then
    ok "health endpoint answers"
  else
    bad "health endpoint does not answer"
    failures=$((failures + 1))
  fi

  local page name needle
  while IFS='|' read -r page name needle; do
    [ -z "$page" ] && continue
    local code
    code="$(http_code "$BASE_URL$page")"
    if [ "$code" = "200" ] && http_has "$BASE_URL$page" "$needle"; then
      ok "$name page loads"
    else
      bad "$name page failed (HTTP $code)"
      failures=$((failures + 1))
    fi
  done <<'PAGES'
/today|Today|Today
/orders/|Orders|Orders
/customers/|Customers|Customers
/b2b/|Partners|Partners
PAGES

  local head current
  head="$(schema_head)"
  current="$(schema_current)"
  if [ "$head" = "none" ]; then
    info "no migrations in this release"
  elif [ "$current" = "$head" ]; then
    ok "database schema matches the code"
  else
    bad "database schema is at $current but the code expects $head"
    failures=$((failures + 1))
  fi

  return "$failures"
}

# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------
take_backup() {
  local out newest
  out="$( cd "$APP_DIR" && py scripts/backup.py --env "$APP_DIR/.env" 2>&1 )" || {
    printf '%s\n' "$out" | tail -5
    return 1
  }
  newest="$(find "$BACKUP_DIR" -name bakery.db -newermt '-5 minutes' 2>/dev/null | head -1)"
  [ -n "$newest" ] || newest="$(ls -t "$BACKUP_DIR"/*/bakery.db 2>/dev/null | head -1)"
  [ -n "$newest" ] || return 1

  # Verify the file is a readable SQLite database before trusting it.
  if py - "$newest" <<'PY' >/dev/null 2>&1
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("PRAGMA quick_check").fetchone()
con.execute("SELECT count(*) FROM sqlite_master").fetchone()
con.close()
PY
  then
    BACKUP_FILE="$newest"
    return 0
  fi
  return 1
}

restore_backup() {
  [ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ] || return 1
  stop_service
  cp -f "$BACKUP_FILE" "$DATA_DIR/bakery.db" || return 1
  rm -f "$DATA_DIR/bakery.db-wal" "$DATA_DIR/bakery.db-shm" 2>/dev/null
  start_service
  return 0
}

# ---------------------------------------------------------------------------
# Rollback: put the code and the database back, then prove it is healthy.
# ---------------------------------------------------------------------------
rollback() {
  local reason="$1"
  printf '\n'
  hr
  printf '%s  ROLLING BACK%s\n' "$BOLD$YELLOW" "$OFF"
  hr
  say "  Reason: $reason"

  if [ "$MIGRATION_RAN" -eq 1 ] && [ -n "$BACKUP_FILE" ]; then
    if restore_backup; then
      ok "database restored from $BACKUP_FILE"
    else
      bad "could not restore the database automatically"
      say "     Restore it by hand:"
      say "       sudo systemctl stop $SERVICE"
      say "       cp $BACKUP_FILE $DATA_DIR/bakery.db"
      say "       sudo systemctl start $SERVICE"
    fi
  fi

  if [ "$CODE_UPDATED" -eq 1 ] && [ -n "$PREV_SHA" ]; then
    if ( cd "$APP_DIR" && git reset --hard "$PREV_SHA" >/dev/null 2>&1 && \
         "$APP_DIR/.venv/bin/pip" install -q -e . >/dev/null 2>&1 ); then
      ok "code put back to $PREV_SHA"
    else
      bad "could not put the code back automatically"
    fi
  fi

  if restart_service && wait_for_app; then
    ok "app is answering again"
  else
    bad "the app is NOT answering"
    say "     Run:  sudo journalctl -u $SERVICE -n 50 --no-pager"
  fi

  printf '\n'
  hr
  printf '%s  DEPLOYMENT FAILED — THE BAKERY IS BACK ON THE OLD VERSION%s\n' "$BOLD$YELLOW" "$OFF"
  hr
  say "  Nothing is half-deployed. Your data was restored from the backup"
  say "  taken minutes ago, and the app is running the previous version."
  say ""
  say "  What to do next:"
  say "    1. Send this file to Puneet:  $LOG_FILE"
  say "    2. Nothing else. The bakery can keep working."
  say ""
  exit 1
}

# ---------------------------------------------------------------------------
# Status mode — read-only health report, safe to run any time.
# ---------------------------------------------------------------------------
# The "· v1.5 (26 November 2026)" tail for the status line, or empty.
release_suffix() {
  local line v d
  line="$( cd "$APP_DIR" && git show HEAD:CHANGELOG.md 2>/dev/null | release_line )"
  [ -n "$line" ] || return 0
  v="${line%%|*}"; d="${line#*|}"
  printf '  ·  %s (%s)' "$v" "$d"
}

# --- release identity ------------------------------------------------------
# The app has no version file: the changelog is the record, and its newest
# entry is the version being run. Reading it from the commit that is about to
# be deployed means the check is about the incoming release, not the current
# one — which is the only version that matters at deploy time.

# Prints "v1.5|26 November 2026" from a changelog on stdin, or nothing.
release_line() {
  awk '
    /^## / {
      line = $0
      sub(/^##[ \t]+/, "", line)
      n = split(line, parts, /—|–|·| - /)
      if (n >= 2) { v = parts[1]; d = parts[2] } else { v = line; d = "" }
      gsub(/^[ \t]+|[ \t]+$/, "", v)
      gsub(/^[ \t]+|[ \t]+$/, "", d)
      print v "|" d
      exit
    }
  '
}

# "26 November 2026" → seconds. Returns 0 when the date is unparseable, so a
# malformed date never silently passes a comparison.
date_epoch() {
  date -d "$1" +%s 2>/dev/null || echo 0
}

# The first few entries of the newest release, for the operator to read.
# Continuation lines are joined, because a changelog entry is hand-wrapped
# and half a sentence on the terminal is worse than none.
release_summary() {
  awk '
    function flush() {
      if (buf != "") {
        gsub(/\*\*/, "", buf)
        print buf
        n++
        buf = ""
      }
    }
    /^## / { if (seen) { flush(); exit } seen = 1; next }
    !seen { next }
    /^### / { next }
    /^- / {
      flush()
      if (n >= 4) exit
      buf = $0
      sub(/^- /, "", buf)
      next
    }
    /^[ \t]+/ {
      if (buf != "") { line = $0; gsub(/^[ \t]+/, "", line); buf = buf " " line }
      next
    }
    END { flush() }
  '
}

do_status() {
  hr
  printf '%s  HOUSE OF DESSERTS — status%s\n' "$BOLD" "$OFF"
  hr
  say ""
  info "service:  $SERVICE is $(service_state)"
  info "version:  $( cd "$APP_DIR" && git rev-parse --short HEAD 2>/dev/null || echo unknown )$(release_suffix)"
  info "schema:   $(schema_current) (code expects $(schema_head))"
  info "data:     $(du -sh "$DATA_DIR" 2>/dev/null | cut -f1 || echo '?')"
  info "backups:  $(ls -1d "$BACKUP_DIR"/*/ 2>/dev/null | wc -l) days kept"
  say ""
  local failures=0
  run_checks || failures=$?
  say ""
  if [ "$failures" -eq 0 ]; then
    printf '  %sEverything is healthy.%s\n\n' "$GREEN$BOLD" "$OFF"
    exit 0
  fi
  printf '  %s%d check(s) failed.%s  Look at: sudo journalctl -u %s -n 50 --no-pager\n\n' \
    "$RED$BOLD" "$failures" "$OFF" "$SERVICE"
  exit 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/deploy-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

hr
printf '%s  HOUSE OF DESSERTS — deployment%s\n' "$BOLD" "$OFF"
printf '%s  %s%s\n' "$DIM" "$(date '+%A %d %B %Y, %H:%M')" "$OFF"
hr

# --- 0. Preflight -----------------------------------------------------------
step "Checking this is the right machine"

[ -d "$APP_DIR/.git" ] || die "Cannot find the app at $APP_DIR.
  This script must run on the server, from inside the app folder.
  If you are on your laptop, connect to the server first."
ok "app folder found"

[ -f "$APP_DIR/.env" ] || die "The settings file .env is missing from $APP_DIR.
  Without it the app cannot start. Ask Puneet to restore it."
ok "settings file found"

# Where the database and the backups actually live, according to .env.
env_value() { grep -E "^$1=" "$APP_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2-; }
abspath() { case "$1" in /*) printf '%s' "$1" ;; *) printf '%s/%s' "$APP_DIR" "$1" ;; esac; }

if [ -z "$DATA_DIR" ]; then
  DB_PATH="$(env_value DB_URL)"
  DB_PATH="${DB_PATH#sqlite:///}"
  if [ -n "$DB_PATH" ]; then
    DATA_DIR="$(dirname "$(abspath "$DB_PATH")")"
  else
    DATA_DIR="$APP_DIR/data"
  fi
fi

if [ -z "$BACKUP_DIR" ]; then
  BACKUP_DIR="$(env_value BACKUP_DIR)"
  BACKUP_DIR="$(abspath "${BACKUP_DIR:-./backups}")"
fi

[ -x "$APP_DIR/.venv/bin/python" ] || die "The Python environment is missing at $APP_DIR/.venv.
  Ask Puneet to rebuild it."
ok "python environment found"

need_cmd git
need_cmd curl

if [ -n "${HOD_SYSTEMCTL:-}" ]; then
  SUDO=""
  [ -x "$SYSTEMCTL_BIN" ] || die "HOD_SYSTEMCTL points at $SYSTEMCTL_BIN, which is not executable."
elif [ "$(id -u)" -eq 0 ]; then
  SUDO=""
elif sudo -n true 2>/dev/null; then
  SUDO="sudo"
else
  die "This script needs permission to restart the app service, and 'sudo' here
  asks for a password.

  Run it as the user that owns the app on the server. If sudo still asks
  for a password, ask Puneet to allow passwordless sudo for systemctl."
fi
ok "permission to restart the service"

FREE_MB="$(df -Pm "$APP_DIR" | awk 'NR==2 {print $4}')"
[ "${FREE_MB:-0}" -ge "$MIN_FREE_MB" ] || die "Only ${FREE_MB} MB of disk space left; need at least ${MIN_FREE_MB} MB.
  Free some space first:  sudo journalctl --vacuum-size=100M"
ok "disk space: ${FREE_MB} MB free"

if [ "$ACTION" = "status" ]; then do_status; fi

# One deploy at a time.
LOCK_FILE="$LOG_DIR/.deploy.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  die "Another deployment is already running.
  Wait for it to finish, or check:  ps aux | grep deploy.sh"
fi

cd "$APP_DIR" || die "Cannot enter $APP_DIR"

# Only edits to TRACKED files block a deploy. Untracked files (a stray log,
# a backup someone copied in) are reported but not treated as a problem —
# git itself refuses a pull that would overwrite one.
DIRTY="$(git status --porcelain --untracked-files=no 2>/dev/null)"
if [ -n "$DIRTY" ] && [ "$FORCE" -eq 0 ]; then
  printf '%s\n' "$DIRTY" | head -10 | sed 's/^/    /'
  die "Some files on the server were edited by hand, and a deploy would
  overwrite them.

  If nobody edited anything deliberately, undo the changes with:
    cd $APP_DIR && git reset --hard origin/$BRANCH

  Then run this script again."
fi

UNTRACKED="$(git status --porcelain --untracked-files=normal 2>/dev/null | grep -c '^??')"
[ "${UNTRACKED:-0}" -gt 0 ] && info "ignoring ${UNTRACKED} untracked file(s) — they will not be touched"

# --- rollback mode ----------------------------------------------------------
if [ "$ACTION" = "rollback" ]; then
  [ -f "$STATE_FILE" ] || die "There is no record of a previous deployment to undo."
  # shellcheck disable=SC1090
  . "$STATE_FILE"
  PREV_SHA="${LAST_PREV_SHA:-}"
  BACKUP_FILE="${LAST_BACKUP:-}"

  if [ -z "$PREV_SHA" ]; then
    die "The last deployment did not change the code — it only brought the
  database up to date. Undoing it would restore the OLD database while
  leaving the NEW code in place, which breaks every page.

  If that is really what you want, do it by hand:
    cd $APP_DIR
    sudo systemctl stop $SERVICE
    cp $BACKUP_FILE $DATA_DIR/bakery.db
    git reset --hard <the version you want>
    sudo systemctl start $SERVICE"
  fi

  rollback "you asked to undo the last deployment"
fi

# --- 1. What is about to happen --------------------------------------------
step "Looking for new code"

git fetch --quiet origin "$BRANCH" 2>/dev/null || die "Cannot reach GitHub.
  Check the server's internet connection, then try again."

PREV_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")"
[ -n "$REMOTE_SHA" ] || die "Cannot find the '$BRANCH' branch on GitHub."

CUR_REV="$(schema_current)"
HEAD_REV="$( cd "$APP_DIR" && "$APP_DIR/.venv/bin/alembic" heads 2>/dev/null | grep -oE '[0-9a-f]{12}' | head -1 )"
SCHEMA_BEHIND=0
[ "$CUR_REV" != "none" ] && [ "$HEAD_REV" != "none" ] && [ "$CUR_REV" != "$HEAD_REV" ] && SCHEMA_BEHIND=1

if [ "$PREV_SHA" = "$REMOTE_SHA" ]; then
  ok "already up to date ($(git rev-parse --short HEAD))"

  if [ "$SCHEMA_BEHIND" -eq 1 ]; then
    # No new code, but the database was never brought up to date — the exact
    # state a deploy leaves behind when the migration step is skipped.
    warn "the database is at $CUR_REV but the code expects $HEAD_REV"
    info "repairing it now (backup, migrate, restart)"
    MIGRATION_NEEDED=1
    PENDING=0
    NEW_SHA="$PREV_SHA"
  else
    step "Running health checks anyway"
    if run_checks; then
      printf '\n  %sNothing to deploy, and everything is healthy.%s\n\n' "$GREEN$BOLD" "$OFF"
      exit 0
    fi
    die "There is no new code, but the app is not healthy. Look at:
  sudo journalctl -u $SERVICE -n 50 --no-pager"
  fi
else
  PENDING="$(git rev-list --count "HEAD..origin/$BRANCH")"
  NEW_SHA="$REMOTE_SHA"
  ok "$PENDING change(s) to install"
  say ""
  git --no-pager log --oneline --no-decorate "HEAD..origin/$BRANCH" | sed 's/^/    /'
fi

# --- release check ----------------------------------------------------------
# Everything here is checked against the code being DEPLOYED, read out of the
# incoming commit, not the copy on disk.
step "Checking the release is complete"

INCOMING_CHANGELOG="$(git show "$REMOTE_SHA:CHANGELOG.md" 2>/dev/null || echo "")"
INCOMING_RELEASE="$(printf '%s' "$INCOMING_CHANGELOG" | release_line)"
INCOMING_COMMIT_DATE="$(git show -s --format=%cd --date=format:'%-d %B %Y' "$REMOTE_SHA")"

if [ -z "$INCOMING_RELEASE" ]; then
  die "This release has no entry in CHANGELOG.md.
  The What's new page reads that file, so without an entry the release is
  invisible to whoever runs the bakery. Add one, push, and deploy again."
fi

INCOMING_VERSION="${INCOMING_RELEASE%%|*}"
INCOMING_DATE="${INCOMING_RELEASE#*|}"

if [ -z "$INCOMING_DATE" ]; then
  die "The newest CHANGELOG.md entry has no date: '$INCOMING_VERSION'.
  Write it as '## v1.6 — 27 November 2026'."
fi

INCOMING_EPOCH="$(date_epoch "$INCOMING_DATE")"
if [ "$INCOMING_EPOCH" -eq 0 ]; then
  # Unreadable, not merely old. Saying 'behind the code' here would send
  # someone looking for the wrong problem.
  die "The newest CHANGELOG.md entry has a date the server cannot read: '$INCOMING_DATE'.
  Write it as '## v1.6 — 27 November 2026'."
fi

# A release dated before the commit it ships in means the changelog was not
# updated with the code. Both dates are day-resolution, so this catches a
# forgotten entry rather than an hour's drift.
if [ "$INCOMING_EPOCH" -lt "$(date_epoch "$INCOMING_COMMIT_DATE")" ]; then
  die "CHANGELOG.md is behind the code.
  The newest entry is $INCOMING_VERSION, dated $INCOMING_DATE,
  but the commit being deployed is dated $INCOMING_COMMIT_DATE.
  Add an entry for what changed, push, and deploy again."
fi

ok "$INCOMING_VERSION — $INCOMING_DATE"
printf '%s\n' "$INCOMING_CHANGELOG" | release_summary | sed 's/^/      /'

if [ "$RUN_TESTS" -eq 1 ]; then
  step "Running the test suite"
  if "$APP_DIR/.venv/bin/python" -c "import pytest" 2>/dev/null; then
    if ( cd "$APP_DIR" && SECRET_KEY="${SECRET_KEY:-deploy-check}" DEBUG=true \
         "$APP_DIR/.venv/bin/python" -m pytest --ignore=tests/ui -q 2>&1 | tail -5 ); then
      ok "tests pass"
    else
      die "The test suite failed. Nothing was deployed.
  Run it yourself to see why:  cd $APP_DIR && .venv/bin/python -m pytest --ignore=tests/ui"
    fi
  else
    warn "pytest is not installed here — skipping (install with: pip install -e '.[dev]')"
  fi
fi

step "Checking whether this release changes the database"
REMOTE_MIGRATIONS="$(git diff --name-only "HEAD..origin/$BRANCH" -- alembic/versions/ | wc -l | tr -d ' ')"

if [ "${REMOTE_MIGRATIONS:-0}" -gt 0 ]; then
  MIGRATION_NEEDED=1
  warn "yes — this release adds database changes"
  info "a backup will be taken first, and can be restored automatically"
elif [ "$SCHEMA_BEHIND" -eq 1 ]; then
  MIGRATION_NEEDED=1
  warn "the database is behind the code — it will be brought up to date"
elif [ "${MIGRATION_NEEDED:-0}" -eq 1 ]; then
  warn "the database is behind the code — it will be brought up to date"
else
  MIGRATION_NEEDED=0
  ok "no — data is not affected by this release"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  printf '\n%sDRY RUN — nothing was changed.%s\n\n' "$BLUE$BOLD" "$OFF"
  exit 0
fi

confirm

# --- 2. Backup --------------------------------------------------------------
step "Backing up the database"
say "  ${DIM}(a complete copy of every order, customer and payment)${OFF}"

if take_backup; then
  SIZE="$(du -h "$BACKUP_FILE" | cut -f1)"
  ok "saved: $BACKUP_FILE ($SIZE)"
else
  die "The backup could not be taken or could not be verified, so the deploy
  was stopped before anything changed. Your data is untouched.

  Try running the backup by hand to see the error:
    cd $APP_DIR && .venv/bin/python scripts/backup.py --env .env"
fi

# From here on, any failure triggers rollback.
FAILED_AT=""

# --- 3. Code ----------------------------------------------------------------
step "Installing the new version"
if ! git pull --ff-only --quiet origin "$BRANCH"; then
  FAILED_AT="could not download the new code"
else
  CODE_UPDATED=1
  ok "code updated to $(git rev-parse --short HEAD)"
  if py -m pip install -q -e . ; then
    ok "dependencies up to date"
  else
    FAILED_AT="could not install the dependencies"
  fi
fi

# --- 4. Migrations ----------------------------------------------------------
if [ -z "$FAILED_AT" ]; then
  step "Updating the database structure"
  if [ "$MIGRATION_NEEDED" -eq 1 ]; then
    MIGRATION_RAN=1
    if ( cd "$APP_DIR" && "$APP_DIR/.venv/bin/alembic" upgrade head >/dev/null 2>&1 ); then
      ok "database updated to $(schema_current)"
    else
      FAILED_AT="the database update failed"
      say "  ${DIM}(the error above, if any, is in the log)${OFF}"
      ( cd "$APP_DIR" && "$APP_DIR/.venv/bin/alembic" upgrade head 2>&1 | tail -5 | sed 's/^/    /' )
    fi
  else
    info "nothing to update"
  fi
fi

# --- 5. Restart -------------------------------------------------------------
if [ -z "$FAILED_AT" ]; then
  step "Restarting the app"
  if restart_service; then
    ok "service restarted"
  else
    FAILED_AT="the service would not restart"
  fi
fi

if [ -z "$FAILED_AT" ]; then
  say "  ${DIM}(waiting up to ${HEALTH_RETRIES}s for it to answer)${OFF}"
  if wait_for_app; then
    ok "app is answering"
  else
    FAILED_AT="the app did not come back up within ${HEALTH_RETRIES}s"
  fi
fi

# --- 6. Sanity checks -------------------------------------------------------
if [ -z "$FAILED_AT" ]; then
  step "Checking that the app actually works"
  if ! run_checks; then
    FAILED_AT="one or more checks failed after the restart"
  fi
fi

if [ -n "$FAILED_AT" ]; then
  rollback "$FAILED_AT"
fi

# --- 7. Remember what happened, for --rollback ------------------------------
# Record a previous version only when the code actually moved. A
# schema-only repair has nothing to roll the code back to, and --rollback
# must refuse rather than restore an old database under new code.
if [ "$PREV_SHA" = "$(git rev-parse HEAD 2>/dev/null)" ]; then
  RECORD_PREV=""
else
  RECORD_PREV="$PREV_SHA"
fi

cat > "$STATE_FILE" <<EOF
LAST_PREV_SHA=$RECORD_PREV
LAST_NEW_SHA=$NEW_SHA
LAST_BACKUP=$BACKUP_FILE
LAST_DEPLOYED_AT=$(date -Iseconds)
EOF

# --- 8. Report --------------------------------------------------------------
printf '\n'
hr
printf '%s  ✓ DEPLOYED SUCCESSFULLY%s\n' "$BOLD$GREEN" "$OFF"
hr
if [ "$PREV_SHA" = "$(git rev-parse HEAD)" ]; then
  say "  Version:  $(git rev-parse --short HEAD)  $(release_suffix)   (code was already at this version)"
else
  say "  Version:  $(git rev-parse --short HEAD)  $(release_suffix)   (was $(git rev-parse --short "$PREV_SHA"))"
fi
say "  Backup:   $BACKUP_FILE"
say "  Time:     ${SECONDS}s"
say ""
say "  ${BOLD}Open the app:${OFF}  $BASE_URL"
say ""
say "  ${DIM}If something looks wrong later:${OFF}"
say "    ./scripts/deploy.sh --status      check everything is healthy"
say "    ./scripts/deploy.sh --rollback    undo this deployment"
say "    sudo journalctl -u $SERVICE -n 50 --no-pager"
say ""
say "  ${DIM}Full log of this deployment: $LOG_FILE${OFF}"
say ""
