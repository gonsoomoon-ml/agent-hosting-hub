// Terminal takes: the developer PC (ttyd on 127.0.0.1:7681, prompt "개발자 $") and the user's shell (127.0.0.1:7682,
// prompt "사용자 $"). The prompt says who types.
import { term } from './plugin.mjs';

export const TERMINAL = { dev: 'http://127.0.0.1:7681', user: 'http://127.0.0.1:7682' };

/** The last row of the screen that holds text. */
export async function lastRow(page) {
  const rows = (await term.screenText(page)).split('\n').filter(r => r.trim());
  return rows.length ? rows[rows.length - 1] : '';
}

/** Wait until the shell is back at its prompt (the last row is the prompt alone); false on a timeout. */
export async function idle(page, prompt, timeoutMs = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if ((await lastRow(page)).trim() === prompt) return true;
    await page.waitForTimeout(300);
  }
  console.warn(`idle: no '${prompt}' prompt after ${timeoutMs} ms`);
  return false;
}

/** Open the terminal of `who` (dev or user) at 28 px and 100 columns, wait for its prompt, clear it, put the camera in.
 * `check`: a shell test run before the screen is cleared (before the first shot, so it is cut from every clip); the take
 * stops when it does not print `ready`. */
export async function openShell(page, rec, who, t, { check } = {}) {
  await term.openTerminal(page, TERMINAL[who], { fontSize: 28, cols: 100 });
  if (!(await idle(page, t.prompt[who], 20000))) throw new Error(`the ${who} terminal shows no '${t.prompt[who]}' prompt`);
  if (check) {
    await term.run(page, `if ${check}; then echo ready; else echo not-ready; fi`);
    await idle(page, t.prompt[who], 15000);
    const rows = (await term.screenText(page)).split('\n').map(r => r.trim());
    if (!rows.includes('ready')) throw new Error(`the ${who} terminal is not ready for this take: ${check}`);
  }
  await term.run(page, 'clear');
  await idle(page, t.prompt[who], 5000);
  await rec.install();
}

/** Type one command like a person (ASCII), then Enter. */
export async function command(page, line) {
  await term.type(page, line, 45);
  await page.waitForTimeout(500);
  await page.keyboard.press('Enter');
}

/** Wait for a text on the screen; a timeout stops the take with one line. */
export async function need(page, text, timeoutMs, what) {
  if (!(await term.waitFor(page, text, timeoutMs))) throw new Error(`${what}: '${text}' did not show within ${timeoutMs / 1000} s`);
}
