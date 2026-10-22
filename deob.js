// Decode the string table of an obfuscated duck.ai jsa challenge.
// usage: node deob.js <challenge.js>
const fs = require('fs');
const vm = require('vm');

const src = fs.readFileSync(process.argv[2], 'utf8');

// 1) the array-rotation IIFE, 2) the two helper declarations it depends on.
const rot = src.match(/\(function\(_0x[0-9a-f]+,_0x[0-9a-f]+\)\{[\s\S]*?\}\(_0x[0-9a-f]+,0x[0-9a-f]+\)\);/);
const fArr = src.match(/function _0x[0-9a-f]+\(\)\{const _0x[0-9a-f]+=\[[\s\S]*?return _0x[0-9a-f]+\(\);\}/);
const fAcc = src.match(/function _0x[0-9a-f]+\(_0x[0-9a-f]+,_0x[0-9a-f]+\)\{const _0x[0-9a-f]+=_0x[0-9a-f]+\(\);[\s\S]*?return _0x[0-9a-f]+\([^)]*\);\}/);
if (!rot || !fArr || !fAcc) {
  console.error('could not locate obfuscation helpers');
  process.exit(1);
}
const accName = fAcc[0].match(/function (_0x[0-9a-f]+)\(/)[1];
const probe = `
  const __out = {};
  for (let i = 0x150; i < 0x1d0; i++) {
    try { const v = ${accName}(i); if (typeof v === 'string') __out['0x' + i.toString(16)] = v; } catch (e) {}
  }
  __out;
`;
const code = `(function(){${rot[0]}${fArr[0]}${fAcc[0]}\nreturn (function(){${probe}})();})()`;
const sandbox = {};
vm.createContext(sandbox);
const map = vm.runInContext(code, sandbox, { timeout: 10000 }) || {};
const used = [...new Set([...src.matchAll(new RegExp(accName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\((0x[0-9a-f]+)\\)', 'g'))].map((x) => x[1]))].sort();
const out = {};
for (const k of used) out[k] = map[k];
console.log(JSON.stringify(out, null, 1));
