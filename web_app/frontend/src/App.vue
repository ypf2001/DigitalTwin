<template>
  <div class="layout">
    <div class="sidebar-overlay" :class="{ show: sidebarOpen }" @click="sidebarOpen = false"></div>
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-brand"><span class="icon">🥔</span> 数字孪生</div>
      <nav class="sidebar-nav">
        <router-link to="/" @click="sidebarOpen = false"><span class="nav-icon">📊</span> 首页</router-link>
        <router-link to="/simulation" @click="sidebarOpen = false"><span class="nav-icon">🔬</span> 仿真运行</router-link>
        <router-link to="/season-compare" @click="sidebarOpen = false"><span class="nav-icon">📈</span> 季节对比</router-link>
        <router-link to="/settings" @click="sidebarOpen = false"><span class="nav-icon">⚙️</span> 系统配置</router-link>
      </nav>
    </aside>
    <div class="main">
      <header class="page-header">
        <button class="hamburger" @click="sidebarOpen = !sidebarOpen">☰</button>
        <h1>{{ pageTitle }}</h1>
      </header>
      <div class="page-content"><router-view /></div>
    </div>
    <nav class="mobile-nav">
      <div class="mobile-nav-inner">
        <router-link to="/"><span class="nav-icon">📊</span> 首页</router-link>
        <router-link to="/simulation"><span class="nav-icon">🔬</span> 仿真</router-link>
        <router-link to="/season-compare"><span class="nav-icon">📈</span> 对比</router-link>
        <router-link to="/settings"><span class="nav-icon">⚙️</span> 配置</router-link>
      </div>
    </nav>
  </div>
</template>

<script>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'

export default {
  name: 'App',
  setup() {
    const route = useRoute()
    const sidebarOpen = ref(false)
    const pageTitle = computed(() => ({
      Dashboard: '系统总览', Simulation: '仿真运行',
      SeasonCompare: '季节对比 T1 vs T2', Settings: '系统配置',
    }[route.name] || '数字孪生系统'))
    return { sidebarOpen, pageTitle }
  },
}
</script>
