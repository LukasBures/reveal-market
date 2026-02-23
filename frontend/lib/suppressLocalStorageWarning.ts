type WarningState = {
  __rmLocalStorageWarningPatched?: boolean;
};

const stripLocalStorageFlag = (args: string[]) => {
  if (!Array.isArray(args) || args.length === 0) return;
  const cleaned: string[] = [];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === "--localstorage-file") {
      i += 1;
      continue;
    }
    if (arg.startsWith("--localstorage-file=")) {
      continue;
    }
    cleaned.push(arg);
  }
  if (cleaned.length !== args.length) {
    args.splice(0, args.length, ...cleaned);
  }
};

const globalState = globalThis as typeof globalThis & WarningState;
if (!globalState.__rmLocalStorageWarningPatched && typeof process !== "undefined") {
  globalState.__rmLocalStorageWarningPatched = true;
  stripLocalStorageFlag(process.argv);
  stripLocalStorageFlag(process.execArgv);

  const originalEmitWarning = process.emitWarning.bind(process);
  process.emitWarning = ((warning: string | Error, ...args: any[]) => {
    const message = typeof warning === "string" ? warning : warning?.message;
    if (typeof message === "string" && message.includes("--localstorage-file")) {
      return;
    }
    return originalEmitWarning(warning as any, ...(args as any));
  }) as typeof process.emitWarning;
}
