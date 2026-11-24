// 55-neighbours (stage 5): with quality_agent stopped, a user asks it (HTTP 403 and the gateway's sentence), then asks
// release_review and docs_adk, which answer (HTTP 200): only the stopped agent is affected. Changes nothing.
import { term } from '../lib/plugin.mjs';
import { command, idle, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['user'];

const CALLS = [
  ['quality_agent', 'ask quality_agent "What is the spec of part P-100?"', 'HTTP 403', 'the stopped agent is refused'],
  ['release_review', 'ask release_review --file demo_scenes/inputs/change-ok.txt', 'HTTP 200', 'release_review still answers'],
  ['docs_adk', 'ask docs_adk "What is our standard for versioning an API?"', 'HTTP 200', 'docs_adk still answers'],
];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { quality_agent: 'APPROVED', release_review: 'APPROVED', docs_adk: 'APPROVED' },
    stopped: ['quality_agent'] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  await openShell(page, rec, 'user', t);
  await cam.reset('shell', 'the user\'s shell');
  await cam.hold(3000);

  for (const [agent, line, status, label] of CALLS) {
    await command(page, line);
    rec.note(`asked_${agent}`);
    if (!(await idle(page, t.prompt.user, 200000))) throw new Error(`ask ${agent} did not end`);
    const rows = (await term.screenText(page)).split('\n');
    const at = rows.findLastIndex(r => r.includes(line.slice(0, 30)));
    const said = rows.slice(at + 1).find(r => /^HTTP \d{3} /.test(r.trim())) || '(no status line)';
    if (!said.trim().startsWith(status)) throw new Error(`ask ${agent}: ${said.trim()}, not ${status}`);
    rec.note(`${agent}_${status.replace(' ', '_')}`);
    await cam.rows(`answer_${agent}`, line.slice(0, 30), t.prompt.user, { kmax: 1.5 }, label);
    await cam.hold(7000);
  }
  // all three on one frame, when the first call is still on the screen
  if ((await term.screenText(page)).includes(CALLS[0][1].slice(0, 30))) {
    await cam.rows('all', CALLS[0][1].slice(0, 30), t.prompt.user, { kmax: 1.3 }, 'only the stopped agent is refused');
    await cam.hold(7000);
  }
}
