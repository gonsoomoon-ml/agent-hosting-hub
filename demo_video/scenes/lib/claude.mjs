// Claude Code in the developer PC, driven like a person at the keyboard. What it prints is untrusted: the storyboard
// only looks at the screen to know when to go on and where to point the camera, and answers a permission question
// with "1. Yes" (this one command) only for a file in the agent's folder or a shell command that runs no code and
// writes nowhere else; anything else (running code, publishing, writing elsewhere) gets No.
import { term } from './plugin.mjs';

const DIALOG = /Do you want to (proceed|make this edit|create|overwrite)/;
const BUSY = 'esc to interrupt';
// a question about a command that starts any of these is answered No: the takes make files only
const NEVER = /(^|[;&|(]\s*|\b(then|do|exec|xargs)\s+)(python3?|pytest|uv|pip3?|publish|node|npm|npx|bash|sh|curl|aws)\b/;

export async function rows(page) { return (await term.screenText(page)).split('\n'); }

/** Start Claude Code from the shell and wait for its input prompt. */
export async function startClaude(page) {
  await term.type(page, 'claude', 60);
  await page.waitForTimeout(400);
  await page.keyboard.press('Enter');
  if (!(await term.waitPrompt(page, 30000))) throw new Error('Claude Code did not show its prompt within 30 s');
  await page.waitForTimeout(1500);
}

/** The rows of the permission dialog on the screen: [first, last] indexes, or null. */
function dialogRows(r) {
  const ask = r.findIndex(l => DIALOG.test(l));
  if (ask < 0) return null;
  let first = -1;
  for (let k = ask - 1; k >= 0 && k >= ask - 16; k--) { if (/Bash command|Edit file|Create file|Write file|Read file/.test(r[k])) { first = k; break; } }
  if (first < 0) { for (let k = ask - 1; k >= 0 && k >= ask - 16; k--) { if (/^\s*[─━]{8,}/.test(r[k])) { first = k; break; } } }
  if (first < 0) first = Math.max(0, ask - 8);
  if (first > 0 && /^\s*[─━]{8,}/.test(r[first - 1])) first -= 1;
  let last = ask;
  for (let k = ask + 1; k < r.length && k <= ask + 6; k++) { if (/^\s*(❯\s*)?\d\.\s/.test(r[k])) last = k; }
  return [first, last];
}

// quoted text (a grep pattern, an echo's words) is an argument, not a command: blanked before a line is read
const unquote = line => line.replace(/'[^']*'|"[^"]*"/g, "''");

/** Whether the command a dialog asks about would run code or publish (any line of it, any part of a compound). */
export function runsCode(lines) { return lines.some(l => NEVER.test(unquote(l).trim())); }

// the only place a take lets Claude Code write: the agent it is making (shown relative to Claude Code's folder, which
// may be the checkout or dev_team/ after a cd)
const AGENT_PATH = /^(\.\/)?(dev_team\/)?quality_agent(\/[\w.-]+)?\/?$/;
const WRITERS = /^(mkdir|touch|tee|rm|rmdir|mv|ln|chmod|chown|truncate|dd|install|cp)$/;

/** Whether every path a shell command writes is in the agent's folder: redirect targets, the arguments of commands
 * that make, move or remove files (cp: its destination), and no sed -i or rm at all. */
export function writesOnlyTheAgent(lines) {
  const text = lines.map(unquote).join('\n');
  if (/\bsed\s+(-\w*\s+)*-i/.test(text) || /(^|[;&|\s])rm\s/.test(text)) return false;
  for (const m of text.matchAll(/>{1,2}\s*([^\s;&|<>]+)/g)) {
    const target = m[1].replace(/^["']|["']$/g, '');
    if (target !== '/dev/null' && !AGENT_PATH.test(target)) return false;
  }
  for (const part of text.split(/&&|\|\||[;|\n]/)) {
    const words = part.trim().split(/\s+/).filter(Boolean);
    if (!words.length || !WRITERS.test(words[0])) continue;
    const args = words.slice(1).filter(w => !w.startsWith('-')).map(w => w.replace(/^["']|["']$/g, ''));
    const targets = words[0] === 'cp' ? args.slice(-1) : args;
    if (!targets.length || !targets.every(a => AGENT_PATH.test(a))) return false;
  }
  return true;
}

// a row of a shell command that begins with one of these is a command of its own; any other row goes on from the one
// above (the dialog wraps a long command at word boundaries)
const STARTER = /^(cat|ls|echo|printf|cd|grep|sed|awk|for|do|done|then|else|fi|if|while|find|head|tail|wc|sort|diff|test|mkdir|cp|mv|rm|rmdir|ln|chmod|chown|touch|tee|truncate|dd|install|python3?|uv|pip3?|pytest|publish|node|npm|npx|bash|sh|curl|aws|xargs|exec)\b/;

/** The command's own lines from the dialog's rows: a wrapped row is joined back to the row above it. */
export function unwrap(rows) {
  const out = [];
  for (const row of rows) {
    if (out.length && row.trim() && !STARTER.test(row.trim())) out[out.length - 1] += ' ' + row.trim();
    else out.push(row);
  }
  return out;
}

// the files of an agent made from the template: a file question whose path scrolled off the screen (a long preview)
// is judged by the file name in the question itself
const AGENT_FILES = new Set(['agent.json', 'agent.py', 'requirements.txt', 'main.py', 'hub_tools.py', 'README.md']);
const TITLE = /^\s*(Bash command|Create file|Edit file|Write file)\s*$/;

/** The answer to the dialog whose question is on row `ask` of the screen `r`: yes only for a file inside the agent's
 * folder, or for a shell command that runs no code and writes nowhere else and is shown whole (no "↑ N more lines"). */
export function verdict(r, ask) {
  let title = -1;
  for (let k = ask - 1; k >= 0; k--) { if (TITLE.test(r[k])) { title = k; break; } }
  const file = r[ask].match(/Do you want to (?:create|make this edit to|overwrite) (.+?)\?/);
  if (file) {
    if (title >= 0 && !/Bash/.test(r[title])) {
      const path = (r[title + 1] || '').trim();
      return AGENT_PATH.test(path) && !/\.claude|\.mcp\.json|CLAUDE\.md/.test(path) ? 'yes' : 'no';
    }
    return AGENT_FILES.has(file[1].trim()) ? 'yes' : 'no';
  }
  if (title < 0 || r.some(l => /↑ \d+ more lines/.test(l))) return 'no';
  const lines = unwrap(r.slice(title + 1, ask));
  return !runsCode(lines) && writesOnlyTheAgent(lines) ? 'yes' : 'no';
}

/** Send one request (pasted: Korean survives) and follow Claude Code until it is done. Each permission question is
 * framed, held and answered by verdict(): option 1 (Yes, this one command), or No (then `noRun` is typed as the
 * reason). Returns { prompts: [{command, answer}], seconds }. */
export async function request(page, rec, cam, text, { noRun, limitMs = 600000 } = {}) {
  await term.paste(page, text);
  await page.waitForTimeout(1200);
  await page.keyboard.press('Enter');
  const t0 = Date.now();
  const prompts = [];
  let busy = false, lastBusy = 0;
  while (Date.now() - t0 < limitMs) {
    const r = await rows(page);
    const screen = r.join('\n');
    const d = dialogRows(r);
    if (d) {
      const command = r.slice(d[0], d[1] + 1).join('\n');
      const no = verdict(r, r.findIndex(l => DIALOG.test(l))) === 'no';
      rec.note('permission', { answer: no ? 'no' : 'yes' });
      await cam.lines(`ask${prompts.length + 1}`, d[0], d[1], { pad: 24, kmax: 1.5 }, `permission question ${prompts.length + 1}`);
      await cam.hold(4500);
      if (no) {
        await page.keyboard.press('Escape');
        await page.waitForTimeout(1500);
        if (noRun) { await term.paste(page, noRun); await page.waitForTimeout(800); await page.keyboard.press('Enter'); }
      } else {
        await page.keyboard.press('Enter');            // the highlighted option: 1. Yes
      }
      prompts.push({ command, answer: no ? 'no' : 'yes' });
      await page.waitForTimeout(1500);
      await cam.reset(`work${prompts.length}`);
      busy = true; lastBusy = Date.now();
      continue;
    }
    if (screen.includes(BUSY)) { busy = true; lastBusy = Date.now(); }
    else if (busy && Date.now() - lastBusy > 3000) return { prompts, seconds: (Date.now() - t0) / 1000 };
    await page.waitForTimeout(400);
  }
  throw new Error(`Claude Code did not finish within ${limitMs / 1000} s`);
}

/** The rows of Claude Code's last answer: from the row of the request (or a marker) to the row above its input box. */
export function answerRows(r, fromNeedle) {
  let box = r.length - 1;
  for (let k = r.length - 1; k >= 0; k--) { if (r[k].includes('❯')) { box = k; break; } }
  let end = box - 1;
  while (end > 0 && (/^\s*[─━]+\s*$/.test(r[end]) || !r[end].trim())) end--;
  let start = -1;
  for (let k = end; k >= 0; k--) { if (r[k].includes(fromNeedle)) { start = k; break; } }
  return start < 0 ? null : [start, end];
}
