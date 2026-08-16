const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.resolve(__dirname, '..', '..', 'src', 'webui', 'index.js'),
  'utf8'
);
const start = source.indexOf('function memeCardsInGrid()');
const end = source.indexOf('function moveInArray(', start);
if (start < 0 || end < 0) throw new Error('drag geometry helpers not found');

const meme = () => ({
  offsetWidth: 100,
  offsetHeight: 80,
  classList: { contains: () => false },
});
const memes = [meme(), meme(), meme(), meme(), meme()];
const allCards = memes;
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
  getBoundingClientRect: () => ({ left: layout.left, top: layout.top }),
};
const context = {
  document: {
    getElementById: id => {
      if (id !== 'meme-grid') throw new Error('unexpected element id: ' + id);
      return grid;
    },
    querySelectorAll: () => allCards,
  },
  getComputedStyle: () => style,
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

function assertSlot(label, x, y, expected) {
  const actual = context.gridSlotIndex(x, y);
  if (actual !== expected) {
    throw new Error(label + ': expected meme index ' + expected + ', got ' + actual);
  }
}

function assertVisibleSlots(label) {
  const originX = layout.left + 10;
  const originY = layout.top + 10;
  assertSlot(label + ' second meme on first row', originX + 110 + 50, originY + 40, 1);
  assertSlot(label + ' fourth meme on next row', originX + 50, originY + 100 + 40, 3);
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
const metrics = context.gridMetrics();
if (!Object.values(metrics).every(Number.isFinite)) {
  throw new Error('malformed styles must produce finite grid metrics');
}

console.log('grid slot behavior: PASS');
