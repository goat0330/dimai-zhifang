<template>
  <aside class="aside-container" :class="{ 'is-collapsed': isCollapsed }">
    <div class="aside-header" @click="handleNav('/warning/risk-eval')">
      <div class="logo-box">
        <img src="@/assets/imgs/logo.png" alt="Logo" class="logo-img" />
      </div>
      <div v-if="!isCollapsed" class="platform-title">
        <span>地脉智控
宜昌风险管理系统</span>
      </div>
    </div>

    <div class="menu-scroll-area">
      <div class="nav-group" :class="{ 'is-open': isWarningOpen }">
        <div class="nav-item" :class="{ 'is-active': isWarningActive }" @click="toggleWarningMenu">
          <img :src="navWarningSolid" class="nav-icon icon-solid" alt="风险评价" />
          <img :src="navWarningLine" class="nav-icon icon-line" alt="风险评价" />
          <span v-if="!isCollapsed" class="nav-label">风险评价</span>
          <el-icon v-if="!isCollapsed" class="arrow-icon" :class="{ 'is-expanded': isWarningOpen }">
            <ArrowDown />
          </el-icon>
        </div>
        <transition name="submenu-fade">
          <div v-show="isWarningOpen" class="submenu-box">
            <div
              v-for="item in warningSubMenus"
              :key="item.path"
              class="submenu-item"
              :class="{ 'is-active': route.path === item.path }"
              @click.stop="handleNav(item.path)"
            >
              <span class="sub-dot-box"><span class="sub-dot"></span></span>
              <span v-if="!isCollapsed" class="sub-label">{{ item.label }}</span>
            </div>
          </div>
        </transition>
      </div>

      <div class="nav-item" :class="{ 'is-active': route.path === '/ai-studio' }" @click="handleNav('/ai-studio')">
        <img src="@/assets/imgs/home/icon-app-grid.png" class="nav-icon" alt="AI 工作台" />
        <span v-if="!isCollapsed" class="nav-label">AI 工作台</span>
      </div>
    </div>

    <div class="aside-footer">
      <div class="nav-item footer-item user-info">
        <i class="iconfont icon-a-Avatartouxiang"></i>
        <span v-if="!isCollapsed" class="nav-label">{{ userInfo?.user?.nickName || '演示用户' }}</span>
        <div class="hover-del-box-outer">
          <div class="hover-del-box" @click.stop="handleLogout">
            <img :src="logoutIcon" alt="" />
            退出登录
          </div>
        </div>
      </div>
      <div class="nav-item footer-item collapse-btn" @click="toggleCollapse">
        <img src="@/assets/imgs/home/menu-hamburger.png" class="nav-icon" alt="收起" />
        <span v-if="!isCollapsed" class="nav-label">收起侧边栏</span>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useUserStore } from '@/store/user.js'
import logoutIcon from '@/assets/imgs/logout.svg?url'
import navWarningLine from '@/assets/imgs/home/nav-warning-line.png'
import navWarningSolid from '@/assets/imgs/home/nav-warning-solid.png'

defineOptions({ name: 'AppAside' })

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const { userInfo } = storeToRefs(userStore)
const warningSubMenus = [
  { path: '/warning/risk-eval', label: '风险评价地图' },
  { path: '/warning/risk-report', label: '动态风险一张图' },
]
const isCollapsed = ref(route.name === 'DynamicRiskReport' || route.path.startsWith('/warning/'))
const isWarningOpen = ref(true)
const isWarningActive = computed(() => route.path.startsWith('/warning/'))

function handleNav(path) {
  router.push(path)
}

function toggleWarningMenu() {
  if (isCollapsed.value) {
    isCollapsed.value = false
    isWarningOpen.value = true
    return
  }
  isWarningOpen.value = !isWarningOpen.value
}

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}

