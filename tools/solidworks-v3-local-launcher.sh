#!/bin/bash
# Installed as Contents/MacOS/SOLIDWORKS inside the local V3 bundle.
set -eu

bundle=$(cd "$(/usr/bin/dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
runtime="$bundle/Contents/Resources/runtime/CrossOver"
wine="$runtime/lib/wine/x86_64-unix/wine"
state="$HOME/Library/Application Support/local.solidworks2025.v3resize"
seed="$bundle/Contents/Resources/prefix-seed"
graphics_lab="$bundle/Contents/Resources/graphics-lab"
graphics_metal="$bundle/Contents/Resources/graphics-metal"
metal_available=false
if [[ -f "$graphics_lab" || -f "$graphics_metal" ]]; then metal_available=true; fi
locale=ru_RU.UTF-8
if [[ -f "$graphics_lab" ]]; then
    state="$HOME/Library/Application Support/local.solidworks2025.v3vertexspanpreview"
elif [[ -f "$graphics_metal" ]]; then
    state="$state/metal"
fi
program_config="$bundle/Contents/Resources/program-path.txt"
if [[ -f "$program_config" ]]; then
    state="$HOME/Library/Application Support/org.swv3.desktop"
    if [[ -f "$graphics_metal" ]]; then state="$state/metal"; fi
    locale=en_US.UTF-8
    runtime="$bundle/Contents/Resources/runtime"
    wine="$runtime/lib/wine/x86_64-unix/wine"
    if [[ ! -x "$wine" ]]; then wine="$runtime/bin/wine"; fi
fi

saved_umask=$(umask)
umask 077
/bin/mkdir -p "$state"
exec 9>>"$state/launch.lock"
/usr/bin/lockf -s -t 0 9 || exit 75

process_start() {
    LC_ALL=C /bin/ps -p "$1" -o stat= -o lstart= |
        /usr/bin/awk '$1 !~ /^Z/ && NF == 6 { $1 = ""; sub(/^ +/, ""); print }'
}

if [[ -f "$state/launch.pid" ]]; then
    {
        read -r previous_pid || previous_pid=
        read -r previous_start || previous_start=
    } < "$state/launch.pid"
    if [[ "$previous_pid" =~ ^[0-9]+$ && -n "$previous_start" &&
          "$(process_start "$previous_pid")" == "$previous_start" ]]; then
        exit 75
    fi
fi
if /bin/ps -axo comm= | /usr/bin/grep -Eiq '(^|[\\/])SLDWORKS[.]exe$'; then exit 75; fi

fail() {
    printf '%s\n' "$1" >>"$state/launch.log"
    exit 1
}

[[ -x "$wine" ]] || fail "The bundled Wine loader is missing."
prefix="$bundle/Contents/Resources/prefix"
if [[ ! -d "$prefix" ]]; then
    prefix="$state/prefix"
    if [[ ! -e "$prefix" && ! -L "$prefix" ]]; then
        [[ -f "$seed/system.reg" ]] || fail "The bundled Wine prefix is incomplete."
        stage=$(/usr/bin/mktemp -d "$state/prefix-stage.XXXXXXXX")
        trap '/bin/rm -rf -- "$stage"' EXIT
        if /bin/cp -cR "$seed" "$stage/clone" 2>>"$state/launch.log"; then
            working="$stage/clone"
        else
            working="$stage/copy"
            /bin/cp -R "$seed" "$working" 2>>"$state/launch.log" ||
                fail "Unable to copy the bundled Wine prefix."
        fi
        if [[ ! -e "$working/dosdevices/z:" && ! -L "$working/dosdevices/z:" ]]; then
            /bin/ln -s / "$working/dosdevices/z:"
        fi
        if [[ -f "$state/workspace-path" ]]; then
            IFS= read -r workspace <"$state/workspace-path" || workspace=
            if [[ -n "$workspace" && -d "$workspace" &&
                  ! -e "$working/dosdevices/w:" && ! -L "$working/dosdevices/w:" ]]; then
                /bin/ln -s "$workspace" "$working/dosdevices/w:"
            fi
        fi
        /bin/mv "$working" "$prefix"
        /bin/rm -rf -- "$stage"
        trap - EXIT
    fi
fi

[[ ! -L "$prefix" && -w "$prefix" && -f "$prefix/system.reg" ]] ||
    fail "The working Wine prefix is unavailable."
if [[ -f "$program_config" ]]; then
    IFS= read -r relative_program <"$program_config" || fail "Missing SOLIDWORKS executable path."
    case "$relative_program" in
        /*|../*|*/../*|*/..) fail "Invalid SOLIDWORKS installation path." ;;
    esac
    program="$prefix/drive_c/$relative_program"
    [[ -f "$program" ]] || fail "SLDWORKS.exe is missing from the working Wine prefix."
