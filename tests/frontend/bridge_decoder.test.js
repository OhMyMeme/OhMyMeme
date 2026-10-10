import { describe, expect, it } from 'vitest'

// 现用设置窗口的唯一 decoder：直接从 settings-vue 的受控桥接导入，不再 vm 执行旧 decoder.js
import {
  decodeBridgeResult,
} from '../../src/ohmymeme/presentation/frontend/settings-vue/shared/bridge'

describe('settings bridge decoder', () => {
  it('preserves boolean and void method results', () => {
    expect(decodeBridgeResult('start_window_drag', true)).toBe(true)
    expect(decodeBridgeResult('refresh_memes', null)).toBeNull()
  })

  it('rejects malformed boolean results', () => {
    try {
      decodeBridgeResult('start_window_drag', { ok: true })
      throw new Error('malformed boolean was accepted')
    } catch (error) {
      expect(error.name).toBe('BridgeDecodeError')
    }
  })

  it('closes a malformed async result into null without throwing', async () => {
    await expect(
      decodeBridgeResult('check_connectivity', Promise.resolve('malformed')),
    ).resolves.toBeNull()
  })
})
