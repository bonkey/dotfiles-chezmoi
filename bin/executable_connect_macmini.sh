#!/usr/bin/env bash
#set -x
# In order to be able to run multiple VNC connections will differentiate based on user and IP
# To do this will add an offset to the local VNC port for jenkins and es users.
# On top of that an additional offset will be added using the last octet of the IP address
# This way a unique local VNC port will be achived for each host and user on the macminis.

connection_string=$1
user=$(echo "$connection_string" | cut -s -f1 -d'@')
case $user in
  es)
    offset=1000
  ;;
  jenkins)
    offset=1000
  ;;
*)
    offset=0
  ;;
esac

#if user is null we have only host or IP specified
if [ -n $user ] ; then
  echo "User is: $user"
  host=$(echo "$connection_string" | cut -s -f2 -d'@')
else
  host=$connection_string
fi

#check if $host it's an IP address
if [[ $host =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    echo "$host Looks like an IPv4 IP address"
    ip=$host
else
    echo "$host is a hostname"
    echo  "Resolving $host..."

    if host $host 2>&1 >/dev/null ; then
      echo "The host $host is resolvable"
      ip=$(host $host | tail -1 | awk '{print $4}')
    elif grep -q $host /etc/hosts ; then
      echo "Found $host in /etc/hosts"
      ip=$(grep $host /etc/hosts | tail -1 | awk '{print $1}')
    else
      echo "Host not found.Can't connect.Exiting"
      exit 1
    fi
fi

echo "IP address is: $ip"

#check again the IP address validaty and grab last octet
if [[ $ip =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.([0-9]{1,3}$) ]]; then
  last_octet=${BASH_REMATCH[1]}
else
  echo "$ip doesn't look like a valid IPv4 address"
  last_octet=0
fi

vnc_port=$(expr 44800 + $offset + $last_octet)
echo "VNC port for $connection_string will be $vnc_port"

ssh -fnNT -L ${vnc_port}:localhost:5900 ${connection_string}
open -W vnc://localhost:${vnc_port}
ssh -O exit ${connection_string}
