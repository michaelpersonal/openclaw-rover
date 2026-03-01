// OpenClaw plugin: Rover Control
// Registers 8 tools for controlling a 2WD rover via serial port.

import { SerialPort } from "serialport";
import { ReadlineParser } from "@serialport/parser-readline";

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

function sendCommand(cmd: string): Promise<string> {
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
        reject(new Error("Response timeout (2s)"));
      }
    }, 2000);
  });
}

function toolResult(text: string) {
  return { content: [{ type: "text" as const, text }] };
}

export default function register(api: PluginApi) {
  const serialPath = api.pluginConfig?.serialPort;
  const baudRate = api.pluginConfig?.baudRate ?? 9600;

  if (serialPath) {
    try {
      port = new SerialPort({ path: serialPath, baudRate });
      parser = port.pipe(new ReadlineParser({ delimiter: "\n" }));

      parser.on("data", (line: string) => {
        const trimmed = line.trim();
        if (pending) {
          const resolve = pending;
          pending = null;
          resolve(trimmed);
        } else {
          // Unsolicited message (e.g., STOPPED:WATCHDOG)
          api.logger.warn(`Rover: ${trimmed}`);
        }
      });

      port.on("error", (err) => {
        api.logger.error(`Rover serial error: ${err.message}`);
      });

      api.logger.info(`Rover connected on ${serialPath} @ ${baudRate} baud`);
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
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_backward",
    description: "Move rover backward at given speed (0-255)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`BACKWARD ${params.speed}`);
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_left",
    description: "Turn rover left (stops left motor, right motor forward)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`LEFT ${params.speed}`);
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_right",
    description: "Turn rover right (left motor forward, stops right motor)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`RIGHT ${params.speed}`);
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_spin_left",
    description: "Spin rover left in place (left motor reverse, right motor forward)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`SPIN_LEFT ${params.speed}`);
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_spin_right",
    description: "Spin rover right in place (left motor forward, right motor reverse)",
    parameters: speedParam,
    async execute(_id, params) {
      const resp = await sendCommand(`SPIN_RIGHT ${params.speed}`);
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_stop",
    description: "Stop all rover motors immediately",
    parameters: noParams,
    async execute() {
      const resp = await sendCommand("STOP");
      return toolResult(resp);
    },
  });

  api.registerTool({
    name: "rover_status",
    description: "Get current rover state: motor speeds, uptime, command count",
    parameters: noParams,
    async execute() {
      const resp = await sendCommand("STATUS");
      return toolResult(resp);
    },
  });
}
