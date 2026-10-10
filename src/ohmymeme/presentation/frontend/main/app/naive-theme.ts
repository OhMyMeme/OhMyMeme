import type { GlobalThemeOverrides } from 'naive-ui'

// 把现有 style.css 的设计 token 映射为 Naive UI 深色主题覆写，保持原有观感
const primary = '#3b82f6'
const primaryStrong = '#1d4ed8'
const danger = '#ef4444'
const bg = '#0d0d0f'
const surface = '#1a1a1f'
const surface2 = '#222228'
const fg = '#e2e8f0'
const fgSecondary = '#94a3b8'
const border = '#2a2a32'

export const naiveThemeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: primary,
    primaryColorHover: primary,
    primaryColorPressed: primaryStrong,
    primaryColorSuppl: primaryStrong,
    errorColor: danger,
    errorColorHover: danger,
    errorColorPressed: '#dc2626',
    bodyColor: bg,
    cardColor: surface,
    modalColor: surface,
    popoverColor: surface2,
    tableColor: surface,
    inputColor: bg,
    textColorBase: fg,
    textColor1: fg,
    textColor2: fg,
    textColor3: fgSecondary,
    borderColor: border,
    dividerColor: border,
    borderRadius: '8px',
    borderRadiusSmall: '4px',
    fontSize: '13px',
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
  },
  Button: {
    borderRadiusMedium: '6px',
  },
  Input: {
    color: bg,
    colorFocus: bg,
    border: `1px solid ${border}`,
    borderHover: `1px solid ${primary}`,
    borderFocus: `1px solid ${primary}`,
  },
}
