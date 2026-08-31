const fs = require('fs');
const vm = require('vm');

let html = '';
process.stdin.resume();
process.stdin.setEncoding('utf8');
process.stdin.on('data', (d) => { html += d; });
process.stdin.on('end', () => {
  const textareaInner = (html.match(/<textarea id="renderData"[^>]*>([\s\S]*?)<\/textarea>/) || [])[1] || '';

  if (!textareaInner) {
    const dm = html.match(/acw_sc__v2\s*=\s*['"]([^'"]+)['"]/);
    if (dm) { console.log(dm[1]); return; }
    const dm2 = html.match(/acw_sc__v2=([^;'"\s&<]+)/);
    if (dm2) { console.log(dm2[1]); return; }
    console.log('NO_COOKIE');
    return;
  }

  let captured = '';
  const location = {
    href: 'https://accountmtapi.mobilelegends.com/',
    reload: () => {},
    get search() { return ''; }
  };
  const documentObj = {
    getElementById: (id) => {
      if (id === 'renderData') return { innerHTML: textareaInner };
      return null;
    },
    referrer: '',
    location: location,
    get cookie() { return captured; },
    set cookie(v) { captured = v; }
  };
  const sandbox = {
    document: documentObj,
    location: location,
    navigator: { userAgent: 'Mozilla/5.0' },
    console: console,
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    setInterval: setInterval,
    clearInterval: clearInterval,
    performance: { now: () => Date.now() },
    Date: Date,
    Math: Math,
    JSON: JSON,
    parseInt: parseInt,
    parseFloat: parseFloat,
    isNaN: isNaN,
    encodeURIComponent: encodeURIComponent,
    decodeURIComponent: decodeURIComponent,
    escape: escape,
    unescape: unescape,
    atob: atob,
    btoa: btoa,
  };
  sandbox.window = sandbox;
  sandbox.top = sandbox;
  sandbox.parent = sandbox;
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;

  const ctx = vm.createContext(sandbox);
  const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  try {
    for (const s of scripts) {
      try { vm.runInContext(s, ctx, { timeout: 10000 }); } catch (e) {}
    }
  } catch (e) {}
  const m = captured.match(/acw_sc__v2=([^;]+)/);
  console.log(m ? m[1] : 'NO_COOKIE');
});