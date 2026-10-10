import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderInput } from 'claude-code'

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

// The button itself, the same wherever it's drawn.
async function control($: EngineInterface, e: RenderInput<'SessionMode' | 'AbovePrompt'>) {
  const { Box, Button, Svg } = $.ui.resolve(e)
  const voice = await read($, isOn)
  const toggle = async () => {
    const flag = `${await $.env.get('HOME')}/.claude/read-aloud/on/${await $.session.id()}`
    await $.fs.write(flag, voice ? 'off' : 'on')
    await update($, isOn, () => !voice)
  }
  const label = voice ? 'Voice on' : 'Voice off'
  return (
    <Box key="voice-row" flexDirection="row" alignItems="center">
      {e.surface !== 'terminal' && Svg && <Svg source={icon(voice)} alt={label} width={14} height={14} />}
      <Button key="voice" label={label} plain dimColor onPress={() => void toggle()} />
    </Box>
  )
}

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

  // Terminal: in the prompt footer's right-hand mode area, after any mode labels (`focus`).
  on('ui.render', { component: 'SessionMode' }, async ($, e, next) => {
    const base = await next(e)
    if (e.surface !== 'terminal') return base
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="row" alignItems="center">
        {base}
        <Box marginLeft={1}>{await control($, e)}</Box>
      </Box>
    )
  })

  // Desktop and other surfaces: the footer slots aren't on screen there, so the button sits in
  // the band just above the prompt, at its right edge, beside whatever other mods draw there.
  // It gives way to a survey.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const base = await next(e)
    if (e.surface === 'terminal' || e.props.hasSurvey) return base
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="row" alignItems="center">
        <Box flexGrow={1}>{base}</Box>
        {await control($, e)}
      </Box>
    )
  })
}
