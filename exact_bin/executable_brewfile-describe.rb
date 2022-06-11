#!/usr/bin/env ruby

require 'json'

ARGF.each do |line|
  if line =~ /^brew ["']([^"']+)["']$/
    name = Regexp.last_match(1)
    warn "Getting brew #{name}"
    output = `brew info --json=v2 "#{name}"`
    json = JSON.parse(output)
    desc = json['formulae'][0]['desc']
    puts "#{line.strip} # #{desc}"
  elsif line =~ /^cask ["']([^"']+)["']$/
    name = Regexp.last_match(1)
    warn "Getting cask #{name}"
    output = `brew info --cask --json=v2 "#{name}"`
    json = JSON.parse(output)
    desc = json['casks'][0]['desc']
    puts "#{line.strip} # #{desc}"
  else
    puts line
  end
end
