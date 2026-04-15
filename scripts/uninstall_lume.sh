#!/bin/bash
set -e

# Lume Uninstaller
# This script uninstalls Lume from your system

# Stop and remove background service
launchctl unload ~/Library/LaunchAgents/com.trycua.lume_daemon.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/com.trycua.lume_daemon.plist

# Stop and remove auto-updater
launchctl unload ~/Library/LaunchAgents/com.trycua.lume_updater.plist 2>/dev/null
rm -f ~/Library/LaunchAgents/com.trycua.lume_updater.plist
rm -f ~/.local/bin/lume-update

# Optional: Remove cached images (run before removing binary)
lume prune

# Remove Lume binary
rm -f $(which lume)

# Optional: Remove VMs and config
rm -rf ~/.lume
rm -rf ~/.config/lume
