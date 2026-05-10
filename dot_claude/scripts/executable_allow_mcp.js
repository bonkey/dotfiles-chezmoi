#!/usr/bin/env osascript -l JavaScript

ObjC.import('Foundation')

const LOG_PATH = '/tmp/allow_mcp.log'

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`
  const data = $.NSString.alloc.initWithUTF8String(line).dataUsingEncoding($.NSUTF8StringEncoding)
  const fm = $.NSFileManager.defaultManager
  if (!fm.fileExistsAtPath(LOG_PATH)) {
    fm.createFileAtPathContentsAttributes(LOG_PATH, data, $())
    return
  }
  const handle = $.NSFileHandle.fileHandleForWritingAtPath(LOG_PATH)
  if (handle.isNil()) return
  handle.seekToEndOfFile
  handle.writeData(data)
  handle.closeFile
}

function sleep(seconds) {
  $.NSThread.sleepForTimeInterval(seconds)
}

function safe(fn, fallback) {
  try { return fn() } catch (e) { return fallback }
}

function elementHasMcpText(element) {
  const texts = safe(() => element.staticTexts(), [])
  for (const t of texts) {
    const v = safe(() => t.value(), null)
    if (typeof v === 'string' && v.includes('to access Xcode?')) return true
  }
  return false
}

function clickAllowIn(element) {
  const buttons = safe(() => element.buttons(), [])
  for (const b of buttons) {
    const name = safe(() => b.name(), null)
    if (name === 'Allow') {
      const ok = safe(() => { b.click(); return true }, false)
      if (ok) { log('clicked Allow'); return 1 }
    }
  }
  return 0
}

function sweepElement(element) {
  let approved = 0
  if (elementHasMcpText(element)) {
    approved += clickAllowIn(element)
  }
  const sheets = safe(() => element.sheets(), [])
  for (const s of sheets) approved += sweepElement(s)
  return approved
}

function sweep(xcodeProcess) {
  let approved = 0
  const windows = safe(() => xcodeProcess.windows(), [])
  for (const w of windows) approved += sweepElement(w)
  return approved
}

function run() {
  log('=== start ===')
  const xcode = Application('Xcode')
  const running = safe(() => xcode.running(), false)
  if (!running) { log('Xcode not running, exit'); return 'Xcode not running' }

  const systemEvents = Application('System Events')
  const xcodeProcess = systemEvents.processes.byName('Xcode')

  const maxAttempts = 20
  let totalApproved = 0
  let idle = 0

  for (let i = 0; i < maxAttempts; i++) {
    const approved = sweep(xcodeProcess)
    totalApproved += approved
    log(`attempt ${i + 1}/${maxAttempts}: approved=${approved} total=${totalApproved}`)
    if (approved > 0) {
      idle = 0
    } else if (totalApproved > 0) {
      idle++
      if (idle >= 3) { log('idle 3s after approval, exit'); break }
    }
    sleep(1)
  }

  const result = totalApproved > 0
    ? `Approved ${totalApproved} MCP connection(s)`
    : 'No pending MCP dialogs'
  log(`=== end: ${result} ===`)
  return result
}
