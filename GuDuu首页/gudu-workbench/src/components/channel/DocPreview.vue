<template>
  <div>
    <div class="doc">
      <div class="dt">{{ data.title }}</div>
      <div class="ds">{{ data.subtitle }}</div>

      <template v-for="(section, i) in data.sections" :key="i">
        <h4>{{ section.title }}</h4>
        <p v-if="section.body" v-html="section.body" />
        <table v-if="section.table" class="tbl">
          <thead>
            <tr>
              <th v-for="(h, hi) in section.table.headers" :key="hi">{{ h }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, ri) in section.table.rows" :key="ri">
              <td
                v-for="(cell, ci) in row"
                :key="ci"
                :style="isStyled(cell) ? `color:${cell.color}` : undefined"
              >
                {{ isStyled(cell) ? cell.text : cell }}
              </td>
            </tr>
          </tbody>
        </table>
      </template>

      <div v-if="data.footer" class="doc-foot">{{ data.footer }}</div>
    </div>

    <div
      v-if="data.actions && data.actions.length"
      style="margin-top: 10px; display: flex; gap: 8px"
    >
      <button
        v-for="(a, i) in data.actions"
        :key="i"
        class="btn"
        :class="{ primary: a.primary }"
        @click="onAction(a.label)"
      >
        {{ a.label }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { DocPreviewData, Sender } from '@/types/message'
import { useCardAction } from '@/composables/useCardAction'

const props = defineProps<{ data: DocPreviewData; sender?: Sender }>()
const { runAction } = useCardAction()

function onAction(label: string) {
  runAction(label, {
    tag: '文档',
    title: props.data.title,
    meta: props.data.subtitle,
    variant: 'info',
    sender: props.sender
  })
}

type Cell = string | { text: string; color?: string }
function isStyled(c: Cell): c is { text: string; color?: string } {
  return typeof c === 'object'
}
</script>
