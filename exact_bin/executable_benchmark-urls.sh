#!/bin/zsh

if [ $# -lt 2 ]; then 
  echo "$0 <times> <url1> [url2] ... [urln]"
  exit
fi

times=$1
shift

echo "Repeats: $times"
echo "Urls:"
for i in "$@" ; do
  echo $i
done

for i in {1..$times} ; do
  echo "Test $i/$times"
  for url in "$@"; do
    echo "GET $url"
    curl -w "%{url_effective} %{content_type} %{size_download} bytes #%{http_code}\ntime (sec.) total: %{time_total} dns: %{time_namelookup} connect: %{time_connect} start: %{time_starttransfer}\nspeed: %{speed_download} b/s\n" -L -# -o /dev/null -q $url
  done
done
