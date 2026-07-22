<template>
  <div class="stream">
    <template v-for="(day, di) in days" :key="di">
      <div class="day-sep">{{ day.daySep }}</div>
      <MessageItem v-for="m in day.messages" :key="m.id" :msg="m" />
    </template>
  </div>
</template>

<script setup lang="ts">
import type { DayMessages } from '@/types/message'
import MessageItem from './MessageItem.vue'

defineProps<{ days: DayMessages[] }>()
</script>
