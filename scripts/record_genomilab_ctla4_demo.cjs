#!/usr/bin/env node
"use strict";

// This is deliberately a postprocessor, not a substitute browser controller.
// The monitored portal session and screenshots must come from Codex's in-app
// Browser client. This script validates that capture ledger and encodes its
// ordered PNG frames as an explicitly labelled screenshot-timelapse MP4.

const crypto = require("node:crypto");
const fs = require("node:fs");
const fsp = fs.promises;
const path = require("node:path");
const {spawn} = require("node:child_process");

const DEFAULT_FRAME_INTERVAL_MS = 1000;
const DEFAULT_HOLD_SECONDS = 5;

function usage() {
  return `Usage:
  node scripts/record_genomilab_ctla4_demo.cjs --run-dir DIR [options]

Options:
  --frames-dir DIR           Default: RUN_DIR/recording-frames
  --capture-log FILE         Default: FRAMES_DIR/capture-provenance.jsonl
  --output FILE.mp4          Default: RUN_DIR/genomilab-ctla4-demo.mp4
  --frame-interval-ms N      Timelapse presentation interval (default: ${DEFAULT_FRAME_INTERVAL_MS})
  --hold-seconds N           Required post-demo_complete coverage (default: ${DEFAULT_HOLD_SECONDS})
  --ffmpeg-path FILE         ffmpeg executable (default: PATH lookup)
  --help                     Show this help

Required in-app Browser runbook (perform before this postprocessor):
  1. Start run_genomilab_ctla4_demo.py with the same --run-dir and
     --wait-for-viewer. Keep the portal alive through capture.
  2. In the Browser skill's persistent in-app Browser session, privately read
     RUN_DIR/launch-url.txt into the browser-control session and open it. Do not
     print, persist, or put the one-time URL in capture-provenance.jsonl.
  3. Once the portal is visibly open, create RUN_DIR/viewer-ready and append a
     session record to capture-provenance.jsonl:
       {"type":"session","browser_surface":"in_app_browser","viewer_ready_at":"<ISO-8601>"}
  4. Follow complete lines in RUN_DIR/timeline.jsonl after viewer-ready. For
     every subsequent line (1-based in the full timeline), navigate to its
     same-document scroll_target with tab.goto, or scroll it with
     tab.cua.scroll, and append the API actually used. Timeline setup records
     written before viewer-ready are retained in the manifest but do not need
     synthetic scroll actions:
       {"type":"scroll","timeline_event_index":1,"stage":"...","scroll_target":"#...","acted_at":"<ISO-8601>","browser_api":"tab.goto"}
  5. Capture viewport images periodically with in-app tab.screenshot. Use one
     truthful, homogeneous format for the run (`.png`, `.jpg`, or `.jpeg`) and
     append one record per image, including the actual media type:
       {"type":"frame","file":"frame-000001.jpg","captured_at":"<ISO-8601>","capture_api":"tab.screenshot","media_type":"image/jpeg"}
  6. After timeline stage demo_complete, keep the portal visible and continue
     capturing for about ${DEFAULT_HOLD_SECONDS} seconds. Then run this command.

The generated MP4 is a screenshot timelapse, never a continuous recording.
The manifest records source-frame hashes, actual capture timing, ffmpeg
provenance, timeline/scroll coverage, and that exact limitation.`;
}

function parseNumber(value, flag, {minimum = 0, integer = false} = {}) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < minimum || (integer && !Number.isInteger(parsed))) {
    throw new Error(`${flag} requires ${integer ? "an integer" : "a number"} >= ${minimum}`);
  }
  return parsed;
}

