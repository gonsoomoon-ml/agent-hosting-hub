// 45-after (stage 4): with the custom guardrail attached, the same two requests as 43-before, framed the same way: the
// request that names the code name is refused (HTTP 403 and the interceptor's sentence), and the answer to the
// inspection question holds {employee_id} where 43-before showed the employee ID. Changes nothing.
import { asked, CODE_NAME, INSPECTION } from '../lib/guardrail.mjs';
import { term } from '../lib/plugin.mjs';
import { openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['user'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { quality_agent: 'APPROVED' }, mode: 'ACTIVE', attached: true, stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  const screen = async () => term.screenText(page);
  await openShell(page, rec, 'user', t);
  await cam.reset('shell', 'the user\'s shell');
  await cam.hold(3000);

  await asked(page, rec, cam, t, CODE_NAME, 'code_name', 'the code name is refused by the custom guardrail', async () => {
    const s = await screen();
    return s.includes('HTTP 403') && s.includes('interceptor') ? '' : 'the request with the code name was not refused by the interceptor';
  });
  await asked(page, rec, cam, t, INSPECTION, 'inspection', 'the employee ID is masked', async () => {
    const s = await screen();
    if (!s.includes('HTTP 200')) return 'the inspection question was not answered with HTTP 200';
    if (/EMP-\d{6}/.test(s)) return 'the answer still holds an employee ID';
    return s.includes('{employee_id}') ? '' : 'the answer holds no {employee_id}';
  });
}
