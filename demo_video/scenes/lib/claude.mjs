// Claude Code in the developer PC, driven like a person at the keyboard. What it prints is untrusted (another agent
// chooses the text of its questions): the storyboard only looks at the screen to know when to go on and where to point
// the camera, and answers a permission question with "1. Yes" (this one command) only when the question is in the
// layout Claude Code 2.1.330 prints, shown whole, and asks either to run a read-only shell command or to write a file
// whose absolute path is inside the agent's folder. Everything else gets No.
import { term } from './plugin.mjs';

const BUSY = 'esc to interrupt';
const WORK = '/home/dev/work';                       // the developer PC's working folder (run.sh up)
const AGENT_DIR = `${WORK}/dev_team/quality_agent/`; // the only folder a take lets Claude Code write in

// The permission dialog of Claude Code 2.1.330, as its rows show on the screen (the trailing spaces cut):
//   ─────────────            a rule
//    Bash command             the title (a file: " Create file", " Edit file")
//    Run shell command        one row (a file: the file's path)
//   ╌╌╌╌╌╌╌╌╌╌╌╌╌            a dashed rule
//    │ <command>              each row of the command behind the gutter (a file: its preview)
//   ╌╌╌╌╌╌╌╌╌╌╌╌╌            a dashed rule
//    <reason>                 none or a few rows, and blank rows
//    Do you want to proceed?  the question (a file: "Do you want to create <name>?")
//    ❯ 1. Yes                 the options, the marker on the highlighted one, "No" the last
//      2. No
//    Esc to cancel · Tab to amend      ("↑ 12 more lines" above it when the dialog does not fit: hidden rows)
const ASKS = 'Do you want to';
const QUESTION = /^ Do you want to (proceed|create (\S+)|make this edit to (\S+)|overwrite (\S+))\?$/;
const RULE = /^─{8,}$/;
const DASHED = /^╌{8,}$/;
const GUTTER = /^ │( |$)/;
const TITLES = { 'Bash command': 'shell', 'Create file': 'file', 'Edit file': 'file' };
const OPTION = /^ (❯ |  )(\d)\. (.+)$/;

export async function rows(page) { return (await term.screenText(page)).split('\n').map(r => r.replace(/\s+$/, '')); }

/** The row of the screen's question: the last row that asks ("Do you want to"), or -1. */
export function questionRow(r) {
  for (let k = r.length - 1; k >= 0; k--) if (r[k].includes(ASKS)) return k;
  return -1;
}

/** The dialog on the screen, read only in the layout above: { kind: 'shell' | 'file', top, end (its last option row),
 * question, title, detail (the row under the title), content (the rows between the dashed rules), options: [{n, text,
 * marked}] }, or { problem } when anything is not where the layout puts it. */
export function parseDialog(r) {
  const q = questionRow(r);
  if (q < 0) return { problem: 'no question' };
  if (!QUESTION.test(r[q])) return { problem: `a question row outside the layout: ${r[q].trim()}` };
  if (r.some(l => /^ ↑ \d+ more lines?$/.test(l))) return { problem: 'rows of the dialog are hidden' };
  const options = [];
  let end = q;
  for (let k = q + 1; k < r.length; k++) {
    const m = r[k].match(OPTION);
    if (m) { options.push({ n: Number(m[2]), text: m[3], marked: m[1] === '❯ ' }); end = k; }
    else if (options.length && /^ {6}\S/.test(r[k])) end = k;            // an option's text wrapped onto a second row
    else break;
  }
  if (!options.length || options[0].n !== 1 || options[0].text !== 'Yes' || !/^No\b/.test(options[options.length - 1].text)
      || options.some((o, i) => o.n !== i + 1) || options.filter(o => o.marked).length !== 1) {
    return { problem: 'the options are not 1. Yes … No with one marker' };
  }
  let closing = q - 1, reasons = 0;
  while (closing >= 0 && !DASHED.test(r[closing])) { if (r[closing].trim()) reasons++; closing--; }
  if (closing < 0 || reasons > 4) return { problem: 'no dashed rule above the question' };
  let open = closing - 1;
  while (open >= 0 && !DASHED.test(r[open])) open--;
  if (open < 3) return { problem: 'no dashed rule above the content' };
  const title = r[open - 2].trim();
  const kind = TITLES[title];
  if (!kind || !RULE.test(r[open - 3]) || !/^ \S/.test(r[open - 1])) return { problem: 'no title under a rule' };
  const content = r.slice(open + 1, closing);
  if (!content.length) return { problem: 'nothing between the dashed rules' };
  if (r.slice(open - 3, q).some(l => l.includes(ASKS))) return { problem: 'a row of the dialog asks a question' };
  const file = r[q].match(QUESTION).slice(2).find(Boolean);
  if ((kind === 'shell') !== !file) return { problem: `a ${kind} dialog with the question "${r[q].trim()}"` };
  return { kind, top: open - 3, end, question: r[q], title, detail: r[open - 1].trim(), content, options, file };
}

