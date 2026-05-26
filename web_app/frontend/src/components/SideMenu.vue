<template>
  <aside class="side-menu">
    <nav>
      <ul>
        <li>
          <router-link to="/" class="menu-item" active-class="active">
            <i class="icon-dashboard"></i>
            <span>仪表盘</span>
          </router-link>
        </li>
        <li>
          <router-link to="/simulation" class="menu-item" active-class="active">
            <i class="icon-simulation"></i>
            <span>仿真实验室</span>
          </router-link>
        </li>
        <li>
          <router-link to="/training" class="menu-item" active-class="active">
            <i class="icon-training"></i>
            <span>模型训练</span>
          </router-link>
        </li>
        <li>
          <router-link to="/settings" class="menu-item" active-class="active">
            <i class="icon-settings"></i>
            <span>系统设置</span>
          </router-link>
        </li>
      </ul>
    </nav>
  </aside>
</template>

<script>
export default {
  name: 'SideMenu',
}
</script>

<style scoped>
.side-menu {
  width: 220px;
  background-color: var(--sidebar-bg);
  color: var(--sidebar-text);
  padding: 20px 0;
  flex-shrink: 0;
  box-shadow: 2px 0 6px rgba(0,0,0,0.1);
  overflow-y: auto;
}

.side-menu ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.side-menu li {
  margin-bottom: 5px;
}

.menu-item {
  display: flex;
  align-items: center;
  padding: 12px 20px;
  color: var(--sidebar-text);
  text-decoration: none;
  transition: background-color 0.2s ease;
}

.menu-item:hover {
  background-color: rgba(255, 255, 255, 0.1);
}

.menu-item.active {
  background-color: var(--primary-color);
  color: white;
  font-weight: 600;
}

.menu-item i {
  margin-right: 10px;
  font-size: 18px;
  /* 实际项目中这里会用 icon font 或 SVG */
}

/* 示例图标样式 (实际项目中应替换为真实的图标库) */
.icon-dashboard::before { content: '📊'; }
.icon-simulation::before { content: '🔬'; }
.icon-training::before { content: '🧠'; }
.icon-settings::before { content: '⚙️'; }
</style>