function handleLogout() {
  userStore.logout()
}
</script>
<style lang="less" scoped>
.aside-container {
  width: 200px;
  height: 100vh;
  background: transparent;
  border-right: 0;
  display: flex;
  flex-direction: column;
  padding: 28px 20px 22px;
  box-sizing: border-box;
  flex-shrink: 0;
  overflow: visible;
  position: relative;
  transition: width 0.26s cubic-bezier(0.4, 0, 0.2, 1),
              padding 0.26s cubic-bezier(0.4, 0, 0.2, 1);
  will-change: width, padding;
  user-select: none;
  z-index: 2;

  &.is-collapsed {
    width: 68px;
    padding: 28px 10px 22px;

    .aside-header {
      padding-left: 4px;
      margin-bottom: 24px;
    }

    .nav-item {
      justify-content: flex-start;
      padding: 0 14px;
      border-radius: 10px;
    }

    .nav-group .submenu-box {
      gap: 0;
      padding-left: 0;
      margin: 2px 0;
    }

    .nav-group .submenu-item {
      width: 100%;
      height: 48px;
      min-height: 48px;
      justify-content: flex-start;
      padding: 0 14px;

      &:hover,
      &.is-active {
        background: transparent;
      }
    }

    .menu-divider {
      margin-right: 8px;
      margin-left: 8px;
    }
  }
}

.aside-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 24px;
  cursor: pointer;
  padding-left: 2px;
  min-width: 0;
  overflow: hidden;
  transition: padding-left 0.26s cubic-bezier(0.4, 0, 0.2, 1);

  .logo-box {
    width: 40px;
    height: 40px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;

    .logo-img {
      width: 40px;
      height: 40px;
      object-fit: contain;
    }
  }

  .platform-title {
    font-family: 'Alimama FangYuanTi VF', sans-serif;
    display: flex;
    flex-direction: column;
    font-size: 18px;
    font-weight: 700;
    line-height: 1.25;
    color: transparent;
    background: linear-gradient(90deg, #007bff 12.5%, #00b2ff 100%);
    background-clip: text;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    white-space: nowrap;
    letter-spacing: 0;
    flex: 0 0 118px;
    min-width: 0;
    overflow: hidden;

    span {
      white-space: pre-wrap;
    }
  }
}

