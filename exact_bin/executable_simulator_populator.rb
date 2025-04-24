#!/usr/bin/env ruby

require 'optparse'
require 'json'
require 'rainbow'
require 'English'

# xcrun simctl list -j devicetypes | jq '.devicetypes[].name'|sort
devices_to_create = [
  "iPad Pro 11-inch (M4)",
  "iPad Pro 13-inch (M4)",
  "iPhone 15 Pro Max",
  "iPhone 15 Pro",
  "iPhone 16 Pro Max",
  "iPhone 16 Pro",
  "iPhone 16",
  "iPhone SE (3rd generation)",
]

# xcrun simctl list -j runtimes | jq '.runtimes[].name'
runtimes_to_use = [
  "iOS 17.5",
  "iOS 18.2",
  "iOS 18.3",
  "iOS 18.4",
]

default_sim_device = 'iPhone 15 Pro'
default_sim_runtime = 'iOS 17.5'

class SimulatorPopulator
  def initialize(
    devices_to_create:, runtimes_to_use:,
    default_device:, default_runtime:)
    @devices_to_create = devices_to_create
    @runtimes_to_use = runtimes_to_use
    @default_device = default_device
    @default_runtime = default_runtime

    @device_types = JSON.parse `xcrun simctl list -j devicetypes`
    @runtimes = JSON.parse `xcrun simctl list -j runtimes`
    @devices = JSON.parse `xcrun simctl list -j devices`
    @available_runtimes = @runtimes['runtimes'].select do |runtime|
      runtime['availability'] == '(available)' || runtime['isAvailable'] == true
    end
  end

  def remove_all
    puts "Removing all existing simulators..."
    @devices['devices'].each do |_, runtime_devices|
      runtime_devices.each do |device|
        puts 'Removing: ' +
             Rainbow("#{device['name']} (#{device['udid']})").color(:red).bright
        `xcrun simctl delete #{device['udid']}`
      end
    end
  end

  def create
    puts "Creating all simulator variants..."

    @available_runtimes.each do |runtime|
      next unless @runtimes_to_use.include?(runtime['name'])

      puts Rainbow("## #{runtime['name']}").color(:blue).bright
      @device_types['devicetypes'].each do |device_type|
        next unless @devices_to_create.include?(device_type['name'])

        create_device(device_type: device_type['identifier'],
                      runtime: runtime['name'],
                      name: "#{device_type['name']} (#{runtime['name']})")
      end
    end
  end

  def create_default_device
    puts "Creating default device #{Rainbow(@default_device).color(:green).bright} on #{Rainbow(@default_runtime).color(:green).bright}"
    create_device(device_type: @default_device, runtime: @default_runtime)
  end

  private
  def find_runtime(name:)
    runtime = @available_runtimes
      .select { |runtime| runtime['name'] == name }
      .first

    return if runtime.nil?

    runtime['identifier']
  end


  def create_device(device_type:, runtime:, name: nil)
    name ||= device_type
    runtime_id = find_runtime(name: runtime)
    if runtime_id.nil?
      puts "Runtime #{Rainbow(runtime).color(:red).bright} not found"
      return
    end
    args = ["'#{name}'", "'#{device_type}'", "'#{runtime_id}'"].join ' '

    `xcrun simctl create #{args} 2> /dev/null`
    puts "Created #{Rainbow(name).color(:green).bright}" if $CHILD_STATUS.success?
  end
end

options = {
  'remove-existing' => true,
  'create-all-variants' => true,
  'create-default-variant' => true,
  'verbose' => true
}

option_parser = OptionParser.new do |opts|
  opts.on '-r', '--[no-]remove-existing', 'Remove all existing simulators' do |v|
    options['remove-existing'] = v
  end
  opts.on '-c', '--[no-]create-all-variants', 'Create new simulators' do |v|
    options['create-all-variants'] = v
  end
  opts.on '-d', '--[no-]create-default-variant', "Create a default simulator (#{default_sim_device} on #{default_sim_runtime})" do |v|
    options['create-default-variant'] = v
  end
  opts.on '-v', '--[no-]verbose', 'Make the operation more talkative (not really, not implemented yet)' do |v|
    options['verbose'] = v
  end
  opts.on '-h', '--help', 'This help'
end

option_parser.parse!

if options[:help]
  puts option_parser
  exit
end

populator = SimulatorPopulator.new(
  devices_to_create: devices_to_create,
  runtimes_to_use: runtimes_to_use,
  default_device: default_sim_device,
  default_runtime: default_sim_runtime)

populator.remove_all if options['remove-existing']
populator.create if options['create-all-variants']
populator.create_default_device if options['create-default-variant']
