// Radix Colors（dark）原生色阶 vendor（来自 @radix-ui/colors 3.0.0，值未修改）
// 只提供色阶变量；CSS/组件按 Radix 档位语义直接使用原生变量（--gray-*、--blue-9、--blue-a3 等），不做语义别名

export const grayDark = {
  1: '#111111',
  2: '#191919',
  3: '#222222',
  4: '#2a2a2a',
  5: '#313131',
  6: '#3a3a3a',
  7: '#484848',
  8: '#606060',
  9: '#6e6e6e',
  10: '#7b7b7b',
  11: '#b4b4b4',
  12: '#eeeeee',
} as const

export const grayAlphaDark = {
  1: '#00000000',
  2: '#ffffff09',
  3: '#ffffff12',
  4: '#ffffff1b',
  5: '#ffffff22',
  6: '#ffffff2c',
  7: '#ffffff3b',
  8: '#ffffff55',
  9: '#ffffff64',
  10: '#ffffff72',
  11: '#ffffffaf',
  12: '#ffffffed',
} as const

export const blueDark = {
  1: '#0d1520',
  2: '#111927',
  3: '#0d2847',
  4: '#003362',
  5: '#004074',
  6: '#104d87',
  7: '#205d9e',
  8: '#2870bd',
  9: '#0090ff',
  10: '#3b9eff',
  11: '#70b8ff',
  12: '#c2e6ff',
} as const

export const blueAlphaDark = {
  1: '#004df211',
  2: '#1166fb18',
  3: '#0077ff3a',
  4: '#0075ff57',
  5: '#0081fd6b',
  6: '#0f89fd7f',
  7: '#2a91fe98',
  8: '#3094feb9',
  9: '#0090ff',
  10: '#3b9eff',
  11: '#70b8ff',
  12: '#c2e6ff',
} as const

export const redDark = {
  1: '#191111',
  2: '#201314',
  3: '#3b1219',
  4: '#500f1c',
  5: '#611623',
  6: '#72232d',
  7: '#8c333a',
  8: '#b54548',
  9: '#e5484d',
  10: '#ec5d5e',
  11: '#ff9592',
  12: '#ffd1d9',
} as const

export const redAlphaDark = {
  1: '#f4121209',
  2: '#f22f3e11',
  3: '#ff173f2d',
  4: '#fe0a3b44',
  5: '#ff204756',
  6: '#ff3e5668',
  7: '#ff536184',
  8: '#ff5d61b0',
  9: '#fe4e54e4',
  10: '#ff6465eb',
  11: '#ff9592',
  12: '#ffd1d9',
} as const

export const greenDark = {
  1: '#0e1512',
  2: '#121b17',
  3: '#132d21',
  4: '#113b29',
  5: '#174933',
  6: '#20573e',
  7: '#28684a',
  8: '#2f7c57',
  9: '#30a46c',
  10: '#33b074',
  11: '#3dd68c',
  12: '#b1f1cb',
} as const

export const amberDark = {
  1: '#16120c',
  2: '#1d180f',
  3: '#302008',
  4: '#3f2700',
  5: '#4d3000',
  6: '#5c3d05',
  7: '#714f19',
  8: '#8f6424',
  9: '#ffc53d',
  10: '#ffd60a',
  11: '#ffca16',
  12: '#ffe7b3',
} as const

const cssVariables: Record<string, string> = {}

for (const [name, scale] of [
  ['gray', grayDark],
  ['blue', blueDark],
  ['red', redDark],
  ['green', greenDark],
  ['amber', amberDark],
] as const) {
  for (const [step, value] of Object.entries(scale)) {
    cssVariables[`--${name}-${step}`] = value
  }
}

for (const [name, scale] of [
  ['gray-a', grayAlphaDark],
  ['blue-a', blueAlphaDark],
  ['red-a', redAlphaDark],
] as const) {
  for (const [step, value] of Object.entries(scale)) {
    cssVariables[`--${name}${step}`] = value
  }
}

// 把 Radix 色阶注入 :root，供两窗口的 CSS 变量消费
export function applyDesignTokens(): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  for (const [name, value] of Object.entries(cssVariables)) {
    root.style.setProperty(name, value)
  }
}

applyDesignTokens()
