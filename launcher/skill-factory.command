#!/bin/bash
# Double-click launcher: starts the Skill Factory web UI. Closing this window (or the in-app
# Quit button) stops it. Lives on the Desktop; the real code is in ~/Desktop/Projects/skill-factory.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"
cd "$HOME/Desktop/Projects/skill-factory" || { echo "skill-factory repo not found"; read -r; exit 1; }
echo "Skill Factory  ->  http://127.0.0.1:4321"
echo "(close this window or click Quit in the page to stop)"
exec python3 app.py
