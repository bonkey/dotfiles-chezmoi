#!/usr/bin/env ruby

require 'json'
require 'tempfile'

file_path = ARGV[0]

def process_line(line)
  match = line.match(/^(brew|cask) ["']([^"']+)["']$/)
  return line unless match

  type, name = match.captures
  warn "Getting #{type} #{name}"
  info_type = type == 'brew' ? '' : '--cask'
  json_key = type == 'brew' ? 'formulae' : 'casks'

  output = `brew info #{info_type} --json=v2 "#{name}"`
  json = JSON.parse(output)
  desc = json[json_key][0]['desc']

  "#{line.strip} # #{desc}"
end

if file_path.nil?
  puts "Usage: #{__FILE__} <Brewfile>"
  exit(1)
end

unless File.exist?(file_path)
  puts "File #{file_path} does not exist."
  exit(2)
end

original_lines = File.readlines(file_path)
filename = File.basename(file_path)
temp_file = Tempfile.new(filename)

begin
  original_lines.each do |line|
    temp_file.puts(process_line(line))
  end

  temp_file.close

  FileUtils.mv(temp_file.path, file_path)
ensure
  temp_file.close
  temp_file.unlink
end
