#!/bin/bash
# Run trad-split on files selected in Finder. Used by the "Split Trad Session"
# Quick Action (see README); also works from Keyboard Maestro or Alfred.
#
#   memo files or folders  -> detect and split
#   a .RPP project         -> re-cut from the regions saved in Reaper
#
# Outputs follow ~/.config/trad-split/config.toml. Progress goes to
# ~/Library/Logs/trad-split.log; a notification says when each one is done.

# Automator starts with a bare PATH, so ffmpeg from Homebrew would not be found.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

here="$(cd "$(dirname "$0")" && pwd -P)"
trad_split="${TRAD_SPLIT:-$here/../.venv/bin/trad-split}"
log="${TRAD_SPLIT_LOG:-$HOME/Library/Logs/trad-split.log}"
mkdir -p "$(dirname "$log")"

notify() {
    osascript -e 'on run argv' \
              -e 'display notification (item 2 of argv) with title "trad-split" subtitle (item 1 of argv)' \
              -e 'end run' "$1" "$2" 2>/dev/null
}

if [ ! -x "$trad_split" ]; then
    notify "Not installed" "Cannot find $trad_split"
    exit 1
fi

status=0
for item in "$@"; do
    name="$(basename "$item")"
    case "$item" in
        *.RPP|*.rpp) args=(--from-reaper "$item"); what="Re-cutting" ;;
        *)           args=("$item");                what="Splitting" ;;
    esac
    notify "$name" "$what..."
    run_log="$(mktemp)"
    { echo; echo "=== $(date '+%Y-%m-%d %H:%M:%S')  $what $item"; } >> "$log"
    if "$trad_split" "${args[@]}" > "$run_log" 2>&1; then
        tr '\r' '\n' < "$run_log" >> "$log"
        summary="$(grep -m1 -E '^  [0-9]+ sets,' "$run_log" | sed 's/^ *//')"
        notify "$name" "Done: ${summary:-finished}"
        # Open the session folder(s) the run reported.
        grep -E '^  -> ' "$run_log" | sed 's/^  -> //' | while IFS= read -r dir; do
            open "$dir" 2>/dev/null
        done
    else
        tr '\r' '\n' < "$run_log" >> "$log"
        notify "$name" "Failed. Opening the log."
        open "$log" 2>/dev/null
        status=1
    fi
    rm -f "$run_log"
done
exit $status
