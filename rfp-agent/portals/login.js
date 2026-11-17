// Browser login for portals behind JavaScript sign-in or single sign-on.
//
//   node portals/login.js <KEY> [startUrl]
//
// Reads <KEY>_USERNAME, <KEY>_PASSWORD and optional <KEY>_TOTP_SECRET from the environment.
// Never prints, logs or screenshots a value. On success it saves the browser session to
// runs/sessions/<KEY>.json (gitignored, container only, never uploaded) so later steps in the
// same run can reuse it, and prints LOGGED_IN. Any CAPTCHA, push or SMS approval, terms page
// or lockout warning prints STOPPED and exits 3: the run reports it and never works around it.
const fs = require('fs');
const path = require('path');
const { totp } = require('./totp');
const { chromium } = require('playwright');

const START = {
  LOGINGOV: 'https://secure.login.gov',
  CANADABUYS: 'https://canadabuys.canada.ca',
  BONFIRE: 'https://bonfirehub.com/login',
  OPENGOV: 'https://procurement.opengov.com/login',
  NYC_PASSPORT: 'https://passport.cityofnewyork.us',
  GOVTRIBE: 'https://govtribe.com/login',
  ONTARIO: 'https://ontariotenders.app.jaggaer.com',
  BCBID: 'https://bcbid.gov.bc.ca',
  ALBERTA_APC: 'https://purchasing.alberta.ca',
  SASKTENDERS: 'https://sasktenders.ca',
  OREGONBUYS: 'https://oregonbuys.gov',
  LABAVN: 'https://www.labavn.org',
  DEMANDSTAR: 'https://www.demandstar.com',
};
const STOP = /captcha|recaptcha|hcaptcha|are you a robot|verify you are human|account (is )?locked|too many (failed )?attempts|approve (the )?sign.?in|push notification|text message|we sent a (code|text)/i;

async function firstVisible(page, selectors) {
  for (const s of selectors) {
    const el = page.locator(s).first();
    if (await el.count() && await el.isVisible().catch(() => false)) return el;
  }
  return null;
}

async function stopCheck(page) {
  const text = (await page.content()).slice(0, 400000);
  if (STOP.test(text) || await page.locator('iframe[src*="captcha"]').count()) return true;
  return false;
}

async function clickSubmit(page) {
  const b = await firstVisible(page, ['button[type=submit]', 'input[type=submit]',
    'button:has-text("Sign in")', 'button:has-text("Log in")', 'button:has-text("Login")',
    'button:has-text("Continue")', 'button:has-text("Next")', 'button:has-text("Submit")']);
  if (b) await b.click(); else await page.keyboard.press('Enter');
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
}

(async () => {
  const key = (process.argv[2] || '').toUpperCase();
  const user = process.env[`${key}_USERNAME`], pass = process.env[`${key}_PASSWORD`], seed = process.env[`${key}_TOTP_SECRET`];
  if (!key) { console.log('usage: login.js KEY [startUrl]'); process.exit(2); }
  if (!user || !pass) { console.log(`${key}: MISSING_CREDENTIALS (set ${key}_USERNAME and ${key}_PASSWORD)`); process.exit(4); }
  const start = process.argv[3] || START[key];
  if (!start) { console.log(`${key}: ERROR (no start URL known; pass one)`); process.exit(2); }
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  try {
    await page.goto(start, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    // Some sites show a "Sign in" link before the form.
    if (!await firstVisible(page, ['input[type=password]', 'input[type=email]', 'input[autocomplete=username]'])) {
      const link = await firstVisible(page, ['a:has-text("Sign in")', 'a:has-text("Log in")', 'a:has-text("Login")', 'button:has-text("Sign in")', 'button:has-text("Log in")']);
      if (link) { await link.click(); await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {}); }
    }
    if (await stopCheck(page)) { console.log(`${key}: STOPPED (challenge before login)`); process.exit(3); }
    const userSel = ['input[autocomplete=username]', 'input[type=email]', 'input[name*=email i]', 'input[name*=user i]', 'input[id*=user i]', 'input[type=text]'];
    let u = await firstVisible(page, userSel);
    if (!u) { console.log(`${key}: ERROR (no username field found at ${page.url().split('?')[0]})`); process.exit(5); }
    await u.fill(user);
    let p = await firstVisible(page, ['input[type=password]']);
    if (!p) { await clickSubmit(page); p = await firstVisible(page, ['input[type=password]']); }  // two-step sign-in
    if (!p) { console.log(`${key}: ERROR (no password field found)`); process.exit(5); }
    await p.fill(pass);
    await clickSubmit(page);
    if (await stopCheck(page)) { console.log(`${key}: STOPPED (CAPTCHA, approval prompt or lockout after password)`); process.exit(3); }
    const code = await firstVisible(page, ['input[autocomplete=one-time-code]', 'input[name*=code i]', 'input[name*=otp i]', 'input[id*=code i]']);
    if (code) {
      if (!seed) { console.log(`${key}: STOPPED (asks for a one-time code and ${key}_TOTP_SECRET is not set)`); process.exit(3); }
      await code.fill(totp(seed));
      await clickSubmit(page);
      if (await stopCheck(page)) { console.log(`${key}: STOPPED (challenge after one-time code)`); process.exit(3); }
    }
    const stillLogin = await firstVisible(page, ['input[type=password]']);
    const loggedIn = !stillLogin && /sign out|log out|logout|my account|dashboard/i.test(await page.content());
    if (!loggedIn) { console.log(`${key}: FAILED (no logged-in marker; landed on ${page.url().split('?')[0]})`); process.exit(1); }
    const dir = path.join(__dirname, '..', 'runs', 'sessions');
    fs.mkdirSync(dir, { recursive: true });
    await ctx.storageState({ path: path.join(dir, `${key}.json`) });
    console.log(`${key}: LOGGED_IN (session saved for this run only)`);
  } catch (e) {
    console.log(`${key}: ERROR (${e.name})`);
    process.exit(1);
  } finally {
    await browser.close();
  }
})();

