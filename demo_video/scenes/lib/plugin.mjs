// The video plugin's terminal helpers (term.mjs), found through DEMO_VIDEO_PLUGIN, the plugin's scripts folder:
// https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const folder = process.env.DEMO_VIDEO_PLUGIN;
if (!folder) {
  throw new Error('DEMO_VIDEO_PLUGIN must name the scripts folder of the demo-video plugin (term.mjs): '
    + 'https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video');
}
export const term = await import(pathToFileURL(path.join(folder, 'term.mjs')).href);
