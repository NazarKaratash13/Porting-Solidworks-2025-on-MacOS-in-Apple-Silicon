#!/bin/bash
# Installed as Contents/MacOS/SOLIDWORKS in the standalone bundle.
set -u
original_umask="$(umask)"
umask 077

BUNDLE="$(cd "$(/usr/bin/dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)" || exit 1
RUNTIME="$BUNDLE/Contents/Resources/runtime/CrossOver"
TEMPLATE="$BUNDLE/Contents/Resources/prefix-template"
DATA="$HOME/Library/Application Support/SOLIDWORKS 2025"
PREFIX="$DATA/prefix"
LOG="$DATA/launch.log"
WINE="$RUNTIME/lib/wine/x86_64-unix/wine"
PROGRAM='C:\Program Files\SOLIDWORKS\SLDWORKS.exe'
PROGRAM_PATH='drive_c/Program Files/SOLIDWORKS/SLDWORKS.exe'

log() {
    printf '[%s] pid=%s %s\n' "$(/bin/date '+%Y-%m-%d %H:%M:%S')" "$$" "$*" >> "$LOG"
}

fail() {
    log "$*"
    printf '%s\n' "$*" >&2
    exit 1
}

busy() {
    log "$*"
    printf '%s\n' "$*" >&2
    exit 75
}

process_identity() {
    # exec retains both the PID and its start time. Ignore unreaped zombies.
    LC_ALL=C /bin/ps -p "$1" -o stat= -o lstart= |
        /usr/bin/awk '$1 !~ /^Z/ && NF == 6 { $1 = ""; sub(/^ +/, ""); print }'
}

/bin/mkdir -p "$DATA" || exit 1
exec 9>>"$DATA/launch.lock" || fail "Cannot open launch lock."
/usr/bin/lockf -s -t 0 9
case $? in
    0) ;;
    75) busy "SOLIDWORKS is preparing another launch." ;;
    *) fail "Cannot acquire launch lock." ;;
esac

# The record follows the launch process through exec without inheriting the
# lock in wineserver or helper processes. Keep it until the next launch.
if [[ -f "$DATA/launch.pid" ]]; then
    {
        read -r previous_pid
        read -r previous_start
    } < "$DATA/launch.pid"
    if [[ "$previous_pid" =~ ^[0-9]+$ && -n "$previous_start" &&
          "$(process_identity "$previous_pid")" == "$previous_start" ]]; then
        busy "SOLIDWORKS is still running (PID $previous_pid). Close it from SOLIDWORKS before starting another session."
    fi
fi

if [[ -d "$PREFIX" ]]; then
    # Recognize sessions started by older launchers without a launch record.
    # An executable mapped from the exact prefix distinguishes other bottles.
    prefix_path="$(cd "$PREFIX" && pwd -P)" || fail "Cannot resolve Wine prefix."
    while read -r candidate command; do
        case "$command" in
            *\\SLDWORKS.exe|SLDWORKS.exe)
                if /usr/sbin/lsof -a -p "$candidate" -d txt -Fn 2>/dev/null |
                    /usr/bin/grep -Fxq "n$prefix_path/$PROGRAM_PATH"; then
                    busy "SOLIDWORKS is still running in this prefix (PID $candidate)."
                fi
                ;;
        esac
    done < <(/bin/ps -axo pid=,comm=)
fi

log "Launch from $BUNDLE"
[[ -x "$WINE" ]] || fail "Wine loader is missing at $WINE."

if [[ ! -e "$PREFIX/.sw-ready" ]]; then
    if [[ -e "$PREFIX" || -L "$PREFIX" ]]; then
        fail "Existing Wine prefix has no .sw-ready marker. Check it before retrying: $PREFIX"
    fi
    [[ -f "$TEMPLATE/$PROGRAM_PATH" && -f "$TEMPLATE/system.reg" ]] ||
        fail "Wine prefix template is incomplete."

    staging="$(/usr/bin/mktemp -d "$DATA/prefix-copy.XXXXXX")" ||
        fail "Cannot create a directory for the prefix copy."
    log "Creating Wine prefix from template."
    if /bin/cp -cR "$TEMPLATE" "$staging/prefix" 2>>"$LOG"; then
        copy="$staging/prefix"
    else
        copy="$staging/fallback"
        /bin/cp -R "$TEMPLATE" "$copy" 2>>"$LOG" ||
            fail "Wine prefix copy failed. Copy directory: $staging"
    fi
    : > "$copy/.sw-ready" || fail "Cannot mark the Wine prefix ready."
    /bin/mv "$copy" "$PREFIX" || fail "Cannot install the Wine prefix."
    /bin/rmdir "$staging" 2>/dev/null || log "Retained prefix copy directory: $staging"
fi

[[ -f "$PREFIX/$PROGRAM_PATH" ]] || fail "SOLIDWORKS executable is missing in $PREFIX."
cd "$PREFIX/drive_c" || fail "Cannot enter the Wine working directory."

export WINEPREFIX="$PREFIX"
export WINEDEBUG=-all
export WINEDLLOVERRIDES="concrt140=n,b"
export LANG=ru_RU.UTF-8 LC_ALL=ru_RU.UTF-8
export WINEMAC_GL_CLIP_V3=1

args=()
for arg in "$@"; do
    case "$arg" in
        -*) ;; # Ignore LaunchServices flags.
        *) args+=("$arg") ;;
    esac
done

started="$(process_identity "$$")"
[[ -n "$started" ]] || fail "Cannot identify the launch process."
printf '%s\n%s\n' "$$" "$started" > "$DATA/launch.pid" ||
    fail "Cannot record the launch process."
log "Starting SOLIDWORKS."

# Keep the LaunchServices PID so Wine's AppKit application handles activation
# and Quit. Release the setup lock before Wine starts any helpers.
exec 9>&-
if [[ ! -t 2 ]]; then
    exec 2>>"$LOG"
fi
umask "$original_umask"
exec "$WINE" "$PROGRAM" "${args[@]+"${args[@]}"}"
