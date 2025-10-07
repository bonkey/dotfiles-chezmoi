#!/usr/bin/env ruby

require 'optparse'
require 'json'
require 'rainbow'
require 'English'

# Device arrays
MODERN_DEVICES = [
  'iPhone 17 Pro Max',
  'iPhone 17 Pro',
  'iPhone 16 Pro'
].freeze

ESSENTIAL_DEVICES = [
  'iPhone 16 Pro'
].freeze

FULL_RANGE_DEVICES = [
  'iPad Pro 11-inch (M4)',
  'iPad Pro 13-inch (M4)',
  'iPhone 17 Pro Max',
  'iPhone 17 Pro',
  'iPhone 16 Pro Max',
  'iPhone 16 Pro',
  'iPhone 16',
  'iPhone SE (3rd generation)'
].freeze

# Runtime to devices mapping
RUNTIME_DEVICE_MAPPING = {
  'iOS 26.0' => {
    devices: MODERN_DEVICES,
    aliases: nil
  },
  'iOS 18.6' => {
    devices: FULL_RANGE_DEVICES,
    aliases: nil
  },
  'iOS 18.5' => {
    devices: ['iPhone 16 Pro'],
    aliases: ['iPhone 16 Pro']
  },
  'iOS 18.0' => {
    devices: ['iPhone 16 Pro'],
    aliases: nil
  },
  'iOS 17.5' => {
    devices: ['iPhone 15 Pro'],
    aliases: ['iPhone 15 Pro']
  }
}.freeze

class SimulatorPopulator
  def initialize(runtime_device_mapping:, verbose: false, runtimes_filter: nil)
    @runtime_device_mapping = runtime_device_mapping
    @verbose = verbose
    @runtimes_filter = runtimes_filter

    run_command('xcrun simctl list -j devicetypes') do |output|
      @device_types = JSON.parse(output)
    end

    run_command('xcrun simctl list -j runtimes') do |output|
      @runtimes = JSON.parse(output)
    end

    run_command('xcrun simctl list -j devices') do |output|
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

  def delete_unavailable
    puts 'Deleting unavailable simulators...'
    run_command('xcrun simctl delete unavailable') do |_output|
      puts Rainbow('Deleted unavailable simulators').color(:green).bright if $CHILD_STATUS.success?
    end
  end

  def create
    puts 'Creating simulators based on runtime-device mapping...'

    target_runtimes = @runtimes_filter || @runtime_device_mapping.keys

    @runtime_device_mapping.each do |runtime_name, config|
      next unless runtime_matches_filter?(runtime_name, target_runtimes)

      # Check if this runtime is available
      runtime = @available_runtimes.find { |r| r['name'] == runtime_name }
      unless runtime
        puts Rainbow("Runtime #{runtime_name} not available, skipping...").color(:yellow)
        next
      end

      puts Rainbow("## #{runtime_name}").color(:blue).bright

      devices = config.is_a?(Array) ? config : config[:devices]
      aliases = config.is_a?(Hash) ? config[:aliases] : nil

      devices.each_with_index do |device_name, index|
        puts "  Processing device: #{device_name}" if @verbose
        # Find the device type
        device_type = @device_types['devicetypes'].find { |dt| dt['name'] == device_name }
        unless device_type
          puts Rainbow("ERROR: Device type '#{device_name}' not found!").color(:red).bright
          puts "  Available device types containing '#{device_name.split.first}':"

          # Show similar device types as suggestions
          similar_devices = @device_types['devicetypes']
                            .select { |dt| dt['name'].downcase.include?(device_name.downcase.split.first.downcase) }
                            .map { |dt| dt['name'] }
                            .sort
                            .first(5)

          if similar_devices.any?
            similar_devices.each { |d| puts "    - #{d}" }
          else
            puts '    (none found - run --list-devices to see all)'
          end

          exit 1
        end

        # Determine simulator name
        simulator_name = get_simulator_name(device_name, runtime_name, aliases, index)

        create_device(
          device_type: device_type['identifier'],
          runtime: runtime_name,
          name: simulator_name
        )
      end
    end
  end

  def list_mapping
    puts Rainbow('Runtime to Device Mapping:').color(:cyan).bright
    @runtime_device_mapping.each do |runtime, config|
      puts Rainbow("  #{runtime}:").color(:blue)
      devices = config.is_a?(Array) ? config : config[:devices]
      aliases = config.is_a?(Hash) ? config[:aliases] : nil

      devices.each_with_index do |device, index|
        simulator_name = get_simulator_name(device, runtime, aliases, index)
        if simulator_name == device
          puts "    - #{device}"
        else
          puts "    - #{device} → #{simulator_name}"
        end
      end
    end
  end

  def list_runtimes
    puts Rainbow('Available Runtimes:').color(:cyan).bright
    @available_runtimes.sort_by { |r| r['name'] }.each do |r|
      puts "  - #{r['name']} (#{r['identifier']})"
    end
  end

  def list_devices
    devices = @device_types['devicetypes']
    # Group devices by broad category
    groups = Hash.new { |h, k| h[k] = [] }
    devices.each do |d|
      name = d['name']
      category =
        case name
        when /iPad Pro/i then 'iPad Pro'
        when /iPad Air/i then 'iPad Air'
        when /iPad mini/i then 'iPad Mini'
        when /iPad/i then 'iPad'
        when /Watch.*SE/i then 'Apple Watch SE'
        when /Watch.*Ultra/i then 'Apple Watch Ultra'
        when /Watch/i then 'Apple Watch'
        when /Apple TV|tvOS/i then 'Apple TV'
        when /iPhone/i then 'iPhone'
        when /Vision/i then 'Vision'
        when /Mac/i then 'Mac'
        else 'Other'
        end
      groups[category] << name
    end

    order = ['iPhone', 'iPad', 'iPad Air', 'iPad Mini', 'iPad Pro', 'Apple Watch', 'Apple Watch SE', 'Apple Watch Ultra', 'Apple TV',
             'Vision', 'Mac', 'Other']
    order.each do |cat|
      next unless groups.key?(cat)

      puts Rainbow(cat).color(:cyan).bright
      smart_sort_reverse(groups[cat].uniq).each do |device|
        puts "  • #{device}"
      end
      puts
    end
  end

  def smart_sort_reverse(device_names)
    device_names.sort do |a, b|
      # Extract model numbers for comparison
      a_num = extract_model_number(a)
      b_num = extract_model_number(b)

      if a_num && b_num
        # Both have numbers, compare numerically (reverse order)
        comparison = b_num <=> a_num
        next comparison unless comparison == 0
      elsif a_num && !b_num
        # Only a has number, it comes first (newer)
        next -1
      elsif !a_num && b_num
        # Only b has number, it comes first (newer)
        next 1
      end

      # Fall back to reverse string comparison
      b <=> a
    end
  end

  def extract_model_number(device_name)
    # Extract primary model number (iPhone 17, iPad Pro 13-inch, etc.)
    if match = device_name.match(/(?:iPhone|iPad|Watch Series|Apple TV 4K|Vision Pro)\s+(\d+)/)
      match[1].to_i
    elsif match = device_name.match(/(\d+)(?:st|nd|rd|th)\s+generation/)
      match[1].to_i
    end
  end

  private

  def get_simulator_name(device_name, runtime_name, aliases, index)
    # Use alias if provided
    return aliases[index] if aliases && aliases[index]

    # Default: device name with runtime
    "#{device_name} (#{runtime_name})"
  end

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

    puts Rainbow("$ xcrun simctl create #{args}").color(:magenta) if @verbose
    stderr_output = `xcrun simctl create #{args} 2>&1 >/dev/null`
    if $CHILD_STATUS.success?
      puts "Created #{Rainbow(name).color(:green).bright}"
    else
      error_msg = stderr_output.strip.lines.last&.strip || 'Unknown error'
      puts Rainbow("FAILED to create #{name}: #{error_msg}").color(:red).bright
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

      invalid_runtimes << requested_runtime unless valid_runtimes.include?(normalized_requested) || valid_versions.include?(version_only)
    end

    return unless invalid_runtimes.any?

    puts Rainbow("Error: Invalid runtime identifier(s): #{invalid_runtimes.join(', ')}").color(:red).bright
    puts Rainbow("Available runtime identifiers: #{valid_runtimes.join(', ')}").color(:cyan).bright
    exit 1
  end
