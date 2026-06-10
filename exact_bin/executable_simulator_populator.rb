#!/usr/bin/env ruby
# frozen_string_literal: true

require 'optparse'
require 'json'
require 'English'

# Minimal ANSI colorizer — no external gems. Coloring is skipped when output
# isn't a TTY (e.g. piped) or NO_COLOR is set (https://no-color.org).
module Tint
  CODES = { red: 31, green: 32, yellow: 33, blue: 34, magenta: 35, cyan: 36 }.freeze

  module_function

  def enabled?
    $stdout.tty? && !ENV.key?('NO_COLOR')
  end

  def paint(text, color, bright: false)
    return text.to_s unless enabled?

    weight = bright ? '1;' : ''
    "\e[#{weight}#{CODES.fetch(color)}m#{text}\e[0m"
  end
end

# Devices created for runtimes in the latest two installed major iOS versions.
# Older runtimes get a minimal setup: the newest iPhone they support.
BIG_DEVICE_LIST = [
  'iPhone 17 Pro',
  'iPhone 17',
  'iPad Pro 11-inch (M4)',
  'iPad Pro 13-inch (M4)',
  'iPhone SE (3rd generation)'
].freeze

class SimulatorPopulator # rubocop:disable Metrics/ClassLength
  def initialize(verbose: false, runtimes_filter: nil)
    @verbose = verbose
    @runtimes_filter = runtimes_filter

    @device_types = load_simctl_json('devicetypes')
    @runtimes = load_simctl_json('runtimes')
    @devices = load_simctl_json('devices')

    @available_runtimes = @runtimes['runtimes'].select do |runtime|
      runtime['availability'] == '(available)' || runtime['isAvailable'] == true
    end

    @runtime_device_mapping = build_runtime_device_mapping

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
        puts "Removing: #{Tint.paint("#{device['name']} (#{device['udid']})", :red, bright: true)}"
        run_command("xcrun simctl delete #{device['udid']}")
      end
    end
  end

  def remove_all_simulators
    puts Tint.paint('Removing ALL simulators (every runtime)...', :red, bright: true)
    run_command('xcrun simctl delete all') do |_output|
      puts Tint.paint('Deleted all simulators', :green, bright: true) if $CHILD_STATUS.success?
    end
  end

  def delete_unavailable
    puts 'Deleting unavailable simulators...'
    run_command('xcrun simctl delete unavailable') do |_output|
      puts Tint.paint('Deleted unavailable simulators', :green, bright: true) if $CHILD_STATUS.success?
    end
  end

  def create
    puts 'Creating simulators based on runtime-device mapping...'
    target_runtimes = @runtimes_filter || @runtime_device_mapping.keys

    @runtime_device_mapping.each do |runtime_name, devices|
      next unless runtime_matches_filter?(runtime_name, target_runtimes)

      create_runtime_devices(runtime_name, devices)
    end
  end

  def list_mapping
    puts Tint.paint('Runtime to Device Mapping:', :cyan, bright: true)
    @runtime_device_mapping.each do |runtime, devices|
      puts Tint.paint("  #{runtime}:", :blue)
      devices.each do |device|
        puts "    - #{device} → #{device} (#{runtime})"
      end
    end
  end

  private

  def load_simctl_json(kind)
    run_command("xcrun simctl list -j #{kind}") { |output| return JSON.parse(output) }
  end

  # Latest two major iOS versions get BIG_DEVICE_LIST (filtered to what the
  # runtime supports); older runtimes get the newest iPhone they support.
  # supportedDeviceTypes is ordered newest-first by simctl.
  def build_runtime_device_mapping
    ios_runtimes = @available_runtimes.select { |r| r['name'].start_with?('iOS') }
    big_majors = ios_runtimes.map { |r| major_version(r) }.uniq.max(2)

    ios_runtimes.sort_by { |r| Gem::Version.new(r['version']) }.reverse.to_h do |runtime|
      supported = runtime['supportedDeviceTypes'].map { |dt| dt['name'] }
      devices = if big_majors.include?(major_version(runtime))
                  BIG_DEVICE_LIST.select { |name| supported.include?(name) }
                else
                  [top_iphone(runtime)].compact
                end
      [runtime['name'], devices]
    end
  end

  def major_version(runtime)
    runtime['version'].split('.').first.to_i
  end

  def top_iphone(runtime)
    device = runtime['supportedDeviceTypes'].find { |dt| dt['productFamily'] == 'iPhone' }
    device && device['name']
  end

  def create_runtime_devices(runtime_name, devices)
    unless @available_runtimes.any? { |r| r['name'] == runtime_name }
      puts Tint.paint("Runtime #{runtime_name} not available, skipping...", :yellow)
      return
    end

    puts Tint.paint("## #{runtime_name}", :blue, bright: true)
    devices.each { |device_name| create_for_runtime(device_name, runtime_name) }
  end

  def create_for_runtime(device_name, runtime_name)
    device_type = @device_types['devicetypes'].find { |dt| dt['name'] == device_name }
    unless device_type
      puts Tint.paint("Device type #{device_name} not found, skipping...", :yellow)
      return
    end

    create_device(
      device_type: device_type['identifier'],
      runtime: runtime_name,
      name: device_name
    )
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
      puts "Runtime #{Tint.paint(runtime, :red, bright: true)} not found"
      return
    end
    args = ["'#{name}'", "'#{device_type}'", "'#{runtime_id}'"].join ' '

    run_command("xcrun simctl create #{args} 2> /dev/null") do |_output|
      puts "Created #{Tint.paint(name, :green, bright: true)}" if $CHILD_STATUS.success?
    end
  end

  def run_command(command)
    puts Tint.paint("$ #{command}", :magenta) if @verbose
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
    invalid = @runtimes_filter.reject { |r| valid_runtime?(r, valid_runtimes) }
    return if invalid.empty?

    puts Tint.paint("Error: Invalid runtime identifier(s): #{invalid.join(', ')}", :red, bright: true)
    puts Tint.paint("Available runtime identifiers: #{valid_runtimes.join(', ')}", :cyan, bright: true)
    exit 1
  end

  def valid_runtime?(requested, valid_runtimes)
    normalized = requested.start_with?('iOS ') ? requested : "iOS #{requested}"
    valid_runtimes.include?(normalized) ||
      valid_runtimes.map { |r| r.gsub('iOS ', '') }.include?(requested.gsub('iOS ', ''))
  end
