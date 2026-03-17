<template>
  <div class="fade-in">
    <div class="page-header">
      <h2>用户与权限</h2>
      <div style="display:flex; gap:8px;">
        <el-button v-if="canSync" @click="handleSyncPermissions">同步内置权限</el-button>
        <el-button v-if="activeTab === 'users' && canManageUsers" type="primary" @click="openUserDialog()">
          <el-icon><Plus /></el-icon> 新增用户
        </el-button>
        <el-button v-if="activeTab === 'roles' && canManageRoles" type="primary" @click="openRoleDialog()">
          <el-icon><Plus /></el-icon> 新增角色
        </el-button>
        <el-button v-if="activeTab === 'groups' && canManageGroups" type="primary" @click="openGroupDialog()">
          <el-icon><Plus /></el-icon> 新增用户组
        </el-button>
      </div>
    </div>

    <div class="table-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane v-if="canViewUsers" label="用户" name="users" />
        <el-tab-pane v-if="canViewGroups" label="用户组" name="groups" />
        <el-tab-pane v-if="canViewRoles" label="角色" name="roles" />
        <el-tab-pane v-if="canViewPermissions" label="权限字典" name="permissions" />
      </el-tabs>

      <template v-if="activeTab === 'users' && canViewUsers">
        <div class="filter-bar">
          <el-input v-model="userSearch" placeholder="搜索用户名 / 邮箱" clearable style="width: 260px" @input="fetchUsers" />
        </div>
        <el-table :data="users" stripe v-loading="loading.users">
          <el-table-column prop="username" label="用户名" min-width="130" />
          <el-table-column label="姓名" min-width="120">
            <template #default="{ row }">{{ row.display_name || row.username }}</template>
          </el-table-column>
          <el-table-column prop="email" label="邮箱" min-width="180" />
          <el-table-column label="用户组" min-width="180">
            <template #default="{ row }">
              <el-tag v-for="group in row.user_groups" :key="group.id" size="small" type="info" style="margin-right:6px;">{{ group.name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="角色" min-width="220">
            <template #default="{ row }">
              <el-tag v-for="role in row.roles" :key="role.id" size="small" style="margin-right:6px;">{{ role.name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="系统身份" width="120">
            <template #default="{ row }">
              <el-tag :type="row.is_superuser ? 'danger' : row.is_staff ? 'warning' : 'info'" size="small">
                {{ row.is_superuser ? '超级管理员' : row.is_staff ? '管理员' : '普通用户' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="加入时间" width="170">
            <template #default="{ row }">{{ formatTime(row.date_joined) }}</template>
          </el-table-column>
          <el-table-column v-if="canManageUsers" label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openUserDialog(row)">编辑</el-button>
              <el-button link type="warning" @click="openPasswordDialog(row)">重置密码</el-button>
              <el-popconfirm title="确定删除该用户？" @confirm="handleDeleteUser(row.id)">
                <template #reference>
                  <el-button link type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
        <div style="display:flex; justify-content:flex-end; margin-top:16px;">
          <el-pagination
            v-model:current-page="userPage"
            :page-size="20"
            :total="userTotal"
            layout="total, prev, pager, next"
            @current-change="fetchUsers"
          />
        </div>
      </template>

      <template v-else-if="activeTab === 'roles' && canViewRoles">
        <div class="filter-bar">
          <el-input v-model="roleSearch" placeholder="搜索角色编码 / 名称" clearable style="width: 260px" @input="fetchRoles" />
        </div>
        <el-table :data="roles" stripe v-loading="loading.roles">
          <el-table-column prop="code" label="角色编码" width="160" />
          <el-table-column prop="name" label="角色名称" min-width="160" />
          <el-table-column prop="description" label="说明" min-width="220" />
          <el-table-column label="权限数" width="100">
            <template #default="{ row }">{{ row.permissions.length }}</template>
          </el-table-column>
          <el-table-column label="内置" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_builtin ? 'warning' : 'info'" size="small">{{ row.is_builtin ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="canManageRoles" label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openRoleDialog(row)">编辑</el-button>
              <el-popconfirm title="确定删除该角色？" @confirm="handleDeleteRole(row.id)">
                <template #reference>
                  <el-button link type="danger" :disabled="row.is_builtin">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="activeTab === 'groups' && canViewGroups">
        <div class="filter-bar">
          <el-input v-model="groupSearch" placeholder="搜索用户组编码 / 名称" clearable style="width: 260px" @input="fetchGroups" />
        </div>
        <el-table :data="groups" stripe v-loading="loading.groups">
          <el-table-column prop="code" label="用户组编码" width="160" />
          <el-table-column prop="name" label="用户组名称" min-width="160" />
          <el-table-column prop="description" label="说明" min-width="220" />
          <el-table-column label="角色" min-width="220">
            <template #default="{ row }">
              <el-tag v-for="role in row.roles" :key="role.id" size="small" style="margin-right:6px;">{{ role.name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="成员数" width="90">
            <template #default="{ row }">{{ row.users.length }}</template>
          </el-table-column>
          <el-table-column v-if="canManageGroups" label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openGroupDialog(row)">编辑</el-button>
              <el-popconfirm title="确定删除该用户组？" @confirm="handleDeleteGroup(row.id)">
                <template #reference>
                  <el-button link type="danger" :disabled="row.is_builtin">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="activeTab === 'permissions' && canViewPermissions">
        <div class="filter-bar">
          <el-input v-model="permissionSearch" placeholder="搜索权限编码 / 名称" clearable style="width: 280px" @input="applyPermissionFilter" />
        </div>
        <el-table :data="filteredPermissions" stripe v-loading="loading.permissions">
          <el-table-column prop="category" label="模块" width="120" />
          <el-table-column prop="name" label="权限名称" min-width="180" />
          <el-table-column prop="code" label="权限编码" min-width="220" />
          <el-table-column prop="description" label="说明" min-width="260" />
        </el-table>
      </template>
    </div>

    <el-dialog v-model="userDialogVisible" :title="editingUserId ? '编辑用户' : '新增用户'" width="720px" destroy-on-close>
      <el-form :model="userForm" label-width="90px">
        <div class="dialog-grid">
          <el-form-item label="用户名">
            <el-input v-model="userForm.username" :disabled="!!editingUserId" />
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input v-model="userForm.email" />
          </el-form-item>
          <el-form-item label="名">
            <el-input v-model="userForm.first_name" />
          </el-form-item>
          <el-form-item label="姓">
            <el-input v-model="userForm.last_name" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="userForm.password" type="password" show-password :placeholder="editingUserId ? '留空则不修改' : '请输入密码'" />
          </el-form-item>
          <el-form-item label="启用">
            <el-switch v-model="userForm.is_active" />
          </el-form-item>
          <el-form-item label="管理员">
            <el-switch v-model="userForm.is_staff" />
          </el-form-item>
          <el-form-item label="超管">
            <el-switch v-model="userForm.is_superuser" />
          </el-form-item>
        </div>
        <el-form-item label="用户组">
          <el-select v-model="userForm.group_ids" multiple filterable style="width:100%">
            <el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role_ids" multiple filterable style="width:100%">
            <el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.user" @click="handleSaveUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDialogVisible" :title="editingRoleId ? '编辑角色' : '新增角色'" width="760px" destroy-on-close>
      <el-form :model="roleForm" label-width="90px">
        <el-form-item label="角色编码">
          <el-input v-model="roleForm.code" :disabled="currentRoleBuiltin" />
        </el-form-item>
        <el-form-item label="角色名称">
          <el-input v-model="roleForm.name" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="roleForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="权限">
          <el-select v-model="roleForm.permission_ids" multiple filterable collapse-tags style="width:100%">
            <el-option v-for="permission in permissions" :key="permission.id" :label="`${permission.name} (${permission.code})`" :value="permission.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.role" @click="handleSaveRole">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="groupDialogVisible" :title="editingGroupId ? '编辑用户组' : '新增用户组'" width="760px" destroy-on-close>
      <el-form :model="groupForm" label-width="90px">
        <el-form-item label="用户组编码">
          <el-input v-model="groupForm.code" :disabled="currentGroupBuiltin" />
        </el-form-item>
        <el-form-item label="用户组名称">
          <el-input v-model="groupForm.name" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="groupForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="groupForm.role_ids" multiple filterable style="width:100%">
            <el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="成员">
          <el-select v-model="groupForm.user_ids" multiple filterable style="width:100%">
            <el-option v-for="user in userOptions" :key="user.id" :label="user.username" :value="user.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="groupDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.group" @click="handleSaveGroup">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="passwordDialogVisible" title="重置密码" width="420px" destroy-on-close>
      <el-form :model="passwordForm" label-width="90px">
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving.password" @click="handleResetPassword">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createGroup,
  createRole,
  createUser,
  deleteGroup,
  deleteRole,
  deleteUser,
  getGroups,
  getPermissions,
  getRoles,
  getUsers,
  resetUserPassword,
  syncPermissions,
  updateGroup,
  updateRole,
  updateUser,
} from '@/api/modules/rbac'
import { useAuthStore } from '@/stores/auth'
import { useRouteTabState } from '@/composables/useRouteTabState'

const authStore = useAuthStore()

const canViewUsers = computed(() => authStore.hasPermission('rbac.user.view'))
const canManageUsers = computed(() => authStore.hasPermission('rbac.user.manage'))
const canViewRoles = computed(() => authStore.hasPermission('rbac.role.view'))
const canManageRoles = computed(() => authStore.hasPermission('rbac.role.manage'))
const canViewGroups = computed(() => authStore.hasPermission('rbac.group.view'))
const canManageGroups = computed(() => authStore.hasPermission('rbac.group.manage'))
const canViewPermissions = computed(() => authStore.hasPermission('rbac.permission.view'))
const canSync = computed(() => authStore.hasPermission('rbac.permission.view'))

const availableTabs = computed(() => [
  canViewUsers.value && 'users',
  canViewGroups.value && 'groups',
  canViewRoles.value && 'roles',
  canViewPermissions.value && 'permissions',
].filter(Boolean))

const activeTab = useRouteTabState({
  tabs: () => availableTabs.value,
  defaultTab: 'users',
}).activeTab
const loading = ref({ users: false, roles: false, groups: false, permissions: false })
const saving = ref({ user: false, role: false, group: false, password: false })

const users = ref([])
const userOptions = ref([])
const userSearch = ref('')
const userPage = ref(1)
const userTotal = ref(0)

const roles = ref([])
const roleSearch = ref('')

const groups = ref([])
const groupSearch = ref('')

const permissions = ref([])
const permissionSearch = ref('')
const filteredPermissions = ref([])

const userDialogVisible = ref(false)
const editingUserId = ref(null)
const userForm = ref({})

const roleDialogVisible = ref(false)
const editingRoleId = ref(null)
const roleForm = ref({})
const currentRoleBuiltin = computed(() => roles.value.find(item => item.id === editingRoleId.value)?.is_builtin || false)

const groupDialogVisible = ref(false)
const editingGroupId = ref(null)
const groupForm = ref({})
const currentGroupBuiltin = computed(() => groups.value.find(item => item.id === editingGroupId.value)?.is_builtin || false)

const passwordDialogVisible = ref(false)
const passwordUserId = ref(null)
const passwordForm = ref({ password: '' })

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

function resetUserForm() {
  userForm.value = {
    username: '',
    email: '',
    first_name: '',
    last_name: '',
    password: '',
    is_active: true,
    is_staff: false,
    is_superuser: false,
    role_ids: [],
    group_ids: [],
  }
}

function resetRoleForm() {
  roleForm.value = {
    code: '',
    name: '',
    description: '',
    permission_ids: [],
  }
}

function resetGroupForm() {
  groupForm.value = {
    code: '',
    name: '',
    description: '',
    role_ids: [],
    user_ids: [],
  }
}

async function fetchUsers() {
  if (!canViewUsers.value) return
  loading.value.users = true
  try {
    const params = { page: userPage.value }
    if (userSearch.value) params.search = userSearch.value
    const res = await getUsers(params)
    users.value = res.results || []
    userTotal.value = res.count || users.value.length
    if (!userSearch.value) {
      userOptions.value = users.value
    }
  } finally {
    loading.value.users = false
  }
}

async function fetchUserOptions() {
  if (!canViewUsers.value) return
  const res = await getUsers({ page_size: 999 })
  userOptions.value = res.results || res || []
}

async function fetchRoles() {
  if (!canViewRoles.value) return
  loading.value.roles = true
  try {
    const params = roleSearch.value ? { search: roleSearch.value } : {}
    roles.value = await getRoles(params)
  } finally {
    loading.value.roles = false
  }
}

async function fetchGroups() {
  if (!canViewGroups.value) return
  loading.value.groups = true
  try {
    const params = groupSearch.value ? { search: groupSearch.value } : {}
    groups.value = await getGroups(params)
  } finally {
    loading.value.groups = false
  }
}

async function fetchPermissions() {
  if (!canViewPermissions.value) return
  loading.value.permissions = true
  try {
    permissions.value = await getPermissions()
    applyPermissionFilter()
  } finally {
    loading.value.permissions = false
  }
}

function applyPermissionFilter() {
  const keyword = permissionSearch.value.trim().toLowerCase()
  filteredPermissions.value = permissions.value.filter((item) => {
    if (!keyword) return true
    return [item.name, item.code, item.description, item.category]
      .filter(Boolean)
      .some(value => value.toLowerCase().includes(keyword))
  })
}

function openUserDialog(row) {
  resetUserForm()
  editingUserId.value = row?.id || null
  if (row) {
    userForm.value = {
      username: row.username,
      email: row.email,
      first_name: row.first_name || '',
      last_name: row.last_name || '',
      password: '',
      is_active: row.is_active,
      is_staff: row.is_staff,
      is_superuser: row.is_superuser,
      role_ids: row.roles.map(item => item.id),
      group_ids: row.user_groups.map(item => item.id),
    }
  }
  userDialogVisible.value = true
}

function openRoleDialog(row) {
  resetRoleForm()
  editingRoleId.value = row?.id || null
  if (row) {
    roleForm.value = {
      code: row.code,
      name: row.name,
      description: row.description,
      permission_ids: row.permissions.map(item => item.id),
    }
  }
  roleDialogVisible.value = true
}

function openGroupDialog(row) {
  resetGroupForm()
  editingGroupId.value = row?.id || null
  if (row) {
    groupForm.value = {
      code: row.code,
      name: row.name,
      description: row.description,
      role_ids: row.roles.map(item => item.id),
      user_ids: row.users.map(item => item.id),
    }
  }
  groupDialogVisible.value = true
}

function openPasswordDialog(row) {
  passwordUserId.value = row.id
  passwordForm.value = { password: '' }
  passwordDialogVisible.value = true
}

async function handleSaveUser() {
  saving.value.user = true
  try {
    const payload = { ...userForm.value }
    if (!payload.password) delete payload.password
    if (editingUserId.value) {
      await updateUser(editingUserId.value, payload)
      ElMessage.success('用户已更新')
    } else {
      await createUser(payload)
      ElMessage.success('用户已创建')
    }
    userDialogVisible.value = false
    await Promise.all([fetchUsers(), fetchUserOptions()])
  } finally {
    saving.value.user = false
  }
}

async function handleSaveRole() {
  saving.value.role = true
  try {
    if (editingRoleId.value) {
      await updateRole(editingRoleId.value, roleForm.value)
      ElMessage.success('角色已更新')
    } else {
      await createRole(roleForm.value)
      ElMessage.success('角色已创建')
    }
    roleDialogVisible.value = false
    await Promise.all([fetchRoles(), fetchUsers()])
  } finally {
    saving.value.role = false
  }
}

async function handleSaveGroup() {
  saving.value.group = true
  try {
    if (editingGroupId.value) {
      await updateGroup(editingGroupId.value, groupForm.value)
      ElMessage.success('用户组已更新')
    } else {
      await createGroup(groupForm.value)
      ElMessage.success('用户组已创建')
    }
    groupDialogVisible.value = false
    await Promise.all([fetchGroups(), fetchUsers(), fetchUserOptions()])
  } finally {
    saving.value.group = false
  }
}

async function handleResetPassword() {
  if (!passwordForm.value.password) {
    ElMessage.warning('请输入新密码')
    return
  }
  saving.value.password = true
  try {
    await resetUserPassword(passwordUserId.value, passwordForm.value.password)
    ElMessage.success('密码已重置')
    passwordDialogVisible.value = false
  } finally {
    saving.value.password = false
  }
}

async function handleDeleteUser(id) {
  await deleteUser(id)
  ElMessage.success('用户已删除')
  await Promise.all([fetchUsers(), fetchUserOptions()])
}

async function handleDeleteRole(id) {
  await deleteRole(id)
  ElMessage.success('角色已删除')
  await Promise.all([fetchRoles(), fetchUsers()])
}

async function handleDeleteGroup(id) {
  await deleteGroup(id)
  ElMessage.success('用户组已删除')
  await Promise.all([fetchGroups(), fetchUsers(), fetchUserOptions()])
}

async function handleSyncPermissions() {
  await syncPermissions()
  await Promise.all([fetchPermissions(), fetchRoles()])
  ElMessage.success('权限与内置角色已同步')
}

onMounted(async () => {
  const tasks = []
  if (canViewUsers.value) tasks.push(fetchUsers(), fetchUserOptions())
  if (canViewRoles.value) tasks.push(fetchRoles())
  if (canViewGroups.value) tasks.push(fetchGroups())
  if (canViewPermissions.value) tasks.push(fetchPermissions())
  await Promise.all(tasks)
})
</script>

<style scoped>
.dialog-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 12px;
}
</style>
