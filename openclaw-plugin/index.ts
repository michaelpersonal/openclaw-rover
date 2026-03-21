// OpenClaw plugin: Rover Control
// Registers 9 tools for controlling a 2WD rover via serial port.
// Streams telemetry over a Unix socket for the TUI monitor.

import { SerialPort } from "serialport";
import { ReadlineParser } from "@serialport/parser-readline";
import * as net from "net";
import * as fs from "fs";

type PluginApi = {
  pluginConfig?: { serialPort?: string; baudRate?: number };
  logger: { info: (msg: string) => void; warn: (msg: string) => void; error: (msg: string) => void };
  registerTool: (tool: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
    execute: (id: string, params: Record<string, unknown>) => Promise<{ content: { type: string; text: string }[] }>;
  }) => void;
};

let port: SerialPort | null = null;
let parser: ReadlineParser | null = null;
let pending: ((value: string) => void) | null = null;

// Telemetry state
const SOCK_PATH = "/tmp/rover-telemetry.sock";
let socketServer: net.Server | null = null;
const socketClients: Set<net.Socket> = new Set();
let pollerPending = false; // true while poller awaits a STATUS response

// Scan frame config: sensor is front-facing on the current chassis layout.
const SENSOR_FACING_REAR = false;
const SENSOR_HEADING_OFFSET = SENSOR_FACING_REAR ? 180 : 0;

function normalizeAngle(a: number): number {
  return ((a % 360) + 360) % 360;
}

function sendCommand(cmd: string, timeoutMs = 2000): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!port || !port.isOpen) {
      reject(new Error("Serial port not connected. Configure serialPort in plugin config."));
      return;
    }
    pending = resolve;
    port.write(cmd + "\n", (err) => {
      if (err) {
        pending = null;
        reject(err);
      }
    });
    setTimeout(() => {
      if (pending === resolve) {
        pending = null;
        reject(new Error(`Response timeout (${timeoutMs}ms)`));
      }
    }, timeoutMs);
  });
}

function toolResult(text: string) {
  return { content: [{ type: "text" as const, text }] };
}

// === Telemetry functions ===

function parseStatus(raw: string): Record<string, unknown> | null {
  if (!raw.startsWith("STATUS:")) return null;
  const body = raw.slice(7);
  const parts: Record<string, string> = {};
  for (const seg of body.split(";")) {
    const eq = seg.indexOf("=");
    if (eq > 0) parts[seg.slice(0, eq)] = seg.slice(eq + 1);
  }

  const motorParts = (parts.motors || "S,S").split(",");
  function parseMotor(s: string) {
    if (s === "S") return { dir: "S", speed: 0 };
    return { dir: s[0], speed: parseInt(s.slice(1), 10) || 0 };
  }

  return {
    type: "status",
    motors: { left: parseMotor(motorParts[0]), right: parseMotor(motorParts[1] || "S") },
    dist: parseInt((parts.dist || "999").replace("cm", ""), 10),
    heading: parseInt(parts.heading || "0", 10),
    uptime: parseInt(parts.uptime || "0", 10),
    cmds: parseInt(parts.cmds || "0", 10),
    lastCmd: parseInt((parts.last_cmd || "0").replace("ms", ""), 10),
    loopHz: parseInt((parts.loop || "0").replace("hz", ""), 10),
    ts: Date.now(),
  };
}

function broadcast(msg: Record<string, unknown>) {
  const line = JSON.stringify(msg) + "\n";
  for (const client of socketClients) {
    try {
      client.write(line);
    } catch {
      socketClients.delete(client);
    }
  }
}

function startSocketServer(logger: PluginApi["logger"]) {
  try { fs.unlinkSync(SOCK_PATH); } catch {}

  socketServer = net.createServer((client) => {
    socketClients.add(client);
    client.on("close", () => socketClients.delete(client));
    client.on("error", () => socketClients.delete(client));
  });
  socketServer.listen(SOCK_PATH, () => {
    logger.info(`Telemetry socket: ${SOCK_PATH}`);
  });
  socketServer.on("error", (err) => {
    logger.error(`Telemetry socket error: ${err.message}`);
  });
}