function parseArgs(argv) {
  const options = {
    runDir: null,
    framesDir: null,
    captureLog: null,
    output: null,
    ffmpegPath: null,
    frameIntervalMs: DEFAULT_FRAME_INTERVAL_MS,
    holdSeconds: DEFAULT_HOLD_SECONDS,
    help: false,
  };
  const values = new Map([
    ["--run-dir", "runDir"],
    ["--frames-dir", "framesDir"],
    ["--capture-log", "captureLog"],
    ["--output", "output"],
    ["--ffmpeg-path", "ffmpegPath"],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    if (flag === "--help" || flag === "-h") {
      options.help = true;
    } else if (values.has(flag)) {
      if (index + 1 >= argv.length || argv[index + 1].startsWith("--")) {
        throw new Error(`${flag} requires a value`);
      }
      options[values.get(flag)] = argv[index + 1];
      index += 1;
    } else if (flag === "--frame-interval-ms") {
      options.frameIntervalMs = parseNumber(argv[++index], flag, {minimum: 100, integer: true});
    } else if (flag === "--hold-seconds") {
      options.holdSeconds = parseNumber(argv[++index], flag, {minimum: 0});
    } else {
      throw new Error(`unknown argument: ${flag}`);
    }
  }
  if (!options.help && !options.runDir) throw new Error("--run-dir is required");
  if (options.help) return options;
  options.runDir = path.resolve(options.runDir);
  options.framesDir = path.resolve(options.framesDir || path.join(options.runDir, "recording-frames"));
  options.captureLog = path.resolve(options.captureLog || path.join(options.framesDir, "capture-provenance.jsonl"));
  options.output = path.resolve(options.output || path.join(options.runDir, "genomilab-ctla4-demo.mp4"));
  if (options.ffmpegPath) options.ffmpegPath = path.resolve(options.ffmpegPath);
  if (path.extname(options.output).toLowerCase() !== ".mp4") throw new Error("--output must end in .mp4");
  for (const [label, candidate] of [["--frames-dir", options.framesDir], ["--capture-log", options.captureLog], ["--output", options.output]]) {
    const relative = path.relative(options.runDir, candidate);
    if (relative.startsWith("..") || path.isAbsolute(relative)) {
      throw new Error(`${label} must stay inside --run-dir`);
    }
  }
  return options;
}

function readJsonLines(contents, label) {
  const lines = contents.split(/\r?\n/u);
  if (lines.at(-1) !== "") throw new Error(`${label} must end with a newline; its final record may be incomplete`);
  lines.pop();
  return lines.filter(Boolean).map((line, index) => {
    try {
      const record = JSON.parse(line);
      if (!record || Array.isArray(record) || typeof record !== "object") throw new Error("record is not an object");
      return record;
    } catch (error) {
      throw new Error(`${label} line ${index + 1} is invalid JSON: ${error.message}`);
    }
  });
}

function isoMilliseconds(value, label) {
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) throw new Error(`${label} must be an ISO-8601 timestamp`);
  return milliseconds;
}

async function sha256File(filePath) {
  const digest = crypto.createHash("sha256");
  await new Promise((resolve, reject) => {
    const stream = fs.createReadStream(filePath);
    stream.on("data", (chunk) => digest.update(chunk));
    stream.once("error", reject);
    stream.once("end", resolve);
  });
  return digest.digest("hex");
}

async function imageFormat(filePath) {
  const handle = await fsp.open(filePath, "r");
  try {
    const header = Buffer.alloc(12);
    const {bytesRead} = await handle.read(header, 0, header.length, 0);
    const bytes = header.subarray(0, bytesRead);
    if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex"))) {
      return {extension: "png", mediaType: "image/png"};
    }
    if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
      return {extension: "jpg", mediaType: "image/jpeg"};
    }
    throw new Error(`${filePath} is not a supported PNG or JPEG image`);
  } finally {
    await handle.close();
  }
}

function executableOnPath(name) {
  for (const directory of String(process.env.PATH || "").split(path.delimiter)) {
    if (!directory) continue;
    const candidate = path.join(directory, name);
    try {
      fs.accessSync(candidate, process.platform === "win32" ? fs.constants.F_OK : fs.constants.X_OK);
      return candidate;
    } catch (_error) {
      // Continue searching PATH.
    }
  }
  return null;
}

async function runProcess(executable, args) {
  return await new Promise((resolve, reject) => {
    const child = spawn(executable, args, {shell: false, stdio: ["ignore", "pipe", "pipe"]});
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout = (stdout + chunk).slice(-32_768); });
    child.stderr.on("data", (chunk) => { stderr = (stderr + chunk).slice(-32_768); });
    child.once("error", reject);
    child.once("close", (code, signal) => resolve({code, signal, stdout, stderr}));
  });
}

