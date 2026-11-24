// 54-stop (stage 5): the platform engineer stops quality_agent on the agents page: its row, the press, the job's lines
// (its entry blocked on the agent gateway, its sessions ended), the row reading stopped while the other agents run.
// Changes the hub (one press). With REHEARSE=1 in the environment the take does everything but the press.
import { openPage, press, waitForJob } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

const ROW = '#agent-quality_agent';

export default async function storyboard({ page, rec, tap, option }) {
  await needState({ records: { quality_agent: 'APPROVED', release_review: 'APPROVED', docs_adk: 'APPROVED' },
    reviewing: [], stopped: [] });
  texts(option);
  const cam = kit({ page, rec, option });

  await openPage(page, rec, '/agents');
  await cam.focus('alarm', '#panel-alarm', { pad: 16, kmax: 1.5 }, 'the alarm is on');
  await cam.hold(5000);
  await cam.focus('agents', '#panel-agents', { pad: 16, kmax: 1.5 }, 'stop only quality_agent');
  await cam.hold(4000);
  await cam.focus('row', ROW, { pad: 24, kmax: 1.6 }, 'quality_agent is running');
  await cam.hold(4000);
  if (process.env.REHEARSE === '1') { rec.note('rehearsal_no_press'); await cam.hold(2000); return; }

  await press(page, rec, tap, page.locator(`${ROW} form[action$="/stop"] button`));
  rec.note('stop_pressed');
  const frameJob = () => cam.focus('job', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job blocks its entry and ends its sessions');
  await frameJob();
  const job = await waitForJob(page, rec, { timeoutMs: 180000, onLines: frameJob });
  rec.note(`job_${job.state}`);
  await cam.focus('job_done', '#panel-job', { pad: 16, kmax: 1.8 }, 'the job\'s lines');
  await cam.hold(8000);
  await cam.focus('stopped', '#panel-agents', { pad: 16, kmax: 1.5 }, 'quality_agent is stopped, the others run');
  await cam.hold(7000);
}