// ---------------------------------------------------------------------------------------------- a shell command

// a command whose first word is one of these only reads (the options that write are refused below)
const READERS = new Set(['cd', 'ls', 'cat', 'head', 'tail', 'grep', 'wc', 'cut', 'sort', 'diff', 'pwd', 'echo', 'find',
  'sed', 'tr', 'basename', 'dirname', 'stat']);

/** A path an argument names, made absolute and normal, or null when it cannot be: a relative path is taken from the
 * working folder, and any ".." or "~" is refused (Claude Code's shell may stand in another folder after a cd). */
function placed(word) {
  if (word.startsWith('~') || word.split('/').includes('..')) return null;
  const parts = (word.startsWith('/') ? word : `${WORK}/${word}`).split('/').filter(s => s && s !== '.');
  return '/' + parts.join('/');
}
const insideWork = word => { const p = placed(word); return !!p && (p === WORK || p.startsWith(WORK + '/')); };

/** The simple commands of a shell text as [{ words: [{text, quoted}] }], or null for anything not parsed: command or
 * process substitution, backticks, $, a backslash, braces, parentheses, an input redirect or a here-document, a
 * comment, a background job, an assignment before a command, a redirect other than to /dev/null (or 2>&1). */
export function simpleCommands(text) {
  const commands = [];
  let words = [], word = null;
  const endWord = () => { if (word) words.push(word); word = null; };
  const endCommand = () => { endWord(); if (words.length) commands.push({ words }); words = []; };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "'") {
      const j = text.indexOf("'", i + 1);
      if (j < 0) return null;
      word = { text: (word ? word.text : '') + text.slice(i + 1, j), quoted: true };
      i = j;
    } else if (c === '"') {
      const j = text.indexOf('"', i + 1);
      if (j < 0) return null;
      const inner = text.slice(i + 1, j);
      if (/[$`\\]/.test(inner)) return null;
      word = { text: (word ? word.text : '') + inner, quoted: true };
      i = j;
    } else if (c === ' ' || c === '\t') {
      endWord();
    } else if (c === '\n' || c === ';') {
      endCommand();
    } else if (c === '|') {
      if (text[i + 1] === '|') i++;
      endCommand();
    } else if (c === '&') {
      if (text[i + 1] === '&') { i++; endCommand(); }
      else if (text[i + 1] === '>') {                                  // &>/dev/null
        endWord();
        const m = text.slice(i + 2).match(/^\s*(\S+)/);
        if (!m || m[1].replace(/[;|&].*$/, '') !== '/dev/null') return null;
        i += 2 + m[0].indexOf('/dev/null') + '/dev/null'.length - 1;
      } else return null;                                                // a background job
    } else if (c === '>') {
      if (word && !/^[12]$/.test(word.text)) return null;                // 2>x glued to a word that is not a descriptor
      word = null;
      const rest = text.slice(i + 1);
      if (/^&[12]/.test(rest)) { i += 2; continue; }                     // 2>&1
      const m = rest.match(/^ *\/dev\/null(?=$|[\s;|&])/);
      if (!m) return null;                                               // >>, >|, or any other target
      i += m[0].length;
    } else if ('$`\\{}()<#!'.includes(c) && !(c === '#' && word)) {
      return null;
    } else {
      word = { text: (word ? word.text : '') + c, quoted: word ? word.quoted : false };
    }
  }
  endCommand();
  return commands;
}

/** Whether one simple command only reads files inside the working folder. */
function readsOnly({ words }) {
  const [name, ...args] = words.map(w => w.text);
  if (!READERS.has(name) || words[0].quoted || name.includes('=')) return false;
  if (name === 'cd') return args.length === 1 && !args[0].startsWith('-') && insideWork(args[0]);
  if (name === 'sort' && args.some(a => /^(-[^-]*o|--output)/.test(a))) return false;
  if (name === 'find' && args.some(a => /^-(exec|execdir|ok|okdir|delete|fprint|fprint0|fprintf|fls)$/.test(a))) return false;
  if (name === 'sed') {
    const scripts = args.filter(a => !a.startsWith('-'));
    if (!args.includes('-n') || args.some(a => a.startsWith('-') && a !== '-n') || !/^\d+(,\d+)?p$/.test(scripts[0] || '')) return false;
  }
  // every argument that names a path, quoted or not, stays inside the working folder (echo's words are text); an
  // option that holds a path (--file=/x, -f/x) is refused
  if (name === 'echo') return true;
  return args.every(a => (a.startsWith('-') ? !/[/~]/.test(a) : !/[/~]|^\.\.?$/.test(a) || insideWork(a)));
}

/** Whether a shell command, given as the rows the dialog showed, only reads: every simple command starts with a
 * reading command, under both readings of a row break (the end of a command, or a long command wrapped). */
export function readOnly(commandRows) {
  return [commandRows.join('\n'), commandRows.join(' ')].every(text => {
    const commands = simpleCommands(text);
    return !!commands && commands.length > 0 && commands.every(readsOnly);
  });
}

