// 41-enforce (stage 4): the platform engineer raises guard_prompt from log-only to enforce on the policy page: the
// press, the job's lines (the same policies switched, not made anew), the card reading enforce (ACTIVE) and the agent
// gateway's policy rows in that mode. Changes the hub (one press). With REHEARSE=1 in the environment the take does
// everything but the press.
import { openPage, press, waitForJob } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';
import { policyRows, PROMPT_CARD } from '../lib/policies.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, tap, option }) {
  await needState({ records: { release_review: 'APPROVED', docs_adk: 'APPROVED', quality_agent: 'APPROVED' },
    reviewing: [], mode: 'LOG_ONLY', attached: false, stopped: [] });
  texts(option);
  const cam = kit({ page, rec, option });

  await openPage(page, rec, '/policies');
  await cam.focus('logonly', PROMPT_CARD, { pad: 16, kmax: 1.9 }, 'guard_prompt in log-only mode');
  await cam.hold(5000);
  await policyRows(page, cam, 'rows_before', 'guard_prompt_', 'the policies only record');
  await cam.hold(5000);
  await cam.focus('buttons', PROMPT_CARD, { pad: 16, kmax: 1.9 }, 'raise it to enforce');
  await cam.hold(3000);
  if (process.env.REHEARSE === '1') { rec.note('rehearsal_no_press'); await cam.hold(2000); return; }

  await press(page, rec, tap, page.locator(`${PROMPT_CARD} button[name=mode][value=active]`));
  rec.note('enforce_pressed');
  const frameJob = () => cam.focus('job', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job switches every agent\'s policy');
  await frameJob();
  const job = await waitForJob(page, rec, { timeoutMs: 240000, onLines: frameJob });
  rec.note(`job_${job.state}`);
  await cam.focus('job_done', '#panel-job', { pad: 16, kmax: 1.8 }, 'each agent reads ACTIVE');
  await cam.hold(7000);
  await cam.focus('enforced', PROMPT_CARD, { pad: 16, kmax: 1.9 }, 'guard_prompt reads enforce');
  await cam.hold(6000);
  await policyRows(page, cam, 'rows', 'guard_prompt_', 'the same policies now block');
  await cam.hold(6000);
}
