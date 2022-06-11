#!/usr/bin/env ruby

require 'nokogiri'
require 'open-uri'
require 'work_queue'
require 'uri'
require 'cgi'
require 'curl'

if ARGV.count < 3 then
	puts "Usage: #{__FILE__} <url> <tag_search_pattern> <tag_link_attr> [tag_link_attr_match_pattern]"
	exit(1)
end

url = ARGV[0]
link_search = ARGV[1]
link_attr = ARGV[2]
link_pattern = /#{ARGV[3]}/

links = Nokogiri::HTML(open(url)).search(link_search).to_a.uniq { |l| l[link_attr] }
puts "Found #{links.count} links"

q_download = WorkQueue.new 5
links.each do |link|
	link_value = link[link_attr]
	next if not link_pattern.nil? and link_pattern !~ link_value
	link_escaped = URI.escape(link_value)
	base_url = URI.parse(url)
	link_url = base_url.merge(link_escaped)
	puts "Downloading #{link_url}"
	q_download.enqueue_b do
		file = link_value.split('/').last
		begin
			Curl::Easy.download(link_url.to_s, file) do |curl|
				curl.follow_location = true
				curl.useragent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.7; rv:12.0) Gecko/20100101 Firefox/12.0"
			end
			print "+"
		rescue
			raise $!
		end
	end
end

q_download.join
