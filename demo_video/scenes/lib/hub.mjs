// The hub screen (make ui, 127.0.0.1:8300). Every button is a form POST answered with 303 to a page, and the page
// reloads itself once when a job ends: each load throws the camera away, so these helpers put it back.
export const HUB = 'http://127.0.0.1:8300';

/** Open a page of the hub screen and put the camera in. */
export async function openPage(page, rec, path, settleMs = 1500) {
  await page.goto(HUB + path, { waitUntil: 'load' });
  await page.waitForSelector('#main');
  await page.waitForTimeout(settleMs);
  await rec.install();
}

/** Press a button (tap: no scroll) and land on the page the 303 points to, with the camera back. */
export async function press(page, rec, tap, locator) {
  await Promise.all([page.waitForNavigation({ waitUntil: 'load', timeout: 30000 }), tap(locator)]);
  await page.waitForSelector('#main');
  await page.waitForTimeout(800);
  await rec.install();
}

/** Whether a job the page shows has ended, as the page draws it. The page follows a job only when it was drawn
 * running (base.html's script), and then reloads once when the job ends: so a page first drawn running has ended only
 * after that reload and in a finished state; a page first drawn finished follows nothing and no reload will come.
 * first: the job panel's state on the first look after the press ('' when there was none); state: now. */
export function jobEnded({ first, state, reloaded }) {
  if (!first) return false;
  if (first !== 'running') return true;
  return reloaded && !!state && state !== 'running';
}

/** After a press that started a job: wait until the job has ended as jobEnded() says, putting the camera back after
 * the page's one reload. Returns the job's state (done, failed) and its lines. onLines(lines) is called when the
 * job's lines change while it runs (to re-frame the panel). */
export async function waitForJob(page, rec, { timeoutMs = 300000, onLines } = {}) {
  const t0 = Date.now();
  let first = '', reloaded = false, lines = '';
  while (Date.now() - t0 < timeoutMs) {
    let s;
    try {
      s = await page.evaluate(() => {
        const p = document.getElementById('panel-job');
        return { cam: !!window.__cam, state: p ? p.dataset.state : '', lines: p ? p.querySelector('.lines').textContent : '' };
      });
    } catch {
      await page.waitForLoadState('load').catch(() => {});
      continue;
    }
    if (!s.cam) {
      await page.waitForSelector('#main');
      await page.waitForTimeout(600);
      await rec.install();
      reloaded = true;
      continue;
    }
    if (!first) first = s.state;
    if (jobEnded({ first, state: s.state, reloaded })) return { state: s.state, lines: s.lines };
    if (s.lines !== lines) { lines = s.lines; if (onLines) await onLines(lines); }
    await page.waitForTimeout(300);
  }
  throw new Error(`the job did not end within ${timeoutMs / 1000} s`);
}

/** The steps of a review's strip: [{name, state}] (state: waiting, running, passed, failed, skipped). */
export async function strip(page, scope) {
  return page.evaluate(sel => [...document.querySelectorAll(`${sel} ol.steps li.step`)].map(li => ({
    name: li.querySelector('.name').textContent.trim(),
    state: ['waiting', 'running', 'passed', 'failed', 'skipped'].find(c => li.classList.contains(c)) || '',
  })), scope);
}

/** The record status and the latest review's status of an agent's card on /reviews (or of /reviews/<agent>). */
export async function pills(page, scope) {
  return page.evaluate(sel => [...document.querySelectorAll(`${sel} .pill`)].map(p => p.textContent.trim()), scope);
}
