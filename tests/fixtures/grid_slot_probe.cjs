const fs = require('fs');
const path = require('path');
const vm = require('vm');
const typescript = require('typescript');

// 现用网格几何位于 gridInteraction.ts（纯函数、无 DOM/Vue/Bridge）：同源转译后在 vm 中执行，
// 不再从 useDragSort.ts 截取源码或用正则剥离类型标注；算法正确性由 Vitest 与同源探针共同覆盖。
const source = fs.readFileSync(
  path.resolve(
    __dirname,
    '..',
    '..',
    'src',
    'ohmymeme',
    'presentation',
    'frontend',
    'main',
    'features',
    'sorting',
    'gridInteraction.ts'
  ),
  'utf8'
);
const compiled = typescript.transpileModule(source, {
  compilerOptions: {
    module: typescript.ModuleKind.CommonJS,
    target: typescript.ScriptTarget.ES2020,
  },
}).outputText;

const sandbox = { exports: {}, module: { exports: {} } };
sandbox.module.exports = sandbox.exports;
vm.createContext(sandbox);
vm.runInContext(compiled, sandbox);
const { gridSlotIndex, slotOrigin, buildDropOrder } = sandbox.exports;
if (typeof gridSlotIndex !== 'function' || typeof slotOrigin !== 'function' || typeof buildDropOrder !== 'function') {
  throw new Error('grid interaction helpers not exported');
}

let checks = 0;

// 固定几何 fixture：卡宽 112 + 间隙 10 = 122，行距 150，4 列（与生产常量一致）
function geometry(overrides) {
  return Object.assign({ originX: 0, originY: 100, pitchX: 122, pitchY: 150, cols: 4 }, overrides || {});
}

function expectSlot(label, geo, x, y, total, expected) {
  const actual = gridSlotIndex(geo, x, y, total);
  checks += 1;
  if (actual !== expected) {
    throw new Error(label + ': expected slot ' + String(expected) + ', got ' + String(actual));
  }
}

// 侧栏/滚动偏移：originX/originY 是滚动后的内容原点，同一记录必须命中同一全局绝对槽位
const cases = [
  { label: 'expanded sidebar', geo: geometry({ originX: 200, originY: 100 }), x: 327, y: 255, expected: 5 },
  { label: 'collapsed sidebar', geo: geometry({ originX: 380, originY: 100 }), x: 507, y: 255, expected: 5 },
  { label: 'folder header margin', geo: geometry({ originX: 200, originY: 140 }), x: 327, y: 295, expected: 5 },
  { label: 'scrolled grid', geo: geometry({ originX: 200, originY: -200 }), x: 327, y: 255, expected: 13 },
];
for (const item of cases) {
  expectSlot(item.label, item.geo, item.x, item.y, 4000, item.expected);
}

// 非 0 全局起点：视口首行为第 100 行（lo=400）时给出全局槽位而不是局部 0，且不做 DOM 卡数钳制
const scrolled = geometry({ originX: 0, originY: 100 - 100 * 150 });
expectSlot('non-zero global start row', scrolled, 5, 125, 5000, 400);
expectSlot('non-zero global start next column', scrolled, 127, 125, 5000, 401);
expectSlot('non-zero global start beyond total', scrolled, 5, 125, 400, null);

// 末行空列与二维越界：总数 9（4 列）时第 2 行只有槽位 8
expectSlot('last row first column', geometry(), 5, 405, 9, 8);
expectSlot('last row empty column', geometry(), 127, 405, 9, null);
expectSlot('row beyond total', geometry(), 5, 555, 9, null);
expectSlot('above grid', geometry(), 5, 90, 9, null);
expectSlot('left of grid', geometry(), -5, 105, 9, null);
expectSlot('right of grid', geometry(), 490, 105, 9, null);
// 旧 head/tail clamp 改为 null：不再钳制到首项/末项
expectSlot('head clamp removed', geometry(), -1000, -1000, 9, null);
expectSlot('tail clamp removed', geometry(), 10000, 10000, 9, null);

// 坏几何显式拒绝（NaN/Infinity/0 步距/列数 0/总数 0/非有限指针），不得算错槽位
expectSlot('nan origin', geometry({ originX: NaN }), 5, 105, 9, null);
expectSlot('infinite pitch', geometry({ pitchX: Infinity }), 5, 105, 9, null);
expectSlot('zero pitch', geometry({ pitchY: 0 }), 5, 105, 9, null);
expectSlot('zero cols', geometry({ cols: 0 }), 5, 105, 9, null);
expectSlot('zero total', geometry(), 5, 105, 0, null);
expectSlot('nan pointer', geometry(), NaN, 105, 9, null);

// slotOrigin：第 n 行 m 列原点 = origin + pitch（scale 不进入数学，无 DOM 读取）
const origin = slotOrigin(geometry({ originX: 200, originY: 100 }), 6);
checks += 1;
if (!origin || origin.left !== 200 + 2 * 122 || origin.top !== 100 + 150) {
  throw new Error('slot origin: expected row/col pitch math, got ' + JSON.stringify(origin));
}

// buildDropOrder：非 0 起点下前→后，输入不被 splice；目标越界/源缺失显式拒绝
const items = [401, 402, 403, 404, 405].map(id => ({ id }));
const baseline = { start: 400, items };
const moved = buildDropOrder(baseline, 401, 403);
checks += 1;
if (!moved || JSON.stringify(moved.map(item => item.id)) !== JSON.stringify([402, 403, 404, 401, 405])) {
  throw new Error('drop order: unexpected result ' + JSON.stringify(moved && moved.map(item => item.id)));
}
if (JSON.stringify(items.map(item => item.id)) !== JSON.stringify([401, 402, 403, 404, 405])) {
  throw new Error('drop order: input array must not be spliced');
}
if (buildDropOrder(baseline, 401, 405) !== null || buildDropOrder(baseline, 999, 402) !== null) {
  throw new Error('drop order: invalid target/source must be rejected');
}

if (checks < 20) throw new Error('probe cases did not run');

console.log('grid slot behavior: PASS');
