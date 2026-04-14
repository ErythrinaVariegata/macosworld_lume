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

# Step 3: Deep Apple Events warmup
# Launch each app and exercise its scripting interface so macOS caches
# the Apple Events connection.  This prevents the first osascript call
# in a cloned VM from timing out during grading.
echo "--- Step 3: Deep Apple Events warmup ---"
for app in "${APPS[@]}"; do
    echo "  Warming up: $app"
    # Launch the app
    lume ssh "$GOLDEN_VM" "open -a \"$app\"" \
        -u "$SSH_USER" -p "$SSH_PASS" -t 15 2>&1 || true
    sleep 3
done

echo "  Waiting 10s for apps to initialise..."
sleep 10

# Exercise each app's scripting interface with real data queries
echo "  Exercising Reminders scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Reminders\" to get the name of every reminder whose completed is false'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 60 2>&1 || true

echo "  Exercising Contacts scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Contacts\" to get the name of every person'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 60 2>&1 || true

echo "  Exercising Notes scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Notes\" to get the name of every note'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 60 2>&1 || true

echo "  Exercising Finder scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Finder\" to get the name of every window'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true

echo "  Exercising System Events scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"System Events\" to get the name of every process whose frontmost is true'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true

echo "  Exercising Music scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Music\" to return 1'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true

echo "  Exercising Keynote scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Keynote\" to return 1'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true

echo "  Exercising Numbers scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Numbers\" to return 1'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true

echo "  Exercising Pages scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Pages\" to return 1'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true

# Close all the apps we opened (clean state for golden VM)
echo "  Closing warmed-up apps..."
for app in "${APPS[@]}"; do
    lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"$app\" to quit'" \
        -u "$SSH_USER" -p "$SSH_PASS" -t 10 2>&1 || true
done
sleep 5
echo "  Apple Events warmup complete."
echo ""

# Step 4: Verify TCC permissions
echo "--- Step 4: Verifying TCC permissions ---"
lume ssh "$GOLDEN_VM" "sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db \"SELECT service, auth_value, indirect_object_identifier FROM access WHERE client LIKE '%sshd%';\"" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 10 2>&1

echo ""
echo "=== Done! ==="
echo "Now stop the golden VM:  lume stop $GOLDEN_VM"
echo "All future clones will inherit these TCC permissions."