async function ffmpegProvenance(explicitPath) {
  const executablePath = explicitPath || executableOnPath(process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg");
  if (!executablePath) throw new Error("ffmpeg was not found; install it or pass --ffmpeg-path");
  await fsp.access(executablePath, process.platform === "win32" ? fs.constants.F_OK : fs.constants.X_OK);
  const result = await runProcess(executablePath, ["-version"]);
  if (result.code !== 0) throw new Error(`ffmpeg -version exited ${result.code}`);
  return {executable_path: executablePath, version: result.stdout.split(/\r?\n/u)[0] || "unknown"};
}

async function validateInputs(options) {
  const timelinePath = path.join(options.runDir, "timeline.jsonl");
  const viewerReadyPath = path.join(options.runDir, "viewer-ready");
  const [timelineText, captureText, viewerStat] = await Promise.all([
    fsp.readFile(timelinePath, "utf8"),
    fsp.readFile(options.captureLog, "utf8"),
    fsp.stat(viewerReadyPath),
  ]);
  if (!viewerStat.isFile()) throw new Error("viewer-ready is not a regular file");
  const timeline = readJsonLines(timelineText, "timeline.jsonl");
  const captureRecords = readJsonLines(captureText, "capture-provenance.jsonl");
  const session = captureRecords.find((record) => record.type === "session");
  if (!session || session.browser_surface !== "in_app_browser") {
    throw new Error("capture provenance must identify browser_surface as in_app_browser");
  }
  const viewerReadyAtMs = isoMilliseconds(session.viewer_ready_at, "session.viewer_ready_at");

  const completionIndex = timeline.findIndex((event) => event.stage === "demo_complete");
  if (completionIndex < 0) throw new Error("timeline.jsonl has no demo_complete event");
  const completionAtMs = isoMilliseconds(timeline[completionIndex].at, "demo_complete.at");
  const scrollRecords = captureRecords.filter((record) => record.type === "scroll");
  const expectedScrolls = [];
  let preViewerTimelineEvents = 0;
  timeline.forEach((event, index) => {
    if (typeof event.scroll_target !== "string" || !event.scroll_target) return;
    const eventAtMs = isoMilliseconds(event.at, `timeline event ${index + 1}.at`);
    // The demo timeline records whole seconds while browser provenance records
    // milliseconds. Treat events in the viewer-ready second as post-handshake.
    if (eventAtMs + 999 < viewerReadyAtMs) {
      preViewerTimelineEvents += 1;
      return;
    }
    const expected = {
      timeline_event_index: index + 1,
      stage: String(event.stage || ""),
      scroll_target: event.scroll_target,
      event_at_ms: eventAtMs,
      next_event_at_ms: index + 1 < timeline.length
        ? isoMilliseconds(timeline[index + 1].at, `timeline event ${index + 2}.at`)
        : null,
    };
    const matchingRecords = scrollRecords.filter((record) =>
      record.timeline_event_index === expected.timeline_event_index
      && record.stage === expected.stage
      && record.scroll_target === expected.scroll_target
      && ["tab.goto", "tab.cua.scroll"].includes(record.browser_api)
    );
    if (matchingRecords.length !== 1) {
      throw new Error(`capture log lacks in-app scroll provenance for timeline event ${index + 1} (${expected.stage} ${expected.scroll_target})`);
    }
    const matching = matchingRecords[0];
    const actedAtMs = isoMilliseconds(matching.acted_at, `scroll event ${index + 1}.acted_at`);
    if (actedAtMs < eventAtMs) {
      throw new Error(`scroll event ${index + 1} predates its timeline event`);
    }
    if (expected.next_event_at_ms !== null && actedAtMs >= expected.next_event_at_ms) {
      throw new Error(`scroll event ${index + 1} occurred after the next timeline event`);
    }
    expected.matching_record = matching;
    expected.acted_at_ms = actedAtMs;
    expectedScrolls.push(expected);
  });
  if (scrollRecords.length !== expectedScrolls.length) {
    throw new Error("capture log contains unexpected, duplicate, or pre-viewer scroll records");
  }

  const frameRecords = captureRecords.filter((record) => record.type === "frame");
  if (!frameRecords.length) throw new Error("capture log contains no frame records");
  const diskFrameNames = (await fsp.readdir(options.framesDir))
    .filter((name) => /^frame-\d{6}\.(?:png|jpe?g)$/iu.test(name))
    .sort();
  const loggedFrameNames = frameRecords.map((record) => record.file);
  if (JSON.stringify(diskFrameNames) !== JSON.stringify(loggedFrameNames)) {
    throw new Error("ordered PNG files do not exactly match capture-log frame records");
  }
  const firstExtension = path.extname(frameRecords[0].file).slice(1).toLowerCase();
  if (!new Set(["png", "jpg", "jpeg"]).has(firstExtension)) {
    throw new Error("frame files must use .png, .jpg, or .jpeg");
  }
  const frames = [];
  const frameSetDigest = crypto.createHash("sha256");
  let runImageFormat = null;
  for (let index = 0; index < frameRecords.length; index += 1) {
    const record = frameRecords[index];
    const expectedName = `frame-${String(index + 1).padStart(6, "0")}.${firstExtension}`;
    if (record.file !== expectedName) throw new Error(`frame ${index + 1} must be named ${expectedName}`);
    if (record.capture_api !== "tab.screenshot") throw new Error(`${expectedName} was not attributed to in-app tab.screenshot`);
    const capturedAtMs = isoMilliseconds(record.captured_at, `${expectedName}.captured_at`);
    const framePath = path.join(options.framesDir, expectedName);
    const stat = await fsp.lstat(framePath);
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`${framePath} is not a regular frame file`);
    const detected = await imageFormat(framePath);
    const extensionMatches = firstExtension === "png"
      ? detected.extension === "png"
      : detected.extension === "jpg";
    if (!extensionMatches) throw new Error(`${expectedName} extension does not match its image signature`);
    if (record.media_type && record.media_type !== detected.mediaType) {
      throw new Error(`${expectedName} media_type does not match its image signature`);
    }
    if (runImageFormat && runImageFormat.mediaType !== detected.mediaType) {
      throw new Error("all recording frames must use one image format");
    }
    runImageFormat = detected;
    const sha256 = await sha256File(framePath);
    frameSetDigest.update(`${expectedName}\0${sha256}\n`, "utf8");
    frames.push({file: expectedName, captured_at: record.captured_at, captured_at_ms: capturedAtMs, bytes: stat.size, sha256});
  }
  for (let index = 1; index < frames.length; index += 1) {
    if (frames[index].captured_at_ms < frames[index - 1].captured_at_ms) {
      throw new Error("frame capture timestamps are not monotonic");
    }
  }
  expectedScrolls.forEach((expected) => {
    const scrollPosition = captureRecords.indexOf(expected.matching_record);
    const nextRecord = captureRecords[scrollPosition + 1];
    if (!nextRecord || nextRecord.type !== "frame") {
      throw new Error(`scroll event ${expected.timeline_event_index} must be followed immediately by a captured frame`);
    }
    const capturedAtMs = isoMilliseconds(
      nextRecord.captured_at,
      `frame after scroll event ${expected.timeline_event_index}.captured_at`,
    );
    if (capturedAtMs < expected.acted_at_ms) {
      throw new Error(`frame after scroll event ${expected.timeline_event_index} predates the scroll`);
    }
    if (expected.next_event_at_ms !== null && capturedAtMs >= expected.next_event_at_ms) {
      throw new Error(`frame after scroll event ${expected.timeline_event_index} was captured after the next timeline event`);
    }
  });
  const holdActualSeconds = (frames.at(-1).captured_at_ms - completionAtMs) / 1000;
  const holdToleranceSeconds = 0.25;
  if (holdActualSeconds + holdToleranceSeconds < options.holdSeconds) {
    throw new Error(`last frame covers only ${holdActualSeconds.toFixed(3)}s after demo_complete; expected about ${options.holdSeconds}s`);
  }
  const intervals = frames.slice(1).map((frame, index) => frame.captured_at_ms - frames[index].captured_at_ms);
  return {
    timelinePath,
    viewerReadyPath,
    timeline,
    completionIndex,
    completionAtMs,
    viewerReadyAtMs,
    preViewerTimelineEvents,
    expectedScrolls,
    scrollRecords,
    frames,
    frameSetSha256: frameSetDigest.digest("hex"),
    actualCaptureSpanMs: frames.at(-1).captured_at_ms - frames[0].captured_at_ms,
    actualIntervalsMs: intervals,
    holdActualSeconds,
    frameExtension: firstExtension,
    frameMediaType: runImageFormat.mediaType,
  };
}

