<template>
  <div class="auth-page">
    <div class="auth-shell">
      <section class="auth-overview">
        <div class="brand-row">
          <div class="brand-mark">
            <img src="@/assets/brand-mark.svg" alt="SxDevOps" class="brand-mark-image" />
          </div>
          <div class="brand-text">SxDevOps · AI Agent</div>
        </div>

        <div class="overview-content">
          <h1>统一运维智能体平台，让团队协同更高效</h1>
          <p class="overview-summary">
            覆盖 CMDB、多云、可观测、工单、容器与中间件、AIOps，帮助团队在一个平台内完成日常运维协同。
          </p>

          <div class="overview-actions">
            <router-link class="promo-link" to="/ai-agent-promo">
              查看 AI Agent 产品介绍
            </router-link>
          </div>

          <div class="feature-grid">
            <article v-for="item in features" :key="item.title" class="feature-card">
              <div class="feature-icon">
                <el-icon><component :is="item.icon" /></el-icon>
              </div>
              <div class="feature-body">
                <div class="feature-title">{{ item.title }}</div>
                <div class="feature-desc">{{ item.desc }}</div>
              </div>
            </article>
          </div>
        </div>
      </section>

      <section class="auth-panel">
        <div class="auth-panel-inner">
          <h2>登录</h2>
          <p class="auth-subtitle">进入工作台</p>

          <el-form :model="form" label-position="top" @submit.prevent="handleLogin">
            <el-form-item label="用户名">
              <el-input v-model="form.username" size="large" placeholder="请输入用户名" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" size="large" type="password" show-password placeholder="请输入密码" />
            </el-form-item>
            <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="handleLogin">
              进入工作台
            </el-button>
          </el-form>

          <div class="auth-tip">默认账号：demo / Demo#123</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DataBoard, Cloudy, TrendCharts, Promotion, Box, Service } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const loading = ref(false)
const form = reactive({
  username: 'demo',
  password: 'Demo#123',
})

const features = [
  {
    title: 'AIOps',
    desc: '以运维智能体串联告警、资源与变更上下文，辅助定位、处置与闭环审计。',
    icon: Service,
  },
  {
    title: 'CMDB',
    desc: '统一沉淀资产、应用与关系模型，建立基础设施全景视图，打造问题溯源与成本分析底座。',
    icon: DataBoard,
  },
  {
    title: '可观测性',
    desc: '贯通指标、日志与链路数据，帮助团队更快发现并定位异常。',
    icon: TrendCharts,
  },
  {
    title: '多云管理',
    desc: '集中纳管多云资源与环境配置，提升跨平台交付与治理效率。',
    icon: Cloudy,
  },
  {
    title: '工单系统',
    desc: '支持应用发布、SQL审计、事务工单、审批流配置，打造可回溯的变更闭环',
    icon: Promotion,
  },
  {
    title: '容器与中间件',
    desc: '统一运维 K8s、容器服务与中间件组件，降低平台协同复杂度。',
    icon: Box,
  },
]

async function handleLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }

  loading.value = true
  try {
    await authStore.login(form)
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/dashboard')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  height: 100vh;
  display: grid;
  place-items: center;
  padding: 16px;
  overflow: hidden;
  background:
    radial-gradient(circle at top, rgba(96, 165, 250, 0.09), transparent 26%),
    linear-gradient(180deg, #f6f8fc 0%, #edf2f8 100%);
}

.auth-shell {
  width: min(1220px, 100%);
  height: min(720px, calc(100vh - 32px));
  display: grid;
  grid-template-columns: 1.16fr 0.84fr;
  border-radius: 28px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(203, 213, 225, 0.8);
  box-shadow: 0 26px 70px rgba(15, 23, 42, 0.14);
}

.auth-overview {
  position: relative;
  padding: 34px 40px 30px;
  background:
    linear-gradient(rgba(125, 177, 250, 0.065) 1px, transparent 1px),
    linear-gradient(90deg, rgba(125, 177, 250, 0.065) 1px, transparent 1px),
    linear-gradient(180deg, #f9fbff 0%, #f2f6fc 100%);
  background-size: 28px 28px, 28px 28px, auto;
}

.auth-overview::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 1px;
  height: 100%;
  background: linear-gradient(180deg, transparent, rgba(226, 232, 240, 0.9), transparent);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-mark {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
}

.brand-mark-image {
  width: 52px;
  height: 52px;
  display: block;
}

.brand-text {
  display: inline-block;
  font-size: 20px;
  font-weight: 800;
  letter-spacing: -0.02em;
  background: var(--brand-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.overview-content {
  max-width: 568px;
  margin: 52px auto 0;
}

.auth-overview h1 {
  margin: 0;
  color: #2a313c;
  font-size: 30px;
  font-weight: 700;
  line-height: 1.35;
  letter-spacing: -0.02em;
}

.overview-summary {
  margin: 14px 0 0;
  color: #7a8595;
  font-size: 13px;
  line-height: 1.75;
  white-space: nowrap;
}

.overview-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 18px;
}

.promo-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 18px;
  border: 1px solid rgba(59, 130, 246, 0.24);
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.98) 0%, rgba(255, 247, 237, 0.92) 100%);
  color: #2563eb;
  font-size: 13px;
  font-weight: 800;
  text-decoration: none;
  box-shadow: 0 12px 24px rgba(59, 130, 246, 0.1);
  transition: all 0.2s ease;
}

