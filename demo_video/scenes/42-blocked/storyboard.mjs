// 42-blocked (stage 4): with guard_prompt enforced, the same change with the hidden instruction is refused at the agent
// gateway: HTTP 403 and the gateway's sentence, for release_review and for docs_adk (one policy on every agent).
// Changes nothing.
import { term } from '../lib/plugin.mjs';
import { command, idle, openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['user'];

const INPUT = 'demo_scenes/inputs/change-with-hidden-instruction.txt';
const AGENTS = ['release_review', 'docs_adk'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { release_review: 'APPROVED', docs_adk: 'APPROVED' }, mode: 'ACTIVE', stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  await openShell(page, rec, 'user', t);
  await cam.reset('shell', 'the user\'s shell');
  await cam.hold(3000);

  for (const [i, agent] of AGENTS.entries()) {
    await command(page, `ask ${agent} --file ${INPUT}`);
    rec.note(`asked_${agent}`);
    if (!(await idle(page, t.prompt.user, 200000))) throw new Error(`ask ${agent} did not end`);
    const refused = (await term.screenText(page)).split('HTTP 403').length - 1;
    if (refused !== i + 1) throw new Error(`ask ${agent}: not refused with HTTP 403 (${refused} refusals on the screen)`);
    rec.note(`refused_${agent}`);
    await cam.rows(`blocked_${agent}`, `ask ${agent} --file`, t.prompt.user, { kmax: 1.5 }, `${agent} is refused at the gateway`);
    await cam.hold(7000);
  }
  await cam.rows('both', `ask ${AGENTS[0]} --file`, t.prompt.user, { kmax: 1.4 }, 'one policy refuses it for every agent');
  await cam.hold(7000);
}
