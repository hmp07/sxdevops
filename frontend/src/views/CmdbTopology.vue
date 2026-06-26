<template>
  <div class="cmdb-topology">
    <div class="page-hero">
      <div class="hero-left">
        <h1 class="hero-title">资源拓扑</h1>
        <p class="hero-desc">按业务线、环境、CI 类型查看配置项之间的关联关系</p>
      </div>
    </div>

    <CmdbTopologyPanel />
  </div>
</template>

<script setup>
import CmdbTopologyPanel from '@/components/cmdb/CmdbTopologyPanel.vue'
</script>
