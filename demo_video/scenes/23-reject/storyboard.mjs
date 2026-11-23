// 23-reject (stage 2): the platform engineer opens quality_agent's failed review: the step that failed (Scan), the
// scan's finding lines (the vulnerable package and its advisories), and rejects the submission with a reason. The
// job's lines and the record reading REJECTED. Changes the hub (one press). With REHEARSE=1 in the environment the
// take does everything but the press.
import { openPage, press, waitForJob } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, tap, option }) {
  await needState({ records: { quality_agent: 'PENDING_APPROVAL', release_review: 'APPROVED' }, reviewing: [],
    stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  const rehearse = process.env.REHEARSE === '1';

  await openPage(page, rec, '/reviews/quality_agent');
  await cam.reset('wide', 'quality_agent: its review failed');
  await cam.hold(5000);
  await cam.focus('failed', '#panel-steps', { pad: 12, kmax: 1.7 }, 'the review stopped at Scan');
  await cam.hold(6000);
  await cam.focus('findings', '#panel-findings', { pad: 16, kmax: 2.0 }, 'the vulnerable package the scan found');
  await cam.hold(8000);

  // the reason, typed into the form (Korean text through the field's value and an input event)
  const reason = page.locator('#panel-reject textarea[name=reason]');
  await reason.evaluate((el, text) => { el.value = text; el.dispatchEvent(new Event('input', { bubbles: true })); }, t.reject);
  rec.note('reason');
  await cam.focus('reason', '#panel-reject', { pad: 16, kmax: 2.0 }, 'the reason for the developer');
  await cam.hold(6000);
  if (rehearse) { rec.note('rehearsal_no_press'); await cam.hold(2000); return; }

  await press(page, rec, tap, page.locator('#panel-reject button.danger'));
  rec.note('reject_pressed');
  await cam.focus('job', '#panel-job', { pad: 16, kmax: 1.8 }, 'the reject job runs');
  const job = await waitForJob(page, rec, { timeoutMs: 120000 });
  rec.note(`job_${job.state}`);
  await cam.focus('job_done', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job\'s lines');
  await cam.hold(7000);
  await cam.focus('rejected', '#panel-application .app-facts', { pad: 16, kmax: 2.0 }, 'the record reads REJECTED');
  await cam.hold(6000);
}