function startPoller() {
  // The poller writes STATUS directly to the port instead of using sendCommand,
  // so it never interferes with tool call pending callbacks.
  setInterval(() => {
    if (!port || !port.isOpen || pending !== null || pollerPending) return;
    pollerPending = true;
    port.write("STATUS\n", (err) => {
      if (err) pollerPending = false;
    });
    // Timeout: if no response in 2s, clear the flag so future polls can run
    setTimeout(() => { pollerPending = false; }, 2000);
  }, 250);
}

function formatStatusForLLM(parsed: Record<string, unknown>): string {
  const m = parsed.motors as { left: { dir: string; speed: number }; right: { dir: string; speed: number } };
  const dirName = (d: string) => d === "F" ? "▲" : d === "R" ? "▼" : "■";
  const motorDesc = (motor: { dir: string; speed: number }) =>
    motor.dir === "S" ? "stopped" : `${dirName(motor.dir)} ${motor.speed}`;
  const uptimeSec = Math.floor((parsed.uptime as number) / 1000);
  const h = Math.floor(uptimeSec / 3600);
  const min = Math.floor((uptimeSec % 3600) / 60);
  const s = uptimeSec % 60;
  const upStr = `${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  const dist = parsed.dist as number;
  const distStr = dist >= 999 ? "clear" : `${dist}cm`;
  const distStyle = dist < 20 ? " ⚠️ BLOCKED" : "";
  const heading = parsed.heading as number;
  return [
    `Motors: Left ${motorDesc(m.left)}, Right ${motorDesc(m.right)}`,
    `Distance: ${distStr}${distStyle}`,
    `Heading: ${heading} degrees`,
    `Uptime: ${upStr}`,
    `Commands: ${parsed.cmds} (last ${parsed.lastCmd}ms ago)`,
    `Loop: ${parsed.loopHz} hz`,
  ].join("\n");
}

// === Plugin registration ===

export default function register(api: PluginApi) {
  const serialPath = api.pluginConfig?.serialPort;
  const baudRate = api.pluginConfig?.baudRate ?? 9600;

  if (serialPath) {
    try {
      port = new SerialPort({ path: serialPath, baudRate, lock: false });
      parser = port.pipe(new ReadlineParser({ delimiter: "\n" }));

      parser.on("data", (line: string) => {
        const trimmed = line.trim();
        if (trimmed === "STOPPED:WATCHDOG" || trimmed === "STOPPED:OBSTACLE") {
          api.logger.warn(`Rover: ${trimmed}`);
          broadcast({ type: "event", event: trimmed, ts: Date.now() });
          return;
        }
        // Tool calls take priority over poller
        if (pending) {
          const resolve = pending;
          pending = null;
          resolve(trimmed);
          return;
        }
        // Poller response
        if (pollerPending) {
          pollerPending = false;
          const parsed = parseStatus(trimmed);
          if (parsed) broadcast(parsed);
          return;
        }
        // Unsolicited
        api.logger.warn(`Rover: ${trimmed}`);
      });

      port.on("error", (err) => {
        api.logger.error(`Rover serial error: ${err.message}`);
      });

      api.logger.info(`Rover connected on ${serialPath} @ ${baudRate} baud`);
      startSocketServer(api.logger);
      startPoller();
    } catch (err) {
      api.logger.error(`Failed to open serial port ${serialPath}: ${err}`);
    }
  } else {
    api.logger.warn("Rover plugin: no serialPort configured. Tools will fail until configured.");
  }

  const speedParam = {
    type: "object",
    properties: {
      speed: {
        type: "number",
        description: "Motor speed 0-255. ~80=slow, ~150=medium, ~200=fast, 255=max",
      },
    },
    required: ["speed"],
  };

  const noParams = {
    type: "object",
    properties: {},
    required: [],
  };

  api.registerTool({
    name: "rover_forward",
    description: "Move rover forward at given speed (0-255)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`FORWARD ${params.speed}`);
      broadcast({ type: "command", cmd: "FORWARD", speed: params.speed, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_backward",
    description: "Move rover backward at given speed (0-255)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`BACKWARD ${params.speed}`);
      broadcast({ type: "command", cmd: "BACKWARD", speed: params.speed, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_left",
    description: "Turn rover left (stops left motor, right motor forward)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`LEFT ${params.speed}`);
      broadcast({ type: "command", cmd: "LEFT", speed: params.speed, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_right",
    description: "Turn rover right (left motor forward, stops right motor)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`RIGHT ${params.speed}`);
      broadcast({ type: "command", cmd: "RIGHT", speed: params.speed, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_spin_left",
    description: "Spin rover left in place (left motor reverse, right motor forward)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`SPIN_LEFT ${params.speed}`);
      broadcast({ type: "command", cmd: "SPIN_LEFT", speed: params.speed, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_spin_right",
    description: "Spin rover right in place (left motor forward, right motor reverse)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`SPIN_RIGHT ${params.speed}`);
      broadcast({ type: "command", cmd: "SPIN_RIGHT", speed: params.speed, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_stop",
    description: "Stop all rover motors immediately",
    parameters: noParams,
    async execute() {
      const resp = await sendCommand("STOP");
      broadcast({ type: "command", cmd: "STOP", response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });

  const angleParam = {
    type: "object",
    properties: {
      angle: {
        type: "number",
        description: "Target heading in degrees (0-359). 0=front, 90=right, 180=rear, 270=left",
      },
    },
    required: ["angle"],
  };

  api.registerTool({
    name: "rover_spin_to",
    description: "Spin rover to a specific heading angle (0-359 degrees) using the gyroscope for precision",
    parameters: angleParam,
    async execute(_id, params) {
      const resp = await sendCommand(`SPIN_TO ${params.angle}`, 6000);
      broadcast({ type: "command", cmd: "SPIN_TO", angle: params.angle, response: resp, ts: Date.now() });
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_scan",
    description: "Perform a 360-degree obstacle scan. Spins the rover in 30-degree increments, measuring distance at each angle, then returns to the original heading. Returns a distance map so you can pick the clearest direction.",
    parameters: noParams,
    async execute() {
      // 1. Get current heading
      const statusResp = await sendCommand("STATUS");
      const parsed = parseStatus(statusResp);
      const startHeading = parsed ? (parsed.heading as number) : 0;

      // 2. Scan 12 positions
      const startLogicalHeading = normalizeAngle(startHeading + SENSOR_HEADING_OFFSET);
      const readings: { angle: number; physicalAngle: number; dist: number }[] = [];
      for (let i = 0; i < 12; i++) {
        const physicalAngle = normalizeAngle(startHeading + i * 30);
        await sendCommand(`SPIN_TO ${physicalAngle}`, 6000);
        const stResp = await sendCommand("STATUS");
        const stParsed = parseStatus(stResp);
        const dist = stParsed ? (stParsed.dist as number) : 999;
        const logicalAngle = normalizeAngle(physicalAngle + SENSOR_HEADING_OFFSET);
        readings.push({ angle: logicalAngle, physicalAngle, dist });
      }

      // 3. Return to original heading
      await sendCommand(`SPIN_TO ${startHeading}`, 6000);

      // 4. Format results
      const dirLabel = (a: number): string => {
        const rel = normalizeAngle(a - startLogicalHeading);
        if (rel === 0) return "(front)";
        if (rel === 90) return "(right)";
        if (rel === 180) return "(rear)";
        if (rel === 270) return "(left)";
        return "";
      };

      const lines = readings.map(({ angle, dist }) => {
        const label = dirLabel(angle);
        const status = dist < 20 ? "BLOCKED" : "clear";
        return `  ${String(angle).padStart(3)}deg ${label.padEnd(8)} ${String(dist).padStart(4)}cm  ${status}`;
      });

      const best = readings.reduce((a, b) => a.dist >= b.dist ? a : b);
      const recommendedMove = SENSOR_FACING_REAR ? "backward" : "forward";

      const result = [
        `Scan complete (12 positions, 30deg apart):`,
        ...lines,
        ``,
        `Best clearance: ${best.angle}deg at ${best.dist}cm`,
        `Recommendation: spin to ${best.angle} degrees then drive ${recommendedMove}`,
      ].join("\n");

      broadcast({ type: "event", event: "SCAN_COMPLETE", best: best.angle, bestDist: best.dist, move: SENSOR_FACING_REAR ? "backward" : "forward", ts: Date.now() });

      return toolResult(result);
    },
  });

  api.registerTool({
    name: "rover_status",
    description: "Get current rover state: motor speeds, uptime, command count",
    parameters: noParams,
    async execute() {
      const resp = await sendCommand("STATUS");
      const parsed = parseStatus(resp);
      if (!parsed) return toolResult(resp);
      broadcast(parsed);
      return toolResult(formatStatusForLLM(parsed));
    },
  });
}
