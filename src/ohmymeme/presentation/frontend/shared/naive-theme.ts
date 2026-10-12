import type { GlobalThemeOverrides } from 'naive-ui'
import { blueDark, grayDark, redDark } from './tokens'

// Naive 组件映射到 Radix 档位：实心 9（hover 10）、文字 11/12、组件底 2/3、边框 6
export const naiveThemeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: blueDark[9],
    primaryColorHover: blueDark[10],
    primaryColorPressed: blueDark[10],
    primaryColorSuppl: blueDark[9],
    errorColor: redDark[9],
    errorColorHover: redDark[10],
    errorColorPressed: redDark[10],
    bodyColor: grayDark[1],
    cardColor: grayDark[2],
    modalColor: grayDark[2],
    popoverColor: grayDark[3],
    tableColor: grayDark[2],
    inputColor: grayDark[1],
    textColorBase: grayDark[12],
    textColor1: grayDark[12],
    textColor2: grayDark[12],
    textColor3: grayDark[11],
    borderColor: grayDark[6],
    dividerColor: grayDark[6],
  },
  Button: {
    colorPrimary: blueDark[9],
    colorHoverPrimary: blueDark[10],
    colorPressedPrimary: blueDark[10],
    colorFocusPrimary: blueDark[9],
    textColorPrimary: '#ffffff',
  },
  Input: {
    color: grayDark[1],
    colorFocus: grayDark[1],
    border: `1px solid ${grayDark[6]}`,
    borderHover: `1px solid ${blueDark[9]}`,
    borderFocus: `1px solid ${blueDark[9]}`,
  },
}
