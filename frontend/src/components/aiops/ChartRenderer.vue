<template>
  <div ref="chartDom" class="chart-container" :style="{ height: chartHeight }" />
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import echarts from '@/lib/echarts'

const props = defineProps({
  chartJson: { type: String, required: true },
})

const chartDom = ref(null)
let chartInstance = null

const chartHeight = computed(() => {
  try { return JSON.parse(props.chartJson).type === 'gauge' ? '220px' : '280px' }
  catch { return '280px' }
})

const CHART_COLORS = ['#5470C6', '#91CC75', '#FAC858', '#EE6666', '#73C0DE', '#3BA272', '#FC8452', '#9A60B4']

function buildBarOption(cfg) {
  return {
    title: { text: cfg.title || '', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: {},
    xAxis: { type: 'category', data: cfg.data?.categories || [] },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar',
      data: (cfg.data?.values || []).map((v, i) => ({
        value: v,
        itemStyle: { color: (cfg.colors || CHART_COLORS)[i] || CHART_COLORS[0] },
      })),
    }],
    grid: { top: 40, bottom: 30, left: 40, right: 20 },
  }
}

function buildLineOption(cfg) {
  return {
    title: { text: cfg.title || '', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: cfg.data?.categories || [], boundaryGap: false },
    yAxis: { type: 'value' },
    series: [{
      type: 'line',
      data: cfg.data?.values || [],
      smooth: true,
      lineStyle: { color: cfg.colors?.[0] || CHART_COLORS[0], width: 2 },
      areaStyle: { color: 'rgba(84,112,198,0.1)' },
    }],
    grid: { top: 40, bottom: 30, left: 50, right: 20 },
  }
}

function buildPieOption(cfg) {
  const data = (cfg.data?.categories || []).map((name, i) => ({
    name,
    value: (cfg.data?.values || [])[i] || 0,
  }))
  return {
    title: { text: cfg.title || '', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '55%'],
      data,
      label: { formatter: '{b}: {c}' },
      itemStyle: {
        color: (params) => (cfg.colors || CHART_COLORS)[params.dataIndex] || CHART_COLORS[0],
      },
    }],
  }
}

function buildGaugeOption(cfg) {
  const value = cfg.data?.value || 0
  let color = [[0.6, '#91CC75'], [0.8, '#FAC858'], [1, '#EE6666']]
  return {
    title: { text: cfg.title || '', left: 'center', textStyle: { fontSize: 14 } },
    series: [{
      type: 'gauge',
      startAngle: 210,
      endAngle: -30,
      center: ['50%', '60%'],
      radius: '90%',
      min: 0,
      max: 100,
      detail: { formatter: '{value}%', fontSize: 16 },
      data: [{ value, name: cfg.title || '' }],
      axisLine: { lineStyle: { color, width: 8 } },
    }],
  }
}

function parseAndBuildOption(jsonStr) {
  try {
    const cfg = JSON.parse(jsonStr)
    switch (cfg.type) {
      case 'bar': return buildBarOption(cfg)
      case 'line': return buildLineOption(cfg)
      case 'pie': return buildPieOption(cfg)
      case 'gauge': return buildGaugeOption(cfg)
      default: return null
    }
  } catch {
    return null
  }
}

onMounted(async () => {
  await nextTick()
  if (!chartDom.value) return
  const option = parseAndBuildOption(props.chartJson)
  if (!option) return
  chartInstance = echarts.init(chartDom.value)
  chartInstance.setOption(option)
})

onBeforeUnmount(() => {
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})
</script>

<style scoped>
.chart-container {
  width: 100%;
  min-width: 280px;
}
</style>
