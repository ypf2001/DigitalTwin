<template>
  <div class="app-container">
    <!-- 顶部导航栏 -->
    <header class="top-bar">
      <div class="logo">
        <span class="logo-icon">🥔</span>
        <h1>马铃薯智慧灌溉数字孪生</h1>
      </div>
      <div class="top-bar-actions">
        <!-- 可以放置用户头像、消息通知等 -->
        <span class="user-avatar">G</span>
      </div>
    </header>

    <div class="main-layout">
      <!-- 左侧菜单栏 -->
      <SideMenu />

      <!-- 内容区 -->
      <main class="content-area">
        <div class="content-wrapper">
          <router-view />
        </div>
      </main>
    </div>
  </div>
</template>

<script>
import SideMenu from './components/SideMenu.vue'

export default {
  name: 'App',
  components: {
    SideMenu,
  },
}
</script>

<style>
/* 全局样式重置和基础设定 */
:root {
  --primary-color: #4a90e2;
  --primary-color-dark: #357abd;
  --bg-color: #f4f7fa;
  --card-bg: #ffffff;
  --text-color: #333;
  --text-secondary: #666;
  --border-color: #e0e6ed;
  --sidebar-bg: #2c3e50;
  --sidebar-text: #ecf0f1;
  --sidebar-active-bg: #34495e;
  --card-min-width: 280px; /* 定义统一的卡片最小宽度 */
}

body {
  margin: 0;
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', '微软雅黑', Arial, sans-serif;
  background-color: var(--bg-color);
  color: var(--text-color);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* 整体布局 */
.app-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  height: 60px;
  background-color: var(--card-bg);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
  z-index: 100;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo-icon {
  font-size: 28px;
}
.logo h1 {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.user-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background-color: var(--primary-color);
  color: white;
  font-weight: bold;
  cursor: pointer;
}

.main-layout {
  display: flex;
  flex-grow: 1;
  overflow: hidden;
}

.content-area {
  flex-grow: 1;
  overflow-y: auto;
  padding: 24px;
}

.content-wrapper {
  max-width: 1600px; /* 重新设置一个更大的最大宽度 */
  width: 100%;
  margin: 0 auto;
}

/* 新增：页面根容器样式，确保子页面占据全部可用宽度 */
.page-container {
  width: 100%;
}

/* --- 通用组件样式 --- */
.card {
  background: var(--card-bg);
  border-radius: 8px;
  border: 1px solid var(--border-color);
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  margin: -20px -20px 20px -20px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid transparent;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  text-decoration: none;
}

.btn-primary {
  background-color: var(--primary-color);
  color: white;
  border-color: var(--primary-color);
}
.btn-primary:hover {
  background-color: var(--primary-color-dark);
  border-color: var(--primary-color-dark);
}

.btn-outline {
  background-color: transparent;
  color: var(--primary-color);
  border-color: var(--primary-color);
}
.btn-outline:hover {
  background-color: rgba(74, 144, 226, 0.05);
}

.form-input, .form-select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 14px;
}
.form-group {
  margin-bottom: 16px;
}
.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}
</style>