.promo-link:hover {
  transform: translateY(-1px);
  border-color: rgba(59, 130, 246, 0.36);
  box-shadow: 0 16px 28px rgba(59, 130, 246, 0.14);
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 20px;
}

.feature-card {
  min-height: 112px;
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  gap: 12px;
  padding: 16px;
  border-radius: 18px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.98);
  box-shadow:
    0 12px 24px rgba(15, 23, 42, 0.08),
    0 1px 0 rgba(255, 255, 255, 0.95) inset;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.feature-card:hover {
  transform: translateY(-2px);
  box-shadow:
    0 16px 28px rgba(15, 23, 42, 0.1),
    0 1px 0 rgba(255, 255, 255, 0.95) inset;
}

.feature-icon {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, #eef5ff 0%, #e9f1fe 100%);
  color: #3b82f6;
  font-size: 20px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.feature-title {
  color: #2d3642;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.4;
}

.feature-desc {
  margin-top: 6px;
  color: #808b99;
  font-size: 12px;
  line-height: 1.6;
}

.auth-panel {
  display: grid;
  place-items: center;
  padding: 32px 40px;
  background: linear-gradient(180deg, #fbfcfe 0%, #ffffff 100%);
}

.auth-panel-inner {
  width: min(376px, 100%);
  padding-top: 0;
}

.auth-panel h2 {
  margin: 0;
  color: #253041;
  font-size: 38px;
  font-weight: 700;
  text-align: center;
  line-height: 1.2;
}

.auth-subtitle {
  margin: 8px 0 32px;
  color: #9aa4b2;
  font-size: 14px;
  text-align: center;
}

:deep(.el-form-item) {
  margin-bottom: 18px;
}

:deep(.el-form-item__label) {
  display: block;
  margin-bottom: 8px;
  color: #2b3340;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.5;
}

:deep(.el-input__wrapper) {
  min-height: 40px;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 0 0 1px #dbe3ee inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px #3b82f6 inset,
    0 0 0 2px rgba(59, 130, 246, 0.06);
}

:deep(.el-input__inner) {
  font-size: 14px;
}

.submit-btn {
  width: 100%;
  height: 44px;
  margin-top: 4px;
  border: none;
  border-radius: 16px;
  background: linear-gradient(180deg, #3f83d0 0%, #3576c8 100%);
  box-shadow: 0 12px 24px rgba(59, 130, 246, 0.22);
  font-size: 16px;
  font-weight: 700;
}

.submit-btn:hover,
.submit-btn:focus {
  background: linear-gradient(180deg, #4b8edd 0%, #3576c8 100%);
}

.auth-tip {
  margin-top: 14px;
  color: #98a2b3;
  font-size: 12px;
  text-align: center;
}

@media (max-height: 820px) {
  .auth-shell {
    height: min(660px, calc(100vh - 24px));
  }

  .auth-overview {
    padding: 28px 34px 24px;
  }

  .overview-content {
    margin-top: 34px;
  }

  .auth-overview h1 {
    font-size: 26px;
  }

  .feature-grid {
    gap: 12px;
    margin-top: 20px;
  }

  .feature-card {
    min-height: 104px;
    padding: 14px;
  }

  .auth-panel {
    padding: 26px 34px;
  }

  .auth-subtitle {
    margin-bottom: 26px;
  }
}

@media (max-width: 980px) {
  .auth-shell {
    grid-template-columns: 1fr;
    height: auto;
  }

  .auth-overview::after {
    display: none;
  }

  .overview-content {
    margin-top: 42px;
  }

  .overview-summary {
    white-space: normal;
  }
}

@media (max-width: 640px) {
  .auth-page {
    padding: 16px;
    height: auto;
    min-height: 100vh;
    overflow: visible;
  }

  .auth-shell {
    min-height: auto;
    border-radius: 22px;
  }

  .auth-overview,
  .auth-panel {
    padding: 24px;
  }

  .overview-content {
    margin-top: 28px;
  }

  .feature-grid {
    grid-template-columns: 1fr;
  }

  .auth-panel h2 {
    font-size: 34px;
  }
}
</style>
