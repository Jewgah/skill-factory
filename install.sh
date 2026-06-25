#!/usr/bin/env bash
# Approve a proposal: copy a drafted SKILL.md into ~/.claude/skills/<name>/.
# The ONLY script that writes into ~/.claude/skills. Never overwrites without a shown diff.
#   usage: bash install.sh <dir-with-SKILL.md | path/to/SKILL.md> [--force]
# --force skips the interactive prompt (used by the web app, which shows the diff in-UI first).
set -euo pipefail

ARG="${1:-}"
FORCE="${2:-}"
[ -n "$ARG" ] || { echo "usage: bash install.sh <proposal-dir|SKILL.md> [--force]"; exit 1; }
if [ -d "$ARG" ]; then SKILL="$ARG/SKILL.md"; else SKILL="$ARG"; fi
[ -f "$SKILL" ] || { echo "no SKILL.md at $SKILL"; exit 1; }

NAME="$(awk -F': *' '/^name:/{print $2; exit}' "$SKILL" | tr -d '\r' | sed -e 's/^["'\'']//' -e 's/["'\'']$//')"
[ -n "$NAME" ] || { echo "could not read 'name:' from $SKILL"; exit 1; }

DEST="$HOME/.claude/skills/$NAME"
TARGET="$DEST/SKILL.md"

if [ -f "$TARGET" ]; then
  echo "Skill '$NAME' already exists. Diff (current vs proposed):"
  echo "----------------------------------------------------------------"
  diff -u "$TARGET" "$SKILL" || true
  echo "----------------------------------------------------------------"
  if [ "$FORCE" != "--force" ]; then
    printf "Overwrite %s ? type 'yes' to confirm: " "$TARGET"
    read -r ANS
    [ "$ANS" = "yes" ] || { echo "Aborted. No changes made."; exit 1; }
  fi
else
  echo "New skill '$NAME' -> $TARGET"
  if [ "$FORCE" != "--force" ]; then
    printf "Create it? type 'yes' to confirm: "
    read -r ANS
    [ "$ANS" = "yes" ] || { echo "Aborted. No changes made."; exit 1; }
  fi
fi

mkdir -p "$DEST"
cp "$SKILL" "$TARGET"
echo "Installed: $TARGET"
