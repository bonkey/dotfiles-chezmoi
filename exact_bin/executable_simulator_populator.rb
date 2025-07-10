#!/usr/bin/env ruby

require 'optparse'
require 'json'
require 'rainbow'
require 'English'

# Core runtime (18.5) - creates all devices from devices_for_core_runtime
core_runtime = 'iOS 18.5'
devices_for_core_runtime = [
  'iPad Pro 11-inch (M4)',
  'iPad Pro 13-inch (M4)',
  'iPhone 16 Pro Max',
  'iPhone 16 Pro',
  'iPhone 16',
  'iPhone SE (3rd generation)'
]

# Supplementary runtimes - creates only selected devices (iPhone 16 Pro and iPad 11 inch)
supplementary_runtimes = [
  'iOS 17.5',
  'iOS 18.2',
  'iOS 18.3',
  'iOS 18.4',
  'iOS 26.0'
]
devices_for_supplementary_runtimes = [
  'iPhone 16 Pro',
  'iPad Pro 11-inch (M4)'
]

# Custom runtime-device pairs - allows duplicate runtimes with different devices
custom_runtime_device_pairs = [
  { runtime: 'iOS 17.5', device: 'iPhone 15 Pro' },
  { runtime: 'iOS 18.0', device: 'iPhone 14 Pro' },
  { runtime: 'iOS 17.5', device: 'iPad Air 11-inch (M2)' }
]

class SimulatorPopulator
  def initialize(
    core_runtime:, devices_for_core_runtime:,
    supplementary_runtimes:, devices_for_supplementary_runtimes:,
    custom_runtime_device_pairs:
  )
    @core_runtime = core_runtime
    @devices_for_core_runtime = devices_for_core_runtime
    @supplementary_runtimes = supplementary_runtimes
    @devices_for_supplementary_runtimes = devices_for_supplementary_runtimes
    @custom_runtime_device_pairs = custom_runtime_device_pairs

    @device_types = JSON.parse `xcrun simctl list -j devicetypes`
    @runtimes = JSON.parse `xcrun simctl list -j runtimes`
    @devices = JSON.parse `xcrun simctl list -j devices`
    @available_runtimes = @runtimes['runtimes'].select do |runtime|
      runtime['availability'] == '(available)' || runtime['isAvailable'] == true
    end
  end

  def remove_all
    puts 'Listing all existing simulators:'
    @devices['devices'].each do |runtime_name, runtime_devices|
      runtime_devices.each do |device|
        puts Rainbow("• #{device['name']} (#{device['udid']}) [#{runtime_name}]").color(:yellow)
      end
    end
    puts Rainbow('Removing all simulators with `xcrun simctl delete all`...').color(:red).bright
    `xcrun simctl delete all`
  end

  def create_all_groups
    create_core_runtime_devices
    create_supplementary_runtime_devices
    create_custom_runtime_device_pairs
  end

  def create_core_runtime_devices
    puts Rainbow("## Creating core runtime devices (#{@core_runtime})").color(:blue).bright

    @device_types['devicetypes'].each do |device_type|
      next unless @devices_for_core_runtime.include?(device_type['name'])

      create_device(device_type: device_type['identifier'],
                    runtime: @core_runtime,
                    name: "#{device_type['name']} (#{@core_runtime})")
    end
  end

  def create_supplementary_runtime_devices
    puts Rainbow('## Creating supplementary runtime devices').color(:blue).bright

    @supplementary_runtimes.each do |runtime_name|
      next unless runtime_available?(runtime_name)

      puts Rainbow("### #{runtime_name}").color(:cyan).bright
      @device_types['devicetypes'].each do |device_type|
        next unless @devices_for_supplementary_runtimes.include?(device_type['name'])

        create_device(device_type: device_type['identifier'],
                      runtime: runtime_name,
                      name: "#{device_type['name']} (#{runtime_name})")
      end
    end
  end

  def create_custom_runtime_device_pairs
    puts Rainbow('## Creating custom runtime:device pairs').color(:blue).bright

    @custom_runtime_device_pairs.each do |pair|
      runtime_name = pair[:runtime]
      device_name = pair[:device]

      next unless runtime_available?(runtime_name)

      device_type = find_device_type_by_name(device_name)
      if device_type.nil?
        puts "Device type #{Rainbow(device_name).color(:red).bright} not found"
        next
      end

      create_device(device_type: device_type['identifier'],
                    runtime: runtime_name,
                    name: "#{device_name} (#{runtime_name})")
    end
  end

  private

  def runtime_available?(runtime_name)
    @available_runtimes.any? { |runtime| runtime['name'] == runtime_name }
  end

  def find_device_type_by_name(device_name)
    @device_types['devicetypes'].find { |device_type| device_type['name'] == device_name }
  end

  def find_runtime_identifier(runtime_name)
    runtime = @available_runtimes.find { |runtime| runtime['name'] == runtime_name }
    return nil if runtime.nil?

    runtime['identifier']
  end

  def create_device(device_type:, runtime:, name: nil)
    name ||= device_type
    runtime_identifier = find_runtime_identifier(runtime)

    if runtime_identifier.nil?
      puts "Runtime #{Rainbow(runtime).color(:red).bright} not found"
      return
    end

    args = ["'#{name}'", "'#{device_type}'", "'#{runtime_identifier}'"].join ' '

    `xcrun simctl create #{args} 2> /dev/null`
    puts "Created #{Rainbow(name).color(:green).bright}" if $CHILD_STATUS.success?
  end
end

options = {
  'remove-existing' => true,
  'create-core-devices' => true,
  'create-supplementary-devices' => true,
  'create-custom-pairs' => true,
  'verbose' => true
}

option_parser = OptionParser.new do |opts|
  opts.on '-r', '--[no-]remove-existing', 'Remove all existing simulators' do |v|
    options['remove-existing'] = v
  end
  opts.on '--[no-]create-core-devices', "Create core runtime devices (#{core_runtime})" do |v|
    options['create-core-devices'] = v
  end
  opts.on '--[no-]create-supplementary-devices', 'Create supplementary runtime devices' do |v|
    options['create-supplementary-devices'] = v
  end
  opts.on '--[no-]create-custom-pairs', 'Create custom runtime-device pairs' do |v|
    options['create-custom-pairs'] = v
  end
  opts.on '-a', '--[no-]create-all', 'Create all device groups (core, supplementary, and custom)' do |v|
    options['create-core-devices'] = v
    options['create-supplementary-devices'] = v
    options['create-custom-pairs'] = v
  end
  opts.on '-v', '--[no-]verbose', 'Make the operation more talkative (not really, not implemented yet)' do |v|
    options['verbose'] = v
  end
  opts.on '-h', '--help', 'This help' do
    puts opts
    exit
  end
end

option_parser.parse!

populator = SimulatorPopulator.new(
  core_runtime: core_runtime,
  devices_for_core_runtime: devices_for_core_runtime,
  supplementary_runtimes: supplementary_runtimes,
  devices_for_supplementary_runtimes: devices_for_supplementary_runtimes,
  custom_runtime_device_pairs: custom_runtime_device_pairs
)

populator.remove_all if options['remove-existing']

if options['create-core-devices'] || options['create-supplementary-devices'] || options['create-custom-pairs']
  if options['create-core-devices'] && options['create-supplementary-devices'] && options['create-custom-pairs']
    populator.create_all_groups
  else
    populator.create_core_runtime_devices if options['create-core-devices']
    populator.create_supplementary_runtime_devices if options['create-supplementary-devices']
    populator.create_custom_runtime_device_pairs if options['create-custom-pairs']
  end
end