// ------------------------------------------------------------------------------------------------------ a file

/** Whether a file question may be answered Yes: its path, shown whole and absolute (or under ~), normal, inside the
 * agent's folder, not a Claude Code folder, MCP list or instructions file, and the file the question names. A
 * relative path is shown relative to Claude Code's folder, which follows its cd: it cannot be placed, so it is a No. */
function fileIsTheAgents(d) {
  const shown = d.detail;
  if (!/^(\/|~\/)/.test(shown) || /\s/.test(shown) || shown.split('/').includes('..')) return false;
  const path = shown.startsWith('~/') ? '/home/dev/' + shown.slice(2) : shown;
  const p = placed(path);
  return !!p && p.startsWith(AGENT_DIR) && p.split('/').pop() === d.file
    && !p.split('/').some(s => s === '.claude' || s === '.mcp.json' || s === 'CLAUDE.md');
}

/** The answer to the dialog on the screen: 'yes' only for a dialog in the known layout, shown whole, with the marker on
 * "1. Yes", asking to run a read-only shell command or to write a file inside the agent's folder; else 'no'. */
export function verdict(r) {
  const d = parseDialog(r);
  if (d.problem || !d.options[0].marked) return 'no';
  if (d.kind === 'shell') {
    if (d.content.some(l => !GUTTER.test(l))) return 'no';
    return readOnly(d.content.map(l => l.replace(GUTTER, ''))) ? 'yes' : 'no';
  }
  return fileIsTheAgents(d) ? 'yes' : 'no';
}

/** Whether two screens show the very same dialog (the same rows from its rule to its last option). */
export function sameDialog(a, b) {
  const da = parseDialog(a), db = parseDialog(b);
  if (da.problem || db.problem) return false;
  return a.slice(da.top, da.end + 1).join('\n') === b.slice(db.top, db.end + 1).join('\n');
}

/** Start Claude Code from the shell and wait for its input prompt. */
export async function startClaude(page) {
  await term.type(page, 'claude', 60);
  await page.waitForTimeout(400);
  await page.keyboard.press('Enter');
  if (!(await term.waitPrompt(page, 30000))) throw new Error('Claude Code did not show its prompt within 30 s');
  await page.waitForTimeout(1500);
}

/** Send one request (pasted: Korean survives) and follow Claude Code until it is done. Every screen not seen before
 * is kept for the take's text check (cam.keep). Each permission question is framed, held, and answered by verdict():
 * for a Yes the screen is read again just before the key, and Enter is pressed only when the same dialog is there with
 * the marker on "1. Yes"; otherwise Escape (No) and the take stops with one line. A No is Escape, then `noRun` is
 * typed as the reason. Returns { prompts: [{ question, answer }], seconds }. */
export async function request(page, rec, cam, text, { noRun, limitMs = 600000, idleMs = 3000 } = {}) {
  await term.paste(page, text);
  await page.waitForTimeout(1200);
  await page.keyboard.press('Enter');
  const t0 = Date.now();
  const prompts = [];
  const seen = new Set();
  const look = async () => {
    const r = await rows(page);
    const screen = r.join('\n');
    if (!seen.has(screen)) { seen.add(screen); cam.keep(screen); }
    return r;
  };
  let busy = false, lastBusy = 0;
  while (Date.now() - t0 < limitMs) {
    const r = await look();
    const q = questionRow(r);
    if (q >= 0) {
      const answer = verdict(r);
      const d = parseDialog(r);
      rec.note('permission', { answer });
      const [first, last] = d.problem ? [Math.max(0, q - 10), Math.min(r.length - 1, q + 4)] : [d.top, d.end];
      await cam.lines(`ask${prompts.length + 1}`, first, last, { pad: 24, kmax: 1.5 }, `permission question ${prompts.length + 1}`);
      await cam.hold(4500);
      if (answer === 'yes') {
        const again = await look();
        if (!sameDialog(r, again) || verdict(again) !== 'yes') {
          await page.keyboard.press('Escape');
          const now = questionRow(again) >= 0 ? again[questionRow(again)].trim() : 'no question';
          const marked = again.find(l => l.startsWith(' ❯ ')) || '';
          throw new Error(`the question changed before the answer: now "${now}", marked "${marked.trim()}"`);
        }
        await page.keyboard.press('Enter');            // the marked option, checked above: 1. Yes
      } else {
        await page.keyboard.press('Escape');
        await page.waitForTimeout(1500);
        if (noRun) { await term.paste(page, noRun); await page.waitForTimeout(800); await page.keyboard.press('Enter'); }
      }
      prompts.push({ question: r[q].trim(), answer });
      await page.waitForTimeout(1500);
      await cam.reset(`work${prompts.length}`);
      busy = true; lastBusy = Date.now();
      continue;
    }
    if (r.join('\n').includes(BUSY)) { busy = true; lastBusy = Date.now(); }
    else if (busy && Date.now() - lastBusy >= idleMs) return { prompts, seconds: (Date.now() - t0) / 1000 };
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
