<template>
  <section class="event-tabs-shell">
    <button
      v-for="item in tabs"
      :key="item.path"
      type="button"
      class="event-tab"
      :class="{ active: route.path === item.path }"
      @click="go(item.path)"
    >
      <span>{{ item.title }}</span>
      <em>{{ item.desc }}</em>
    </button>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const tabs = computed(() => [
  { path: '/events/wall', title: '事件墙', desc: '故障窗口与变更定位', permission: 'eventwall.view' },
  { path: '/events/sources', title: '事件源', desc: '内置采集与外部接入', permission: 'eventwall.source.view' },
].filter(item => authStore.hasPermission(item.permission)))

function go(path) {
  if (route.path !== path) {
    router.push({ path, query: { ...route.query } })
  }
}
</script>

<style scoped>
.event-tabs-shell {
  display: inline-flex;
  width: fit-content;
  max-width: 100%;
  gap: 2px;
  padding: 3px;
  border: 1px solid #dee0e3;
  border-radius: 8px;
  background: #fff;
}

.event-tab {
  min-width: 168px;
  padding: 8px 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #4e5969;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  text-align: left;
  cursor: pointer;
}

.event-tab:hover {
  background: #f7f8fa;
}

.event-tab.active {
  background: #e8f0ff;
  color: #245bdb;
}

.event-tab span {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.2;
}

.event-tab em {
  font-size: 12px;
  font-style: normal;
  color: #8f959e;
  line-height: 1.3;
}

.event-tab.active em {
  color: #245bdb;
}

@media (max-width: 700px) {
  .event-tabs-shell {
    width: 100%;
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .event-tab {
    min-width: 0;
  }
}
</style>
