import { closeSync, constants as FS, fstatSync, lstatSync, openSync, readSync } from "fs";
import { isAbsolute } from "path";

const MAX_FILE_BYTES = 64 * 1024;
const FUTURE_MTIME_SKEW_MS = 30_000;

type SecretOptions = {
  envName: string;
  fileEnvName: string;
  maxAgeEnvName: string;
  required: boolean;
  devFallback?: string;
};

function devMode(): boolean {
  return ["1", "true", "yes", "on"].includes((process.env.TANAGHOM_DEV_MODE || "").trim().toLowerCase());
}

function secureFile(path: string, options: SecretOptions): string {
  if (!isAbsolute(path)) throw new Error(`${options.fileEnvName} must be an absolute path`);
  const maxAgeRaw = (process.env[options.maxAgeEnvName] || "").trim();
  const maxAge = Number(maxAgeRaw);
  if (!maxAgeRaw || !Number.isInteger(maxAge) || maxAge <= 0) {
    throw new Error(`${options.fileEnvName} requires a positive ${options.maxAgeEnvName}`);
  }
  const leaf = lstatSync(path);
  if (leaf.isSymbolicLink()) throw new Error(`${options.fileEnvName} must not be a symlink`);
  const fd = openSync(path, FS.O_RDONLY | (FS.O_NOFOLLOW || 0));
  try {
    const stat = fstatSync(fd);
    if (!stat.isFile()) throw new Error(`${options.fileEnvName} must be a regular file`);
    if (stat.mode & 0o077) throw new Error(`${options.fileEnvName} must have zero group/world permissions`);
    const euid = typeof process.geteuid === "function" ? process.geteuid() : stat.uid;
    if (stat.uid !== 0 && stat.uid !== euid) {
      throw new Error(`${options.fileEnvName} must be owned by root or the process user`);
    }
    if (stat.size > MAX_FILE_BYTES) throw new Error(`${options.fileEnvName} exceeds 64 KiB`);
    const now = Date.now();
    if (stat.mtimeMs > now + FUTURE_MTIME_SKEW_MS) throw new Error(`${options.fileEnvName} mtime is in the future`);
    if (now - stat.mtimeMs > maxAge * 1000) throw new Error(`${options.fileEnvName} is stale`);
    const chunks: Buffer[] = [];
    let total = 0;
    for (;;) {
      const chunk = Buffer.allocUnsafe(4096);
      const count = readSync(fd, chunk, 0, chunk.length, total);
      if (count === 0) break;
      total += count;
      if (total > MAX_FILE_BYTES) throw new Error(`${options.fileEnvName} exceeds 64 KiB`);
      chunks.push(Buffer.from(chunk.subarray(0, count)));
    }
    let value: string;
    try {
      value = new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)).trim();
    } catch {
      throw new Error(`${options.fileEnvName} is not valid UTF-8`);
    }
    if (!value) throw new Error(`${options.fileEnvName} is empty`);
    return value;
  } finally {
    closeSync(fd);
  }
}

export function resolveSecret(options: SecretOptions): string | null {
  const envValue = (process.env[options.envName] || "").trim();
  const filePath = (process.env[options.fileEnvName] || "").trim();
  if (envValue && filePath) throw new Error(`${options.envName} and ${options.fileEnvName} are both set`);
  if (filePath) return secureFile(filePath, options);
  if (envValue) return envValue;
  if (options.devFallback && devMode()) return options.devFallback;
  if (options.required) throw new Error(`${options.envName} is not configured`);
  return null;
}
