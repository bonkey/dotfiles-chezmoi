#!/usr/bin/env ruby

require 'csv'
require 'optparse'
require 'pp'

options = ARGV.getopts('', "in-sep:", 'out-sep:')
input, output = ARGV[0], ARGV[1]
in_sep, out_sep = options['in-sep'], options['out-sep']

if out_sep.nil? || input.nil? || output.nil?
	abort("Usage: #{File.basename(__FILE__)} [--in-sep SEP] --out-sep SEP <infile> <outfile>")
end


CSV.open(output, "wb", {col_sep: out_sep}) do |csv|
	CSV.read(input, {col_sep: in_sep}).each do |record|
		csv << record
	end
end

