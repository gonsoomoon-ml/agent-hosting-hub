// 44-attach (stage 4): the platform engineer attaches the custom guardrail (the interceptor Lambda) to the agent
// gateway on the policy page: the guardrail's panel (detached), the press, the job's lines, the panel reading attached
// with its points. Changes the hub (one press); the guardrail stays attached for stage 5. With REHEARSE=1 in the
// environment the take does everything but the press.
import { openPage, press, waitForJob } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, tap, option }) {
  await needState({ records: { quality_agent: 'APPROVED' }, reviewing: [], mode: 'ACTIVE', attached: false, stopped: [] });
  texts(option);
  const cam = kit({ page, rec, option });

  await openPage(page, rec, '/policies');
  await cam.reset('wide', 'the company policies and the custom guardrail');
  await cam.hold(4000);
  await cam.focus('detached', '#panel-guardrail', { pad: 16, kmax: 1.9 }, 'the custom guardrail is detached');
  await cam.hold(6000);
  if (process.env.REHEARSE === '1') { rec.note('rehearsal_no_press'); await cam.hold(2000); return; }

  await press(page, rec, tap, page.locator('#panel-guardrail form[action="/guardrail/attach"] button'));
  rec.note('attach_pressed');
  const frameJob = () => cam.focus('job', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job attaches the interceptor');
  await frameJob();
  const job = await waitForJob(page, rec, { timeoutMs: 120000, onLines: frameJob });
  rec.note(`job_${job.state}`);
  await cam.focus('job_done', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job\'s lines');
  await cam.hold(7000);
  await cam.focus('attached', '#panel-guardrail', { pad: 16, kmax: 1.9 }, 'the custom guardrail is attached');
  await cam.hold(7000);
}
