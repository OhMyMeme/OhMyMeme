// Vite 处理 CSS 资源导入；此处只为独立设置窗口入口声明默认导出，避免类型检查把 CSS 当成缺失模块
declare module '*.css' {
  const content: string
  export default content
}
