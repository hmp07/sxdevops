<template>
  <div class="forbidden-page">
    <div class="forbidden-card">
      <div class="forbidden-code">403</div>
      <h1>无权访问</h1>
      <p v-if="hasNoAccess">当前账号尚未分配任何权限，请联系管理员分配角色或用户组。</p>
      <p v-else>当前账号没有访问该页面的权限，请联系管理员分配角色或用户组。</p>
      <div class="actions">
        <el-button v-if="!hasNoAccess" @click="$router.back()">返回上一页</el-button>
        <el-button v-if="hasNoAccess" type="primary" @click="goLogin">返回登录</el-button>
        <el-button v-else type="primary" @click="goHome">回到首页</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { pinia } from '@/stores'
import { useAuthStore } from '@/stores/auth'
import { firstAccessibleRoute } from '@/router'

const router = useRouter()
const authStore = useAuthStore(pinia)
const hasNoAccess = computed(() => authStore.hasNoAccess)

function goLogin() {
  router.push('/login')
}

function goHome() {
  // 跳到第一个有权限的页面，避免"有权限但无 dashboard 权限"的用户二次 403
  router.push(firstAccessibleRoute() || '/login')
}
</script>

<style scoped>
.forbidden-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
  padding: 24px;
}

.forbidden-card {
  width: min(520px, 100%);
  padding: 40px;
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
  text-align: center;
}

.forbidden-code {
  font-size: 72px;
  font-weight: 800;
  line-height: 1;
  color: #f97316;
}

h1 {
  margin: 16px 0 12px;
  color: #0f172a;
}

p {
  margin: 0;
  color: #475569;
}

.actions {
  margin-top: 24px;
  display: flex;
  justify-content: center;
  gap: 12px;
}
</style>
