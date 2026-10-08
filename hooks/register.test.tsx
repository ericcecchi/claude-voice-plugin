import { test, expect, mock } from 'claude-code/testing'

const FLAG = '/home/.claude/read-aloud/on/s1'

test('the voice toggle under the prompt shows the state and toggles the flag', async ($, on) => {
  const files: Record<string, string> = {}
  mock.env(on, { HOME: '/home' })
  mock.clock(on)
  on('ui.render', ($, e) => { const { Text } = $.ui.resolve(e); return <Text dimColor>? for shortcuts</Text> })
  on('session.id', () => ({ value: 's1' }))
  on('fs.exists', ($, e) => ({ value: e.path in files }))
  on('fs.read', ($, e) => ({ value: files[e.path] ?? '' }))
  on('fs.write', ($, e) => { files[e.path] = e.text; return { value: undefined } })
  for (const surface of ['terminal', 'desktop'] as const) {
    delete files[FLAG]
    const ui = await $.ui.mount({ plugin: 'read-aloud', surface, component: 'PromptHint', props: { isDraft: false, isWorking: false, hint: '? for shortcuts' } } as never)
    expect((await ui.find({ key: 'voice' }))?.props.label).toBe('Voice off')
    await ui.press({ key: 'voice' })
    expect(files[FLAG]).toBe('on')
    expect((await ui.find({ key: 'voice' }))?.props.label).toBe('Voice on')
    await ui.press({ key: 'voice' })
    expect(files[FLAG]).toBe('off')
    await ui.unmount()
  }
})
