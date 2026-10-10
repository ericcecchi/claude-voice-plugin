import { test, expect, mock } from 'claude-code/testing'

const FLAG = '/home/.claude/read-aloud/on/s1'
const SITES = {
  terminal: { component: 'SessionMode', props: { modes: [] } },
  desktop: { component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 80 } },
} as const

test('the voice toggle shows the state and toggles the flag where each surface shows it', async ($, on) => {
  const files: Record<string, string> = {}
  mock.env(on, { HOME: '/home' })
  mock.clock(on)
  on('ui.render', ($, e) => { const { Text } = $.ui.resolve(e); return <Text dimColor>focus</Text> })
  on('session.id', () => ({ value: 's1' }))
  on('fs.exists', ($, e) => ({ value: e.path in files }))
  on('fs.read', ($, e) => ({ value: files[e.path] ?? '' }))
  on('fs.write', ($, e) => { files[e.path] = e.text; return { value: undefined } })
  for (const surface of ['terminal', 'desktop'] as const) {
    delete files[FLAG]
    const ui = await $.ui.mount({ plugin: 'read-aloud', surface, ...SITES[surface] } as never)
    expect((await ui.find({ key: 'voice' }))?.props.label).toBe('Voice off')
    await ui.press({ key: 'voice' })
    expect(files[FLAG]).toBe('on')
    expect((await ui.find({ key: 'voice' }))?.props.label).toBe('Voice on')
    await ui.press({ key: 'voice' })
    expect(files[FLAG]).toBe('off')
    await ui.unmount()
  }
})

test('on desktop the footer slot stays as it was, and a survey takes the band', async ($, on) => {
  mock.env(on, { HOME: '/home' })
  mock.clock(on)
  on('ui.render', ($, e) => { const { Text } = $.ui.resolve(e); return <Text dimColor>focus</Text> })
  on('session.id', () => ({ value: 's1' }))
  on('fs.exists', () => ({ value: false }))
  const footer = await $.ui.mount({ plugin: 'read-aloud', surface: 'desktop', component: 'SessionMode', props: { modes: [] } } as never)
  expect(await footer.find({ key: 'voice' })).toBeUndefined()
  await footer.unmount()
  const band = await $.ui.mount({ plugin: 'read-aloud', surface: 'desktop', component: 'AbovePrompt', props: { ...SITES.desktop.props, hasSurvey: true } } as never)
  expect(await band.find({ key: 'voice' })).toBeUndefined()
  await band.unmount()
})

test('on desktop the band keeps what other mods draw there', async ($, on) => {
  mock.env(on, { HOME: '/home' })
  mock.clock(on)
  on('ui.render', ($, e) => { const { Button } = $.ui.resolve(e); return <Button key="other" label="Other mod" onPress={() => {}} /> })
  on('session.id', () => ({ value: 's1' }))
  on('fs.exists', () => ({ value: false }))
  const band = await $.ui.mount({ plugin: 'read-aloud', surface: 'desktop', ...SITES.desktop } as never)
  expect(await band.find({ key: 'other' })).toBeDefined()
  expect(await band.find({ key: 'voice' })).toBeDefined()
  await band.unmount()
})
