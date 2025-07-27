#!/usr/bin/env ruby

require 'mechanize'
require 'parallel'

if ARGV.count != 1
  puts "USAGE: #{__FILE__} <count>"
  exit(1)
end

count = ARGV[1].to_i

mechanize = Mechanize.new
mechanize.post('https://www.nsscreencast.com/user_sessions',
               'email' => 'office@netguru.pl', 'password' => 'nsbiedronka')
mechanize.pluggable_parser.default = Mechanize::Download

Parallel.each((1..count)) do |idx|
  begin
    video_url = "http://www.nsscreencast.com/episodes/#{idx}.mp4"
    puts "Downloading #{video_url}"

    video = mechanize.get(video_url)

    raw_filename = File.basename(video.uri.path)
    episode_number = raw_filename.split('-')[0].gsub('ns', '').gsub('nss', '').to_i
    episode_name = raw_filename.split('-').drop(1).map(&:capitalize).join(' ')

    video.save("videos/##{episode_number} - #{episode_name}")
    puts "Saved #{video_url}"
  rescue
    puts "Couldn't save #{video_url}"
  end
end
