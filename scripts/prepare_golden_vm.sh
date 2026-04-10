#!/bin/bash
# prepare_golden_vm.sh — Grant TCC permissions on the golden VM
#
# Run this script ONCE on the golden VM (e.g., macos-tahoe-cua_fixed)
# BEFORE using it for cloning.  This ensures every clone inherits the
# TCC permissions needed for osascript grading commands.
#
# Usage:
#   1. Start the golden VM:  lume run macos-tahoe-cua_fixed --no-display
#   2. Wait for it to boot and SSH to be available
#   3. Run this script:  ./scripts/prepare_golden_vm.sh macos-tahoe-cua_fixed
#   4. The script will trigger TCC dialogs — YOU MUST manually click
#      "Allow" on each dialog via VNC viewer (or Screen Sharing)
#   5. Stop the golden VM:  lume stop macos-tahoe-cua_fixed
#
# After completing these steps, all clones will inherit the permissions.

set -e

GOLDEN_VM="${1:-macos-tahoe-cua_fixed}"
SSH_USER="${2:-lume}"
SSH_PASS="${3:-lume}"

echo "=== Preparing golden VM: $GOLDEN_VM ==="
echo "=== IMPORTANT: Watch VNC and click 'Allow' on every TCC dialog ==="
echo ""

# Apps used in macOSWorld grading commands
APPS=(
    "Contacts"
    "Reminders"
    "Notes"
    "Music"
    "Keynote"
    "Numbers"
    "Pages"
    "Script Editor"
    "Finder"
)

# Step 1: Trigger AppleEvents TCC dialogs (automation permission)
echo "--- Step 1: Triggering AppleEvents TCC dialogs ---"
for app in "${APPS[@]}"; do
    echo "  Probing: $app (automation)"
    lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"$app\" to return 1'" \
        -u "$SSH_USER" -p "$SSH_PASS" -t 15 2>&1 || true
    echo "  -> Click 'Allow' if a TCC dialog appeared, then press Enter"
    read -r
done

# Step 2: Trigger data-access TCC dialogs
echo "--- Step 2: Triggering data-access TCC dialogs ---"

echo "  Probing: Contacts data access"
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Contacts\" to count every person'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true
echo "  -> Click 'Allow' if a TCC dialog appeared, then press Enter"
read -r

echo "  Probing: Reminders data access"
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Reminders\" to count every list'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true
echo "  -> Click 'Allow' if a TCC dialog appeared, then press Enter"
read -r

echo "  Probing: Notes data access"
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Notes\" to count every note'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true
echo "  -> Click 'Allow' if a TCC dialog appeared, then press Enter"
read -r

echo "  Probing: System Events accessibility"
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"System Events\" to get the name of every process whose frontmost is true'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true
echo "  -> Click 'Allow' if a TCC dialog appeared, then press Enter"
read -r

echo "  Probing: Finder data access"
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Finder\" to get the name of every window'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true
echo "  -> Click 'Allow' if a TCC dialog appeared, then press Enter"
read -r

# Step 3: Verify TCC permissions
echo "--- Step 3: Verifying TCC permissions ---"
lume ssh "$GOLDEN_VM" "sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db \"SELECT service, auth_value, indirect_object_identifier FROM access WHERE client LIKE '%sshd%';\"" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 10 2>&1

echo ""
echo "=== Done! ==="
echo "Now stop the golden VM:  lume stop $GOLDEN_VM"
echo "All future clones will inherit these TCC permissions."
