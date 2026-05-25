<template>
  <div class="fade-in task-page-shell">
    <section class="hero panel task-hero-panel">
      <div class="hero-copy">
        <div class="hero-title-row">
          <span class="hero-icon hero-icon-operation"><el-icon><Operation /></el-icon></span>
          <h2>任务工作台</h2>
          <p class="page-inline-desc">集中处理任务下发、AIOps 建议联动、模板复用与执行回溯，提供更直接的控制台操作入口。</p>
        </div>
      </div>
    </section>

    <CmdbHostTaskCenter
      :resource-tree="resourceTree"
      :resource-loading="loading"
      :on-reload-resources="reloadResourceTree"
    />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Operation } from '@element-plus/icons-vue'
import CmdbHostTaskCenter from '@/components/cmdb/CmdbHostTaskCenter.vue'
import { getTaskResourceTree } from '@/api/modules/ops'

const loading = ref(false)
const resourceTree = ref([])

function normalizeTree(list = []) {
  return list.map((env) => ({
    ...env,
    treeKey: `environment:${env.id}`,
    children: (env.children || []).map((system) => ({
      ...system,
      treeKey: `system:${system.id}`,
      children: [],
    })),
  }))
}

async function reloadResourceTree() {
  loading.value = true
  try {
    const tree = await getTaskResourceTree()
    resourceTree.value = normalizeTree(tree || [])
  } finally {
    loading.value = false
  }
}

onMounted(reloadResourceTree)
</script>

<style scoped>
.task-page-shell {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hero.panel.task-hero-panel {
  align-items: center;
  background: linear-gradient(180deg, #ffffff 0%, #fcfdff 100%);
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 12px;
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.04);
  display: flex;
  justify-content: space-between;
  padding: 10px 14px;
}

.hero-copy {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.hero-title-row {
  align-items: baseline;
  display: flex;
  gap: 10px;
}

.hero-title-row h2 {
  color: #0f172a;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.1;
  margin: 0;
}

.page-inline-desc {
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
  margin: 0;
}

.hero-icon {
  align-items: center;
  border-radius: 16px;
  color: #fff;
  display: inline-flex;
  font-size: 20px;
  height: 36px;
  justify-content: center;
  width: 36px;
}

.hero-icon-operation {
  background: linear-gradient(135deg, #5b7cf7, #8b5cf6);
}

.panel {
  background: #fff;
  border: 1px solid #eff0f2;
  border-radius: 16px;
  box-shadow: 0 8px 24px rgba(31, 35, 41, 0.06);
  padding: 12px 14px;
}

@media (max-width: 760px) {
  .hero.panel.task-hero-panel {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
