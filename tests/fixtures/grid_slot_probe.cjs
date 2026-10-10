const fs = require('fs');
const path = require('path');
const vm = require('vm');

// 现用主窗口拖拽几何在 useDragSort.ts：提取 gridMetrics/gridSlotIndex（TS 类型标注剥离后）在本地 DOM 桩上执行。
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
    'useDragSort.ts'
  ),
  'utf8'
);
const start = source.indexOf('function gridMetrics(');
const end = source.indexOf('function moveInArray(', start);
if (start < 0 || end < 0) throw new Error('drag geometry helpers not found');

const geometry = source
  .slice(start, end)
  .replace(/:\s*(?:HTMLElement|number|string|boolean|GridMetrics(?:\s*\|\s*null)?)/g, '');

const meme = () => ({ offsetWidth: 100, offsetHeight: 80 });
const memes = [meme(), meme(), meme(), meme(), meme()];
const layout = { left: 200, top: 100 };
const style = {
  paddingLeft: '10px',
  paddingRight: '10px',
  paddingTop: '10px',
  columnGap: '10px',
  rowGap: '20px',
};
const grid = {
  clientLeft: 0,
  clientTop: 0,
  clientWidth: 340,
  querySelectorAll: () => memes,
  getBoundingClientRect: () => ({ left: layout.left, top: layout.top }),
};

const context = { getComputedStyle: () => style };
vm.createContext(context);
vm.runInContext(geometry + '\nglobalThis.gridMetrics = gridMetrics; globalThis.gridSlotIndex = gridSlotIndex;', context);

function assertSlot(label, x, y, expected) {
  const actual = context.gridSlotIndex(grid, x, y);
  if (actual !== expected) {
    throw new Error(label + ': expected meme index ' + expected + ', got ' + actual);
  }
}

function assertVisibleSlots(label) {
  const originX = layout.left + 10;
  const originY = layout.top + 10;
  assertSlot(label + ' first slot', originX + 5, originY + 5, 0);
  assertSlot(label + ' second column', originX + 115, originY + 5, 1);
  assertSlot(label + ' third column', originX + 225, originY + 5, 2);
  assertSlot(label + ' second row first column', originX + 5, originY + 105, 3);
  assertSlot(label + ' second row second column', originX + 115, originY + 105, 4);
}

assertVisibleSlots('expanded sidebar');
layout.left = 20;
assertVisibleSlots('collapsed sidebar');
layout.top = -90;
assertVisibleSlots('scrolled grid');
assertSlot('head clamp', -1000, -1000, 0);
assertSlot('tail clamp', 10000, 10000, 4);

style.paddingLeft = undefined;
style.paddingRight = 'not-a-number';
style.paddingTop = 'Infinity';
style.columnGap = 'Infinity';
style.rowGap = 'NaN';
const metrics = context.gridMetrics(grid);
if (!Object.values(metrics).every(Number.isFinite)) {
  throw new Error('malformed styles must produce finite grid metrics');
}

console.log('grid slot behavior: PASS');
