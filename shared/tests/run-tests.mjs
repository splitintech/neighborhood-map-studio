import { build } from '../../frontend/node_modules/esbuild/lib/main.js';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const directory = await mkdtemp(join(tmpdir(), 'map-studio-shared-tests-'));
try {
  for (const name of ['contracts', 'leaflet']) {
    const output = join(directory, `${name}.mjs`);
    await build({ entryPoints: [`shared/tests/${name}.test.ts`], bundle: true, platform: 'node', format: 'esm', outfile: output });
    await import(`file://${output}`);
  }
} finally {
  await rm(directory, { recursive: true, force: true });
}