elif [[ -f "$prefix/drive_c/Program Files/SOLIDWORKS/SLDWORKS.exe" ]]; then
    program='C:\Program Files\SOLIDWORKS\SLDWORKS.exe'
elif [[ -f "$prefix/drive_c/Program Files/SOLIDWORKS Corp/SOLIDWORKS/SLDWORKS.exe" ]]; then
    program='C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe'
else
    fail "SLDWORKS.exe is missing from the working Wine prefix."
fi

args=()
backend=metal
for arg in "$@"; do
    case "$arg" in
        --backend=metal|--backend=opengl)
            if "$metal_available"; then backend=${arg#--backend=}; fi
            ;;
        -*) ;; # Ignore LaunchServices flags.
        *) args+=("$arg") ;;
    esac
done

overrides='concrt140=n,b;winedbg.exe=d'
if "$metal_available"; then
    if [[ "$backend" == metal ]]; then
        overrides="opengl32=n,b;winemetalgl=b;$overrides"
        export SWV3_WMGL_WINEMAC_SURFACE=1 SWV3_WMGL_ZORDER_CLIP=0 WINEMETALGL_X87=0
        if [[ -f "$graphics_metal" ]]; then
            export SWV3_WMGL_BATCH_VERTEX3FV=0 SWV3_WMGL_COMPACT_IMMEDIATE=0
            export SWV3_WMGL_CONTEXT_LOCAL_VERTICES=0 SWV3_WMGL_VERTEX_SPANS=0
        else
            # Laboratory runs opt in to each optimization explicitly.
            export SWV3_WMGL_BATCH_VERTEX3FV="${SWV3_WMGL_BATCH_VERTEX3FV:-0}"
            export SWV3_WMGL_COMPACT_IMMEDIATE="${SWV3_WMGL_COMPACT_IMMEDIATE:-0}"
            export SWV3_WMGL_CONTEXT_LOCAL_VERTICES="${SWV3_WMGL_CONTEXT_LOCAL_VERTICES:-0}"
            export SWV3_WMGL_VERTEX_SPANS="${SWV3_WMGL_VERTEX_SPANS:-0}"
        fi
    else
        overrides="opengl32=b;winemetalgl=d;$overrides"
    fi
fi

started=$(process_start "$$")
[[ -n "$started" ]] || exit 1
printf '%s\n%s\n' "$$" "$started" > "$state/launch.pid"
exec >"$state/launch.log" 2>&1
exec 9>&-
umask "$saved_umask"

cd "$prefix/drive_c"
# Retain LaunchServices' PID for Wine's GUI activation and quit handling.
if [[ "$wine" = "$runtime/lib/wine/x86_64-unix/wine" ]]; then export CX_ROOT="$runtime"; fi
export PATH="$runtime/bin:${PATH:-/usr/bin:/bin}"
exec /usr/bin/env WINEPREFIX="$prefix" \
    WINEDLLOVERRIDES="$overrides" WINEDEBUG='-all,err+all' \
    WINEMAC_GL_CLIP_V3=1 WINEMAC_GL_CLIP_WINDOW_RGN=0 WINEMAC_DISABLE_DOCK_SNAPSHOT=1 \
    WIN32U_SW_PM_TOPMOST=1 WIN32U_SW_TASKPANE_LAYOUT=1 WINEMAC_SW_BORDERLESS_RESIZE=1 \
    WINEMAC_SW_FILES_PID="$$" \
    LANG="$locale" LC_ALL="$locale" "$wine" "$program" "${args[@]+"${args[@]}"}"