end

options = {
  remove_existing: true,
  remove_all: false,
  create_all_variants: true,
  list_mapping: false,
  verbose: false,
  runtimes: nil,
  delete_unavailable: true
}

option_parser = OptionParser.new do |opts| # rubocop:disable Metrics/BlockLength
  opts.banner = "Usage: #{$PROGRAM_NAME} [options]"

  opts.on '-r', '--[no-]remove-existing', 'Remove simulators in runtimes covered by the mapping' do |v|
    options[:remove_existing] = v
  end
  opts.on '--remove-all', 'Remove EVERY simulator across ALL runtimes (ignores mapping/--runtimes)' do |v|
    options[:remove_all] = v
  end
  opts.on '-c', '--[no-]create-all-variants', 'Create new simulators based on runtime-device mapping' do |v|
    options[:create_all_variants] = v
  end
  opts.on '-u', '--[no-]delete-unavailable', 'Delete unavailable simulators' do |v|
    options[:delete_unavailable] = v
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
  verbose: options[:verbose],
  runtimes_filter: options[:runtimes]
)

if options[:list_mapping]
  populator.list_mapping
  exit
end

populator.delete_unavailable if options[:delete_unavailable]
if options[:remove_all]
  populator.remove_all_simulators
elsif options[:remove_existing]
  populator.remove_simulators
  puts Tint.paint('Hint: pass --remove-all to also wipe simulators in runtimes outside the mapping.', :cyan)
end
populator.create if options[:create_all_variants]
