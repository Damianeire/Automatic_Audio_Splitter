#!/bin/bash
# Build "Trad Split.app", a small launcher for the trad-split window.
#
#   scripts/make-app.sh                  -> ~/Applications/Trad Split.app
#   scripts/make-app.sh /Applications    -> /Applications/Trad Split.app
#
# The app runs this checkout's .venv, so install first with:
#   .venv/bin/pip install -e '.[gui]'
# Files dropped on the app's icon are added to the window, which opens if needed.
# Running it again rebuilds the app, for example after moving this folder.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
python="$repo/.venv/bin/python"
dest="${1:-$HOME/Applications}"
app="$dest/Trad Split.app"
log="$HOME/Library/Logs/trad-split-gui.log"

if ! "$python" -c "import PySide6" 2>/dev/null; then
    echo "PySide6 is not installed in $repo/.venv. Run:" >&2
    echo "  $repo/.venv/bin/pip install -e '$repo[gui]'" >&2
    exit 1
fi

# AppleScript string literal: escape backslashes and double quotes.
as_string() { printf '"%s"' "$(printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')"; }

script="$(mktemp -t trad-split-app)"
trap 'rm -f "$script"' EXIT
cat > "$script" <<EOF
on run
    launchWindow({})
end run

on open theItems
    launchWindow(theItems)
end open

on launchWindow(theItems)
    set cmd to "export PATH=/opt/homebrew/bin:/usr/local/bin:\$PATH; cd " & quoted form of $(as_string "$repo") & "; " & quoted form of $(as_string "$python") & " -m trad_split.gui"
    repeat with f in theItems
        set cmd to cmd & " " & quoted form of POSIX path of f
    end repeat
    do shell script cmd & " >> " & quoted form of $(as_string "$log") & " 2>&1 &"
end launchWindow
EOF

mkdir -p "$dest" "$(dirname "$log")"
rm -rf "$app"
osacompile -o "$app" "$script"
echo "Built $app"
echo "Drag it to the Dock; drop memos, .RPP projects or session notes on it."
