// 43-before (stage 4): before the custom guardrail is attached: a request that names the company's code name is
// answered, and the answer to an inspection question holds the inspector's employee ID (synthetic data of the sample
// tools). 45-after types the same two requests and frames them the same way. Changes nothing.
import { asked, CODE_NAME, INSPECTION } from '../lib/guardrail.mjs';
import { term } from '../lib/plugin.mjs';
import { openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['user'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { quality_agent: 'APPROVED' }, mode: 'ACTIVE', attached: false, stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  const screen = async () => term.screenText(page);
  const count = (s, text) => s.split(text).length - 1;
  await openShell(page, rec, 'user', t);
  await cam.reset('shell', 'the user\'s shell');
  await cam.hold(3000);

  await asked(page, rec, cam, t, CODE_NAME, 'code_name', 'a request that names the code name is answered', async () => {
    const s = await screen();
    return count(s, 'HTTP 200') === 1 ? '' : 'the request with the code name was not answered with HTTP 200';
  });
  await asked(page, rec, cam, t, INSPECTION, 'inspection', 'the answer holds an employee ID', async () => {
    const s = await screen();
    if (count(s, 'HTTP 200') !== 2) return 'the inspection question was not answered with HTTP 200';
    return /EMP-\d{6}/.test(s) ? '' : 'the answer holds no employee ID';
  });
}
