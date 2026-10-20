import { build } from "esbuild";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
const directory = await mkdtemp(join(tmpdir(), "map-studio-tests-"));
const output = join(directory, "state.test.mjs");
try {
  await build({ entryPoints: ["tests/state.test.ts"], bundle: true, platform: "node", format: "esm", outfile: output });
  await import(`file://${output}`);
} finally {
  await rm(directory, { recursive: true, force: true });
}
