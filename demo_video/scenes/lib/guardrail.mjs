// The two requests of the custom guardrail's scenes (43-before, 45-after), typed the same way and framed the same way
// in both takes: a request that names the company's code name, and an inspection question whose answer holds the
// inspector's employee ID (synthetic data of the sample tools).
import { command, idle } from './shell.mjs';

export const CODE_NAME = 'ask quality_agent "Summarise the schedule of Project Falcon for part P-100."';
export const INSPECTION = 'ask quality_agent "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"';

/** Type one of the two requests, wait for the prompt, check the answer with `expect(screen)` (a sentence when it is
 * not what the take needs), note it, and frame the command and its answer. */
export async function asked(page, rec, cam, t, line, key, label, expect) {
  await command(page, line);
  rec.note(`asked_${key}`);
  if (!(await idle(page, t.prompt.user, 200000))) throw new Error(`${line} did not end`);
  const wrong = await expect();
  if (wrong) throw new Error(`${key}: ${wrong}`);
  rec.note(`answered_${key}`);
  await cam.rows(key, line.slice(0, 40), t.prompt.user, { kmax: 1.4 }, label);
  await cam.hold(8000);
}
