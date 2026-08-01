/* 在主样式加载前恢复主题，独立文件让 Portal 可以启用不含 unsafe-inline 的脚本 CSP。 */
try {
  if (localStorage.getItem("nexus_portal_theme") !== "dark") {
    document.documentElement.dataset.theme = "light";
  }
} catch (error) {
  document.documentElement.dataset.theme = "light";
}