.menu-scroll-area {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
  gap: 2px;

  /* 隐藏滚动条 */
  &::-webkit-scrollbar {
    display: none;
  }
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 48px;
  min-height: 48px;
  padding: 0 18px;
  border-radius: 10px;
  color: #383c41;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: padding 0.26s cubic-bezier(0.4, 0, 0.2, 1),
              background-color 0.2s ease,
              color 0.2s ease;
  flex-shrink: 0;

  .nav-icon {
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    object-fit: contain;

    &.icon-solid {
      display: none;
    }

    &.icon-line {
      display: block;
    }
  }

  .nav-label {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .arrow-icon {
    font-size: 12px;
    color: #94a3b8;
    transition: transform 0.22s ease,
                color 0.2s ease;

    &.is-expanded {
      transform: rotate(180deg);
    }
  }

  &:hover {
    background-color: #f1f5f9;
    color: #007bff;

    .arrow-icon {
      color: #007bff;
    }

    .nav-icon {
      &.icon-solid {
        display: block;
      }

      &.icon-line {
        display: none;
      }
    }
  }

  &.is-active {
    background-color: rgba(255, 255, 255, 0.72);
    color: #007bff;
    font-weight: 600;

    .arrow-icon {
      color: #007bff;
    }

    .nav-icon {
      &.icon-solid {
        display: block;
      }

      &.icon-line {
        display: none;
      }
    }
  }
}

.nav-group {
  display: flex;
  flex-direction: column;

  > .nav-item.is-active {
    background-color: transparent;
    color: #007bff;

    &:hover {
      background-color: #f1f5f9;
    }
  }

  .submenu-box {
    display: flex;
    flex-direction: column;
    gap: 0;
    padding-left: 0;
    margin: 0 0 2px;
    overflow: hidden;
    max-height: 240px;
  }

  .submenu-item {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 48px;
    min-height: 48px;
    padding: 0 18px;
    border-radius: 10px;
    color: #617185;
    font-size: 14px;
    cursor: pointer;
    transition: padding 0.26s cubic-bezier(0.4, 0, 0.2, 1),
                background-color 0.2s ease,
                color 0.2s ease;
    flex-shrink: 0;

    .sub-dot-box {
      width: 20px;
      height: 20px;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .sub-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background-color: #a6acb8;
      transition: background-color 0.2s ease;
    }

    .sub-label {
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    &:hover {
      background-color: #f8fafc;
      color: #007bff;

      .sub-dot {
        background-color: #007bff;
      }
    }

    &.is-active {
      color: #007bff;
      font-weight: 600;
      background-color: rgba(255, 255, 255, 0.72);

      .sub-dot {
        background-color: #007bff;
      }
    }
  }
}

.menu-divider {
  height: 1px;
  flex-shrink: 0;
  margin: 10px 12px 8px;
  background: rgba(166, 172, 184, 0.32);
}

.aside-footer {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-top: 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);

  .footer-item {
    height: 40px;
    color: #64748b;

    .setting-icon {
      background-color: #9096a2;
      mask: url('@/assets/imgs/home/setting.png') center / contain no-repeat;
      -webkit-mask: url('@/assets/imgs/home/setting.png') center / contain no-repeat;
      transition: background-color 0.2s ease;
    }

    .avatar-icon {
      border-radius: 50%;
    }

    &:hover {
      color: #007bff;
      background-color: #f8fafc;

      .setting-icon {
        background-color: #007bff;
      }
    }

    &.is-active {
      color: #007bff;
    }
  }

  .user-info {
    position: relative;

    > i {
      display: flex;
      width: 20px;
      justify-content: center;
      font-size: 18px;
    }

    .hover-del-box-outer {
      position: absolute;
      top: 50%;
      right: -100px;
      z-index: 2000;
      display: flex;
      width: 140px;
      height: 48px;
      padding-left: 50px;
      pointer-events: none;
      opacity: 0;
      transform: translateY(-50%);
      transition: opacity 0.2s ease;
      visibility: hidden;
    }

    .hover-del-box {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 114px;
      height: 48px;
      gap: 10px;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 4px 12px 0 #0062de66;
      color: #222527;
      font-size: 12px;
      cursor: pointer;

      img {
        width: 16px;
        height: 16px;
      }

      &:hover {
        background: #dcedff;
      }
    }

    &:hover {
      color: #007bff;

      .hover-del-box-outer {
        pointer-events: auto;
        opacity: 1;
        visibility: visible;
      }
    }
  }

  .collapse-btn {
    margin-top: 2px;
  }

  .message-icon-wrap {
    position: relative;
    display: flex;
    width: 20px;
    height: 20px;
    align-items: center;
    justify-content: center;
    flex: 0 0 20px;
  }

  .message-icon { font-size: 18px; }

  .notice-count {
    position: absolute;
    top: -8px;
    left: 12px;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    border: 2px solid #fff;
    border-radius: 8px;
    background: #e45b5b;
    color: #fff;
    font-family: 'Alimama FangYuanTi VF', sans-serif;
    font-size: 10px;
    line-height: 12px;
    text-align: center;
    box-sizing: border-box;
  }
}

.submenu-fade-enter-active,
.submenu-fade-leave-active {
  transition:
    max-height 0.26s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.2s ease;
  overflow: hidden;
}

.submenu-fade-enter-from,
.submenu-fade-leave-to {
  opacity: 0;
  max-height: 0 !important;
}

.submenu-fade-enter-to,
.submenu-fade-leave-from {
  opacity: 1;
  max-height: 240px;
}
</style>

