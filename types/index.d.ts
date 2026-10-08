export type ReadAloud = { isOn: boolean }

declare module 'claude-code' {
  interface PluginState {
    'read-aloud': { isOn: boolean }
  }
}
