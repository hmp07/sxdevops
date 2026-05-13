<template>
  <div class="dashboard-page">
    <ObservabilityPostureHistory embedded />
  </div>
</template>

<script setup>
import ObservabilityPostureHistory from '@/views/ObservabilityPostureHistory.vue'
</script>

<style scoped>
.dashboard-page {
  min-height: 100%;
}
</style>
