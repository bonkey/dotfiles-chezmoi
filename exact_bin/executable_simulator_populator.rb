#!/usr/bin/env ruby

require 'optparse'
require 'json'
require 'rainbow'
require 'English'

# xcrun simctl list -j devicetypes | jq '.devicetypes[].name'|sort
devices_to_create = %w[
  "iPad Pro 11-inch (M4)"
  "iPad Pro 13-inch (M4)"
  "iPhone 15 Pro Max"
  "iPhone 15 Pro"
  "iPhone 16 Pro Max"
  "iPhone 16 Pro"
  "iPhone 16"
  "iPhone SE (3rd generation)"
]

# xcrun simctl list -j runtimes | jq '.runtimes[].name'
runtimes_to_use = %w[
  "iOS 17.5"
  "iOS 18.1"
]

default_sim_device = 'iPhone 15 Pro'
default_sim_runtime = 'iOS 17.5'

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
      next unless runtimes == :all || runtimes.include?(runtime['name'])

      puts Rainbow("## #{runtime['name']}").color(:blue).bright
      @device_types['devicetypes'].each do |device_type|
        next unless device_names == :all || device_names.include?(device_type['name'])

        create_device(device_type: device_type['identifier'],
                      runtime: runtime['name'],
                      name: "#{device_type['name']} (#{runtime['name']})")
      end
    end
  end

  def find_runtime(name:)
    @available_runtimes
      .select { |runtime| runtime['name'] == name }
      .first['identifier']
  end

  def create_device(device_type:, runtime:, name: nil)
    name ||= device_type
    runtime_id = find_runtime(name: runtime)
    args = ["'#{name}'", "'#{device_type}'", "'#{runtime_id}'"].join ' '

    `xcrun simctl create #{args} 2> /dev/null`
    puts "Created #{Rainbow(name).color(:green).bright}" if $CHILD_STATUS.success?
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

populator = SimulatorPopulator.new

populator.create(device_names: devices_to_create,
                 runtimes: runtimes_to_use,
                 options:)

populator.create_device(device_type: default_sim_device,
                        runtime: default_sim_runtime)
