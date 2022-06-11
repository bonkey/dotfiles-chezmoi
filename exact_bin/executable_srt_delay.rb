#!/usr/bin/ruby
# author : sathyz@gmail.com
#

class String

	def to_msec( )
		# convert string in time format to milli sec format 
		# "12:23:34,567" => "12*60*60*1000 + 23*60*1000 + 34 *1000 + 567"
		time_list = self.split(":")
		sec, msec = time_list.pop().split(",") 
		time_list.push(sec)
		msecs = msec.to_i
		time_list.reverse!
		time_list.each_with_index { |x,i| msecs += x.to_i * 60**i * 1000 }
		msecs.to_s
	end
end

class Fixnum

	def to_time()
		# convert millisec to standard time format
		# 3600 * 1000 = ,000
		time = self
		msec = "%.3d"%(time % 1000)
		time /= 1000
		time_list = []
		3.times { time_list.unshift( "%.2d"% (time%60) ) ; time /= 60 }
		[ time_list.join(':'),msec ].join(',')
	end

end

def srt_delay(in_file, delay)
	puts "Using Subtitle File: #{in_file}, delay : #{delay}\n"

	if !FileTest::exists?(in_file)
		print "#{in_file} doesn't exist.. \n"
		return
	end

	seq = 0
	dir = ( dir = delay.match("^[+-]") ) ? dir[0] : "+" 
	delay = delay.delete(dir)

	in_sequence = false
	File.open("delayed-#{in_file}", "w") do |out_file|
		File.readlines(in_file).each do |in_line|
			in_line.chop!

			next if in_line =~ /^[0-9]+$/
			if in_line =~ /^$/
				out_file.puts if in_sequence
				in_sequence = false
			end

			if in_line =~ /^[0-9:,]+ --> [0-9:,]+$/
				in_sequence = true
				p "delaying line: #{in_line}, #{delay}" if $DEBUG
				original_instances = in_line.split("-->").each{|instance| instance.chop!}

				delayed_line = "%s --> %s" % original_instances.collect { |x|
					delay_msec = eval( x.to_msec + dir + delay.to_msec )
					in_sequence = false if delay_msec < 0
					delay_msec.to_time
				}
				next unless in_sequence

				puts "DELAYED_LINE: '#{delayed_line}'" if $DEBUG
				seq += 1
				out_file.puts seq
				out_file.puts delayed_line
				next
			end
			
			if in_sequence
				out_file.puts in_line
			end

		end
	end
end

if __FILE__ == $0
	if ARGV.size != 2
		print "Usage #{$0} SRT_FILE DELAY\n DELAY specified as 59 => 59 secs, 23:59 => 23 mins 59 secs\n"
		exit
	end
	srt_delay(ARGV[0],ARGV[1])
end
