#!/bin/bash
# prepare_golden_vm.sh — Grant TCC permissions on the golden VM
#
# Run this script ONCE on the golden VM before using it for cloning.
# It relies on a human operator watching the VM via VNC / Screen Sharing
# and clicking Allow when TCC dialogs appear.
#
# Usage:
#   1. Start the golden VM:  lume run macos-tahoe-cua_fixed --no-display
#   2. Wait for it to boot and SSH to be available
#   3. Run this script:  ./scripts/prepare_golden_vm.sh macos-tahoe-cua_fixed
#   4. Watch VNC and click "Allow" on TCC dialogs when prompted
#   5. Stop the golden VM:  lume stop macos-tahoe-cua_fixed
#
# The goal is to bake both shallow Automation permission and deeper
# document / window AppleEvent permission into the golden VM.

set -e

GOLDEN_VM="${1:-macos-tahoe-cua_fixed}"
SSH_USER="${2:-lume}"
SSH_PASS="${3:-lume}"

echo "=== Preparing golden VM: $GOLDEN_VM ==="
echo "=== IMPORTANT: Watch VNC and click 'Allow' on every TCC dialog ==="
echo ""

run_probe() {
    local label="$1"
    local command="$2"
    local timeout="${3:-30}"

    echo "  Probing: $label"
    lume ssh "$GOLDEN_VM" "$command" \
        -u "$SSH_USER" -p "$SSH_PASS" -t "$timeout" 2>&1 || true
    echo "  -> Click 'Allow' if a TCC dialog appeared, then press Enter"
    read -r
}

run_verify() {
    local label="$1"
    local command="$2"
    local timeout="${3:-30}"

    echo "  Verifying: $label"
    lume ssh "$GOLDEN_VM" "$command" \
        -u "$SSH_USER" -p "$SSH_PASS" -t "$timeout" 2>&1 || true
}

# Apps used in macOSWorld grading commands.
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
    "Automator"
    "Xcode"
    "Calendar"
    "QuickTime Player"
    "TextEdit"
)

# Step 0: Reduce common first-launch blockers before probing.
echo "--- Step 0: Clearing first-launch blockers ---"
lume ssh "$GOLDEN_VM" "killall akd 2>/dev/null || true" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 10 2>&1 || true
echo ""

# Step 1: Trigger AppleEvents TCC dialogs (basic Automation permission).
echo "--- Step 1: Triggering AppleEvents TCC dialogs ---"
for app in "${APPS[@]}"; do
    run_probe "$app (automation)" "osascript -e 'tell application \"$app\" to return 1'" 15
done

# Step 2: Trigger data-access / accessibility TCC dialogs.
echo "--- Step 2: Triggering data-access TCC dialogs ---"
run_probe "Contacts data access" "osascript -e 'tell application \"Contacts\" to count every person'" 30
run_probe "Reminders data access" "osascript -e 'tell application \"Reminders\" to count every list'" 30
run_probe "Notes data access" "osascript -e 'tell application \"Notes\" to count every note'" 30
run_probe "System Events accessibility" "osascript -e 'tell application \"System Events\" to get the name of every process whose frontmost is true'" 30
run_probe "Calendar data access" "osascript -e 'tell application \"Calendar\" to get the name of every calendar'" 30
run_probe "Finder data access" "osascript -e 'tell application \"Finder\" to get the name of every window'" 30

# Step 3: Warm up apps so macOS caches AppleEvent connections.
echo "--- Step 3: Deep Apple Events warmup ---"
for app in "${APPS[@]}"; do
    echo "  Warming up: $app"
    lume ssh "$GOLDEN_VM" "open -a \"$app\"" \
        -u "$SSH_USER" -p "$SSH_PASS" -t 15 2>&1 || true
    sleep 3
done

echo "  Waiting 10s for apps to initialise..."
sleep 10

echo "  -> If Numbers / Pages / Keynote show a template chooser, dismiss it via VNC now."
echo "  -> If Xcode shows a welcome screen, license prompt, or setup / install UI, dismiss or complete it now."
echo "  -> Press Enter when the launched apps are in a usable state."
read -r

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

echo "  Exercising Calendar scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Calendar\" to get the name of every calendar'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 60 2>&1 || true

echo "  Exercising Automator scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"Automator\" to return 1'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true

echo "  Exercising QuickTime Player scripting..."
lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"QuickTime Player\" to return 1'" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 30 2>&1 || true

# Step 3b: Trigger deeper document / window AppleEvents that often cause
# a second TCC grant or first-use timeout in clones.
echo "--- Step 3b: Triggering deep document/workspace AppleEvents ---"
run_probe "Numbers document access" "osascript -e 'tell application \"Numbers\" to count every document'" 60
run_probe "Pages document access" "osascript -e 'tell application \"Pages\" to count every document'" 60
run_probe "Keynote document access" "osascript -e 'tell application \"Keynote\" to count every document'" 60
run_probe "TextEdit document access" "osascript -e 'tell application \"TextEdit\" to count every document'" 60
run_probe "Xcode window access" "osascript -e 'tell application \"Xcode\" to count every window'" 60
run_probe "Xcode close windows AppleEvent" "osascript -e 'tell application \"Xcode\" to close windows'" 60

# Close all the apps we opened (clean state for golden VM).
echo "  Closing warmed-up apps..."
for app in "${APPS[@]}"; do
    lume ssh "$GOLDEN_VM" "osascript -e 'tell application \"$app\" to quit'" \
        -u "$SSH_USER" -p "$SSH_PASS" -t 10 2>&1 || true
done
sleep 5
echo "  Apple Events warmup complete."
echo ""

# Step 4: Verify both TCC DB entries and deep probes.
echo "--- Step 4: Verifying TCC permissions and deep probes ---"
lume ssh "$GOLDEN_VM" "sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db \"SELECT service, auth_value, indirect_object_identifier FROM access WHERE client LIKE '%sshd%';\"" \
    -u "$SSH_USER" -p "$SSH_PASS" -t 10 2>&1

run_verify "Numbers document access" "osascript -e 'tell application \"Numbers\" to count every document'" 30
run_verify "Pages document access" "osascript -e 'tell application \"Pages\" to count every document'" 30
run_verify "Keynote document access" "osascript -e 'tell application \"Keynote\" to count every document'" 30
run_verify "TextEdit document access" "osascript -e 'tell application \"TextEdit\" to count every document'" 30
run_verify "Xcode window access" "osascript -e 'tell application \"Xcode\" to count every window'" 30
run_verify "Xcode close windows AppleEvent" "osascript -e 'tell application \"Xcode\" to close windows'" 30

echo ""
echo "=== Done! ==="
echo "Now stop the golden VM:  lume stop $GOLDEN_VM"
echo "All future clones will inherit these TCC permissions."
