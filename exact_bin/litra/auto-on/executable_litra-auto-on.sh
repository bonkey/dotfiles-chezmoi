#! /bin/bash

# Details: https://gist.github.com/antonmry/8bf2d07db75df538c385bfa1cd6d5cf2

# For test it:
# tail -f /var/log/system.log
# launchctl start litra-auto-on

# Use 046D/C900 for older models
model="046D/C900"
# Change to your own path
hidapitester="/Library/LaunchDaemons/hidapitester"

log stream --predicate 'subsystem contains "com.apple.UVCExtension" and composedMessage contains "Post PowerLog"' | while read LOGLINE
do
  [[ "${LOGLINE}" == *"On;"* ]] && eval "$hidapitester --vidpid $model --open --length 20 --send-output 0x11,0xff,0x04,0x1c,0x01"
  [[ "${LOGLINE}" == *"Off;"* ]] && eval "$hidapitester --vidpid $model --open --length 20 --send-output 0x11,0xff,0x04,0x1c"
done

