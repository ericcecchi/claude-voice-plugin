import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

// The read-aloud hook (scripts/read-aloud.py) speaks only when
// ~/.claude/read-aloud/on/<session id> holds "on". `/read-aloud` and this toggle both write it.
const isOn = atom({ plugin: 'read-aloud', key: 'isOn' } as const, false)

// Lucide's volume-2 / volume-x, the stroke icon set the Claude UI draws with.
const SPEAKER =
  '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/>'
const WAVES = '<path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>'
const CROSS = '<path d="M22 9l-6 6"/><path d="M16 9l6 6"/>'
const icon = (on: boolean) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#8b8b86" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${SPEAKER}${on ? WAVES : CROSS}</svg>`

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    const flag = `${await $.env.get('HOME')}/.claude/read-aloud/on/${await $.session.id()}`
    const sync = async () => {
      const now = (await $.fs.exists(flag)) && (await $.fs.read(flag)).trim() !== 'off'
      if (now !== (await read($, isOn))) await update($, isOn, () => now)
    }
    await sync()
    $.clock.every(1000, () => void sync())
    return result
  })

  // Drawn in the prompt footer's right-hand mode area, beside the model selector, after any
  // mode labels the engine shows there (`focus`, `memory paused`).
  on('ui.render', { component: 'SessionMode' }, async ($, e, next) => {
    const base = await next(e)
    const { Box, Button } = $.ui.resolve(e)
    const voice = await read($, isOn)
    const toggle = async () => {
      const flag = `${await $.env.get('HOME')}/.claude/read-aloud/on/${await $.session.id()}`
      await $.fs.write(flag, voice ? 'off' : 'on')
      await update($, isOn, () => !voice)
    }
    const label = voice ? 'Voice on' : 'Voice off'
    const Svg = e.surface === 'terminal' ? undefined : $.ui.resolve(e).Svg
    return (
      <Box flexDirection="row" alignItems="center">
        {base}
        <Box key="voice-row" flexDirection="row" alignItems="center" marginLeft={1}>
          {Svg && <Svg source={icon(voice)} alt={label} width={14} height={14} />}
          <Button key="voice" label={label} plain dimColor onPress={() => void toggle()} />
        </Box>
      </Box>
    )
  })
}
