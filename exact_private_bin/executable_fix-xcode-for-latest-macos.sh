#!/usr/bin/env zsh

set -euo pipefail

help() {
    echo "Usage: $0 <OLD_XCODE_PATH> <NEW_XCODE_PATH>"
    echo "  e.g. ./fix-xcode-for-latest-macos.sh /Applications/Xcode-14.3.1.app /Applications/Xcode-15.0.0.app"
}

if [[ $# -ne 2 || ! -d "$1" || ! -d "$2" ]]; then
    help
    exit 0
fi

OLD_XCODE=$1
NEW_XCODE=$2

# Get New Xcode build number
OLD_XCODE_BUILD=$(/usr/libexec/PlistBuddy -c "Print CFBundleVersion" ${OLD_XCODE}/Contents/Info.plist)
NEW_XCODE_BUILD=$(/usr/libexec/PlistBuddy -c "Print CFBundleVersion" ${NEW_XCODE}/Contents/Info.plist)

echo The Old Xcode build version is $OLD_XCODE_BUILD
echo The New Xcode build version is $NEW_XCODE_BUILD

# Change Old Xcode build version to New Xcode
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${NEW_XCODE_BUILD}" ${OLD_XCODE}/Contents/Info.plist

# Open Old Xcode (system will check build version and cache it)
open $OLD_XCODE

# Revert Old's Xcode's build version
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${OLD_XCODE_BUILD}" ${OLD_XCODE}/Contents/Info.plist
