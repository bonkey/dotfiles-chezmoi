#!/usr/bin/env ruby

require 'optparse'
require 'json'
require 'rainbow'
require 'English'

# Device arrays
MINIMAL_DEVICES = [
  'iPhone 16 Pro'
].freeze

STANDARD_DEVICES = [
  'iPad Pro 11-inch (M4)',
  'iPad Pro 13-inch (M4)',
  'iPhone 16 Pro Max',
  'iPhone 16 Pro',
  'iPhone 16',
  'iPhone SE (3rd generation)'
].freeze

# Runtime to devices mapping
RUNTIME_DEVICE_MAPPING = {
  'iOS 26.0' => MINIMAL_DEVICES,
  'iOS 18.6' => STANDARD_DEVICES,
  'iOS 18.5' => MINIMAL_DEVICES,
  'iOS 17.5' => ['iPhone 15 Pro']
}.freeze


class SimulatorPopulator
  def initialize(runtime_device_mapping:, verbose: false, runtimes_filter: nil)
    @runtime_device_mapping = runtime_device_mapping
    @verbose = verbose
    @runtimes_filter = runtimes_filter

    run_command("xcrun simctl list -j devicetypes") do |output|
      @device_types = JSON.parse(output)
    end

    run_command("xcrun simctl list -j runtimes") do |output|
      @runtimes = JSON.parse(output)
    end

    run_command("xcrun simctl list -j devices") do |output|
      @devices = JSON.parse(output)
    end

    @available_runtimes = @runtimes['runtimes'].select do |runtime|
      runtime['availability'] == '(available)' || runtime['isAvailable'] == true
    end

    # Validate runtime filter if provided
    validate_runtime_filter if @runtimes_filter
  end

  def remove_simulators
    puts 'Removing simulators...'
    target_runtimes = @runtimes_filter || @runtime_device_mapping.keys

    @devices['devices'].each do |runtime_key, runtime_devices|
      # Extract runtime name from the key (e.g., "com.apple.CoreSimulator.SimRuntime.iOS-18-5" -> "iOS 18.5")
      runtime_name = extract_runtime_name_from_key(runtime_key)
      next unless runtime_matches_filter?(runtime_name, target_runtimes)

      runtime_devices.each do |device|
        puts 'Removing: ' +
             Rainbow("#{device['name']} (#{device['udid']})").color(:red).bright
        run_command("xcrun simctl delete #{device['udid']}")
      end
    end
  end

  def create
    puts 'Creating simulators based on runtime-device mapping...'

    target_runtimes = @runtimes_filter || @runtime_device_mapping.keys

    @runtime_device_mapping.each do |runtime_name, devices_for_runtime|
      next unless runtime_matches_filter?(runtime_name, target_runtimes)

      # Check if this runtime is available
      runtime = @available_runtimes.find { |r| r['name'] == runtime_name }
      unless runtime
        puts Rainbow("Runtime #{runtime_name} not available, skipping...").color(:yellow)
        next
      end

      puts Rainbow("## #{runtime_name}").color(:blue).bright

      devices_for_runtime.each do |device_name|
        # Find the device type
        device_type = @device_types['devicetypes'].find { |dt| dt['name'] == device_name }
        unless device_type
          puts Rainbow("Device type #{device_name} not found, skipping...").color(:yellow)
          next
        end

        create_device(
          device_type: device_type['identifier'],
          runtime: runtime_name,
          name: "#{device_name} (#{runtime_name})"
        )
      end
    end
  end



  def list_mapping
    puts Rainbow('Runtime to Device Mapping:').color(:cyan).bright
    @runtime_device_mapping.each do |runtime, devices|
      puts Rainbow("  #{runtime}:").color(:blue)
      devices.each do |device|
        puts "    - #{device}"
      end
    end
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

    run_command("xcrun simctl create #{args} 2> /dev/null") do |output|
      puts "Created #{Rainbow(name).color(:green).bright}" if $CHILD_STATUS.success?
    end
  end

  def run_command(command)
    puts Rainbow("$ #{command}").color(:magenta) if @verbose
    output = `#{command}`
    yield output if block_given?
    output
  end

  def extract_runtime_name_from_key(runtime_key)
    # Convert keys like "com.apple.CoreSimulator.SimRuntime.iOS-18-5" to "iOS 18.5"
    if runtime_key.include?('iOS')
      version_part = runtime_key.split('iOS-').last
      "iOS #{version_part.gsub('-', '.')}"
    else
      runtime_key
    end
  end

  def runtime_matches_filter?(runtime_name, target_runtimes)
    return true if target_runtimes.include?(runtime_name)

    # Also check if runtime matches without iOS prefix
    version = runtime_name.gsub('iOS ', '')
    target_runtimes.include?(version)
  end

  def validate_runtime_filter
    return unless @runtimes_filter

    valid_runtimes = @runtime_device_mapping.keys
    valid_versions = valid_runtimes.map { |r| r.gsub('iOS ', '') }

    invalid_runtimes = []

    @runtimes_filter.each do |requested_runtime|
      # Check if it matches any valid runtime (with or without iOS prefix)
      normalized_requested = requested_runtime.start_with?('iOS ') ? requested_runtime : "iOS #{requested_runtime}"
      version_only = requested_runtime.gsub('iOS ', '')

      unless valid_runtimes.include?(normalized_requested) || valid_versions.include?(version_only)
        invalid_runtimes << requested_runtime
      end
    end

    if invalid_runtimes.any?
      puts Rainbow("Error: Invalid runtime identifier(s): #{invalid_runtimes.join(', ')}").color(:red).bright
      puts Rainbow("Available runtime identifiers: #{valid_runtimes.join(', ')}").color(:cyan).bright
      exit 1
    end
  end
end

options = {
  remove_existing: true,
  create_all_variants: true,
  list_mapping: false,
  verbose: false,
  runtimes: nil
}

option_parser = OptionParser.new do |opts|
  opts.banner = "Usage: #{$0} [options]"

  opts.on '-r', '--[no-]remove-existing', 'Remove all existing simulators' do |v|
    options[:remove_existing] = v
  end
  opts.on '-c', '--[no-]create-all-variants', 'Create new simulators based on runtime-device mapping' do |v|
    options[:create_all_variants] = v
  end

  opts.on '-l', '--list-mapping', 'List the runtime to device mapping and exit' do |v|
    options[:list_mapping] = v
  end
  opts.on '--runtimes RUNTIMES', 'Comma-separated list of iOS versions to target (e.g., "26.0,18.5" or "iOS 26.0,iOS 18.5")' do |v|
    options[:runtimes] = v.split(',').map(&:strip)
  end
  opts.on '-v', '--[no-]verbose', 'Show shell commands being executed' do |v|
    options[:verbose] = v
  end
  opts.on '-h', '--help', 'Show this help' do
    puts opts
    exit
  end
end

option_parser.parse!

populator = SimulatorPopulator.new(
  runtime_device_mapping: RUNTIME_DEVICE_MAPPING,
  verbose: options[:verbose],
  runtimes_filter: options[:runtimes]
)

if options[:list_mapping]
  populator.list_mapping
  exit
end

populator.remove_simulators if options[:remove_existing]
populator.create if options[:create_all_variants]