end

options = {
  remove_existing: true,
  create_all_variants: true,
  list_mapping: false,
  list_runtimes: false,
  list_devices: false,
  verbose: false,
  runtimes: nil,
  delete_unavailable: true
}

option_parser = OptionParser.new do |opts|
  opts.banner = "Usage: #{$0} [options]"

  opts.on '-r', '--[no-]remove-existing', 'Remove all existing simulators' do |v|
    options[:remove_existing] = v
  end
  opts.on '-c', '--[no-]create-all-variants', 'Create new simulators based on runtime-device mapping' do |v|
    options[:create_all_variants] = v
  end
  opts.on '-u', '--[no-]delete-unavailable', 'Delete unavailable simulators' do |v|
    options[:delete_unavailable] = v
  end

  opts.on '--list-mapping', 'List the runtime to device mapping and exit' do |v|
    options[:list_mapping] = v
  end
  opts.on '--list-runtimes', 'List all available runtimes (from simctl) and exit' do |v|
    options[:list_runtimes] = v
  end
  opts.on '--list-devices', 'List all available device types (from simctl) and exit' do |v|
    options[:list_devices] = v
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

if options[:list_runtimes]
  populator.list_runtimes
  exit unless options[:list_devices]
end

if options[:list_devices]
  populator.list_devices
  exit unless options[:list_runtimes]
end

if options[:list_mapping]
  populator.list_mapping
  exit
end

populator.delete_unavailable if options[:delete_unavailable]
populator.remove_simulators if options[:remove_existing]
populator.create if options[:create_all_variants]
