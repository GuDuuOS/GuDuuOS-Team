/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

interface Window {
  readonly guduuDesktop?: Readonly<{
    isDesktop: true
    platform: 'darwin' | 'win32' | 'linux'
    arch: string
    electronVersion: string
  }>
}