function intervalSummary(intervals) {
  if (!intervals.length) return {minimum: null, median: null, maximum: null};
  const sorted = [...intervals].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  return {minimum: sorted[0], median, maximum: sorted.at(-1)};
}

async function encode(options) {
  const startedAt = new Date();
  const manifestPath = path.join(options.runDir, "recording-manifest.json");
  try {
    await fsp.access(manifestPath);
    throw new Error(`refusing to overwrite existing manifest: ${manifestPath}`);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  try {
    await fsp.access(options.output);
    throw new Error(`refusing to overwrite existing output: ${options.output}`);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }

  const validated = await validateInputs(options);
  const ffmpeg = await ffmpegProvenance(options.ffmpegPath);
  const inputFramerate = (1000 / options.frameIntervalMs).toFixed(6).replace(/0+$/u, "").replace(/\.$/u, "");
  const stagedOutput = path.join(
    path.dirname(options.output),
    `.${path.basename(options.output, ".mp4")}.encoding-${crypto.randomBytes(6).toString("hex")}.mp4`,
  );
  const argumentsList = [
    "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
    "-framerate", inputFramerate, "-start_number", "1",
    "-i", path.join(options.framesDir, `frame-%06d.${validated.frameExtension}`),
    "-frames:v", String(validated.frames.length),
    "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-an", "-c:v", "libx264",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart", stagedOutput,
  ];
  try {
    const result = await runProcess(ffmpeg.executable_path, argumentsList);
    if (result.code !== 0) {
      throw new Error(`ffmpeg exited ${result.code}${result.signal ? ` (${result.signal})` : ""}: ${result.stderr.trim()}`);
    }
    const stagedStat = await fsp.stat(stagedOutput);
    if (!stagedStat.isFile() || stagedStat.size === 0) {
      throw new Error("ffmpeg did not produce a nonempty regular MP4 file");
    }
    await fsp.rename(stagedOutput, options.output);
  } catch (error) {
    try {
      await fsp.unlink(stagedOutput);
    } catch (cleanupError) {
      if (cleanupError.code !== "ENOENT") throw cleanupError;
    }
    throw error;
  }
  const outputStat = await fsp.stat(options.output);
  const finishedAt = new Date();
  const manifest = {
    status: "completed",
    started_at: startedAt.toISOString(),
    finished_at: finishedAt.toISOString(),
    capture: {
      method: "in_app_browser_periodic_viewport_screenshots_encoded_as_mp4_with_ffmpeg",
      continuous_recording: false,
      truthful_label: "screenshot timelapse; not a continuous recording",
      browser_surface: "in_app_browser",
      browser_capture_api: "tab.screenshot",
      browser_scroll_apis: [...new Set(validated.scrollRecords.map((record) => record.browser_api))].sort(),
      launch_url_handling: "performed privately in the in-app Browser session; URL not read or recorded by this postprocessor",
      source_frames: {
        directory: options.framesDir,
        provenance_log: options.captureLog,
        provenance_log_sha256: await sha256File(options.captureLog),
        count: validated.frames.length,
        file_extension: validated.frameExtension,
        media_type: validated.frameMediaType,
        ordered_set_sha256: validated.frameSetSha256,
        first_captured_at: validated.frames[0].captured_at,
        last_captured_at: validated.frames.at(-1).captured_at,
        actual_capture_span_ms: validated.actualCaptureSpanMs,
        actual_interval_ms: intervalSummary(validated.actualIntervalsMs),
        presentation_interval_ms: options.frameIntervalMs,
        presentation_timing_note: "ffmpeg presents each screenshot for the configured fixed interval; actual capture timestamps remain in the provenance log",
      },
    },
    coordination: {
      viewer_ready_path: validated.viewerReadyPath,
      viewer_ready_observed: true,
      timeline_path: validated.timelinePath,
      timeline_sha256: await sha256File(validated.timelinePath),
      timeline_events_observed: validated.timeline.length,
      pre_viewer_timeline_events: validated.preViewerTimelineEvents,
      scroll_targets_verified: validated.expectedScrolls.length,
      demo_complete_event_index: validated.completionIndex + 1,
      demo_complete_at: new Date(validated.completionAtMs).toISOString(),
      post_completion_hold_seconds_requested: options.holdSeconds,
      post_completion_frame_coverage_seconds: Number(validated.holdActualSeconds.toFixed(3)),
    },
    encoder: {
      name: "ffmpeg",
      executable_path: ffmpeg.executable_path,
      version: ffmpeg.version,
      arguments: [...argumentsList.slice(0, -1), options.output],
      output_staging: "same-directory temporary MP4 followed by atomic rename",
      input_framerate: Number(inputFramerate),
    },
    output: {
      path: options.output,
      format: "mp4",
      codec: "H.264",
      audio: false,
      bytes: outputStat.size,
      sha256: await sha256File(options.output),
      nominal_duration_seconds: Number((validated.frames.length * options.frameIntervalMs / 1000).toFixed(3)),
    },
  };
  await fsp.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, {encoding: "utf8", mode: 0o600, flag: "wx"});
  return {manifestPath, outputPath: options.output, frameCount: validated.frames.length};
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`Error: ${error.message}\n\n${usage()}\n`);
    process.exitCode = 2;
    return;
  }
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  try {
    const result = await encode(options);
    process.stdout.write(`Encoded ${result.frameCount} in-app Browser screenshots as a timelapse.\nManifest: ${result.manifestPath}\nOutput: ${result.outputPath}\n`);
  } catch (error) {
    process.stderr.write(`Encoding failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}

void main();
