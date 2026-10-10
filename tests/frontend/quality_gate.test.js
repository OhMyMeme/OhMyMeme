import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { NPagination } from 'naive-ui'

import Pager from '../../src/ohmymeme/presentation/frontend/main/features/memes/Pager.vue'

describe('Pager', () => {
  it('emits the next page when the pagination advances', async () => {
    const wrapper = mount(Pager, {
      props: { page: 3, pageCount: 8 },
    })

    wrapper.findComponent(NPagination).vm.$emit('update:page', 4)
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('go')).toEqual([[4]])
  })

  it('stays hidden when there is a single page', () => {
    const wrapper = mount(Pager, {
      props: { page: 1, pageCount: 1 },
    })

    expect(wrapper.find('.pager').exists()).toBe(false)
  })
})
