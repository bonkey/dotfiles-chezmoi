#!/usr/bin/env ruby

require 'optparse'
require 'json'
require 'rainbow'
require 'English'

# Update it for your needs
devices_to_create = /^(iPad (Air.*5th|Pro.*12.*6th|Pro.*11.*4rd|mini.*6th)|iPhone (1[45]|8|SE.*3rd)|Apple Watch Series [89])/
runtimes_to_use = /^(iOS 1[56]|watchOS)/

class SimulatorPopulator
  def initialize
    @device_types = JSON.parse `xcrun simctl list -j devicetypes`
    @runtimes = JSON.parse `xcrun simctl list -j runtimes`
    @devices = JSON.parse `xcrun simctl list -j devices`
    @available_runtimes = @runtimes['runtimes'].select do |runtime|
      runtime['availability'] == '(available)' || runtime['isAvailable'] == true
    end
  end

  def remove_all
    @devices['devices'].each do |_, runtime_devices|
      runtime_devices.each do |device|
        puts 'Removing: ' +
             Rainbow("#{device['name']} (#{device['udid']})").color(:red).bright
        `xcrun simctl delete #{device['udid']}`
      end
    end
  end

  def create(device_names: :all, runtimes: :all, options: {})
    remove_all unless options[:'no-remove-existing'] == true

    @available_runtimes.each do |runtime|
      next unless runtimes == :all || runtime['name']&.match?(runtimes)

      puts Rainbow("## #{runtime['name']}").color(:blue).bright
      @device_types['devicetypes'].each do |device_type|
        next unless device_names == :all || device_type['name']&.match?(device_names)

        simulator_name = "#{device_type['name']} (#{runtime['name']})"
        args = ["'#{simulator_name}'",
                device_type['identifier'],
                runtime['identifier']].join ' '

        `xcrun simctl create #{args} 2> /dev/null`
        puts 'Created ' + Rainbow(simulator_name).color(:green).bright if $CHILD_STATUS.success?
      end
    end
  end
end

option_parser = OptionParser.new do |opts|
  opts.on '-r', '--[no-]remove-existing', 'Remove all existing simulators'
  opts.on '-v', '--[no-]verbose', 'Make the operation more talkative (not really, not implemented yet)'
  opts.on '-h', '--help', 'This help'
end

options = {}
option_parser.parse!(into: options)

if options[:help]
  puts option_parser
  exit
end

SimulatorPopulator.new.create(device_names: devices_to_create,
                              runtimes: runtimes_to_use,
                              options: options)
