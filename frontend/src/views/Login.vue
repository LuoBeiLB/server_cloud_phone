<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuth } from '../stores/auth'

const router = useRouter()
const auth = useAuth()
const username = ref('admin')
const password = ref('admin123')
const loading = ref(false)

const pupilRefs = ref([])
let mouseHandler = null

onMounted(() => {
  mouseHandler = (e) => {
    pupilRefs.value.forEach((pupil) => {
      if (!pupil) return
      const rect = pupil.parentElement.getBoundingClientRect()
      const cx = rect.left + rect.width / 2
      const cy = rect.top + rect.height / 2
      const angle = Math.atan2(e.clientY - cy, e.clientX - cx)
      const dist = Math.min(3.5, Math.hypot(e.clientX - cx, e.clientY - cy) / 30)
      pupil.style.transform = `translate(${Math.cos(angle) * dist}px, ${Math.sin(angle) * dist}px)`
    })
  }
  window.addEventListener('mousemove', mouseHandler)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', mouseHandler)
})

function setPupil(el, i) {
  pupilRefs.value[i] = el
}

async function submit() {
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    ElMessage.success('登录成功')
    router.push('/devices')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <!-- 星空背景 -->
    <div class="stars">
      <div v-for="i in 80" :key="'star-'+i" class="star"
        :style="{
          left: Math.random()*100 + '%',
          top: Math.random()*100 + '%',
          width: (Math.random()*2+1) + 'px',
          height: (Math.random()*2+1) + 'px',
          animationDelay: Math.random()*5 + 's',
          animationDuration: (Math.random()*3+2) + 's'
        }"></div>
    </div>

    <!-- 流星 -->
    <div class="shooting-star s1"></div>
    <div class="shooting-star s2"></div>
    <div class="shooting-star s3"></div>

    <!-- 行星 -->
    <div class="planet planet-1"><div class="planet-ring"></div></div>
    <div class="planet planet-2"></div>
    <div class="planet planet-3"></div>

    <!-- 飞船 -->
    <div class="ship ship-1">
      <div class="ship-body"></div>
      <div class="ship-cockpit"></div>
      <div class="ship-flame"></div>
    </div>
    <div class="ship ship-2">
      <div class="ship-body"></div>
      <div class="ship-cockpit"></div>
      <div class="ship-flame"></div>
    </div>

    <!-- 光斑 -->
    <div class="bg-circle bg-circle-1"></div>
    <div class="bg-circle bg-circle-2"></div>
    <div class="bg-circle bg-circle-3"></div>
    <div class="bg-circle bg-circle-4"></div>

    <div class="login-card">
      <!-- 卡通角色 -->
      <div class="characters">
        <div class="char char-orange">
          <div class="char-eyes">
            <div class="eye"><div class="pupil" :ref="(el) => setPupil(el, 0)"></div></div>
            <div class="eye"><div class="pupil" :ref="(el) => setPupil(el, 1)"></div></div>
          </div>
        </div>
        <div class="char char-purple">
          <div class="char-eyes">
            <div class="eye"><div class="pupil" :ref="(el) => setPupil(el, 2)"></div></div>
            <div class="eye"><div class="pupil" :ref="(el) => setPupil(el, 3)"></div></div>
          </div>
        </div>
        <div class="char char-black">
          <div class="char-eyes">
            <div class="eye"><div class="pupil" :ref="(el) => setPupil(el, 4)"></div></div>
            <div class="eye"><div class="pupil" :ref="(el) => setPupil(el, 5)"></div></div>
          </div>
        </div>
        <div class="char char-yellow">
          <div class="char-eyes">
            <div class="eye"><div class="pupil" :ref="(el) => setPupil(el, 6)"></div></div>
            <div class="eye"><div class="pupil" :ref="(el) => setPupil(el, 7)"></div></div>
          </div>
          <div class="char-mouth"></div>
        </div>
      </div>

      <!-- 标题 -->
      <div class="login-head">
        <div>
          <div class="login-title">X86 云手机平台</div>
          <div class="login-sub">网站登录及管理系统 · 类魔云腾</div>
        </div>
        <img src="/logo.png" class="login-logo" alt="logo" />
      </div>

      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input v-model="username" placeholder="用户名" size="large" :prefix-icon="'User'" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="密码"
            size="large"
            show-password
            :prefix-icon="'Lock'"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          style="width: 100%"
          :loading="loading"
          @click="submit"
        >
          登 录
        </el-button>
      </el-form>
      <div class="login-sub" style="margin: 14px 0 0; text-align: center">
        默认账号 admin / admin123
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #0a0a2e 0%, #1a1a4e 30%, #16213e 60%, #0f3460 100%);
  position: relative;
  overflow: hidden;
}

/* ===== 星星 ===== */
.stars {
  position: absolute;
  inset: 0;
  z-index: 0;
}
.star {
  position: absolute;
  background: #fff;
  border-radius: 50%;
  animation: twinkle 3s ease-in-out infinite;
  opacity: 0;
}
@keyframes twinkle {
  0%, 100% { opacity: 0; transform: scale(0.5); }
  50% { opacity: 1; transform: scale(1); }
}

/* ===== 流星 ===== */
.shooting-star {
  position: absolute;
  width: 2px; height: 2px;
  background: #fff;
  border-radius: 50%;
  z-index: 0;
}
.shooting-star::before {
  content: '';
  position: absolute;
  width: 80px; height: 1px;
  background: linear-gradient(to right, #fff, transparent);
  right: 0; top: 0;
}
.s1 {
  top: 15%; left: -5%;
  animation: shoot 6s linear infinite;
  animation-delay: 2s;
}
.s2 {
  top: 45%; left: -5%;
  animation: shoot 8s linear infinite;
  animation-delay: 5s;
}
.s3 {
  top: 75%; left: -5%;
  animation: shoot 10s linear infinite;
  animation-delay: 8s;
}
@keyframes shoot {
  0% { transform: translateX(0) translateY(0) rotate(-35deg); opacity: 0; }
  5% { opacity: 1; }
  30% { transform: translateX(70vw) translateY(35vh) rotate(-35deg); opacity: 0; }
  100% { transform: translateX(70vw) translateY(35vh) rotate(-35deg); opacity: 0; }
}

/* ===== 行星 ===== */
.planet {
  position: absolute;
  border-radius: 50%;
  z-index: 0;
  animation: planetFloat 20s ease-in-out infinite;
}
.planet-1 {
  width: 90px; height: 90px;
  background: radial-gradient(circle at 30% 30%, #a78bfa, #7c3aed, #4c1d95);
  top: 6%; right: 6%;
  animation-delay: 0s;
}
.planet-1 .planet-ring {
  position: absolute;
  width: 150px; height: 36px;
  border: 2px solid rgba(167, 139, 250, 0.3);
  border-radius: 50%;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%) rotate(-20deg);
  animation: ringSpin 12s linear infinite;
}
@keyframes ringSpin {
  from { transform: translate(-50%, -50%) rotate(-20deg); }
  to { transform: translate(-50%, -50%) rotate(340deg); }
}
.planet-2 {
  width: 55px; height: 55px;
  background: radial-gradient(circle at 35% 35%, #60a5fa, #3b82f6, #1d4ed8);
  bottom: 18%; left: 5%;
  animation-delay: 5s;
  animation-duration: 15s;
}
.planet-3 {
  width: 30px; height: 30px;
  background: radial-gradient(circle at 35% 35%, #fbbf24, #f59e0b, #b45309);
  top: 50%; right: 12%;
  animation-delay: 8s;
  animation-duration: 18s;
}
@keyframes planetFloat {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  25% { transform: translateY(-12px) rotate(2deg); }
  50% { transform: translateY(-6px) rotate(0deg); }
  75% { transform: translateY(8px) rotate(-2deg); }
}

/* ===== 飞船 ===== */
.ship {
  position: absolute;
  z-index: 0;
  animation: shipFly linear infinite;
}
.ship-1 {
  top: 20%;
  animation-duration: 20s;
  animation-delay: 0s;
  animation-name: shipFlyRight;
}
.ship-2 {
  top: 65%;
  animation-duration: 25s;
  animation-delay: 12s;
  animation-name: shipFlyLeft;
}
.ship-body {
  width: 40px; height: 14px;
  background: linear-gradient(180deg, #94a3b8, #64748b, #475569);
  border-radius: 50% 50% 50% 50% / 80% 80% 20% 20%;
  position: relative;
}
.ship-cockpit {
  width: 14px; height: 8px;
  background: linear-gradient(180deg, #67e8f9, #22d3ee);
  border-radius: 50%;
  position: absolute;
  top: -6px; left: 50%;
  transform: translateX(-50%);
  box-shadow: 0 0 6px rgba(103, 232, 249, 0.6);
}
.ship-flame {
  position: absolute;
  bottom: -10px; left: 50%;
  transform: translateX(-50%);
  width: 6px; height: 12px;
  background: linear-gradient(to bottom, #fbbf24, #f97316, transparent);
  border-radius: 0 0 50% 50%;
  animation: flame 0.3s ease-in-out infinite alternate;
}
@keyframes flame {
  from { height: 8px; opacity: 0.8; }
  to { height: 14px; opacity: 1; }
}
@keyframes shipFlyRight {
  0% { left: -60px; transform: translateY(0) rotate(-5deg); }
  20% { transform: translateY(-10px) rotate(3deg); }
  40% { transform: translateY(5px) rotate(-2deg); }
  60% { transform: translateY(-8px) rotate(4deg); }
  80% { transform: translateY(3px) rotate(-3deg); }
  100% { left: 110%; transform: translateY(0) rotate(5deg); }
}
@keyframes shipFlyLeft {
  0% { right: -60px; transform: translateY(0) rotate(5deg) scaleX(-1); }
  20% { transform: translateY(8px) rotate(-3deg) scaleX(-1); }
  40% { transform: translateY(-6px) rotate(2deg) scaleX(-1); }
  60% { transform: translateY(10px) rotate(-4deg) scaleX(-1); }
  80% { transform: translateY(-4px) rotate(3deg) scaleX(-1); }
  100% { right: 110%; transform: translateY(0) rotate(-5deg) scaleX(-1); }
}

/* ===== 光斑 ===== */
.bg-circle {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.2;
  animation: float 10s ease-in-out infinite;
  z-index: 0;
}
.bg-circle-1 {
  width: 350px; height: 350px;
  background: #7c3aed;
  top: -80px; left: -80px;
  animation-delay: 0s;
}
.bg-circle-2 {
  width: 250px; height: 250px;
  background: #4f46e5;
  bottom: 5%; right: -60px;
  animation-delay: 3s;
}
.bg-circle-3 {
  width: 180px; height: 180px;
  background: #c026d3;
  top: 40%; right: 20%;
  animation-delay: 6s;
}
.bg-circle-4 {
  width: 200px; height: 200px;
  background: #2563eb;
  bottom: -40px; left: 20%;
  animation-delay: 9s;
}
@keyframes float {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-30px) scale(1.08); }
}

/* ===== 登录卡片 ===== */
.login-card {
  width: 420px;
  padding: 36px 32px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255,255,255,0.08);
  position: relative;
  z-index: 1;
}

/* ===== 卡通角色 ===== */
.characters {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  gap: 6px;
  margin-bottom: 28px;
}

.char {
  border-radius: 12px 12px 0 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
  transition: transform 0.2s;
  animation: bounce 3s ease-in-out infinite;
}
.char:hover { transform: translateY(-4px); }

.char-orange {
  width: 52px; height: 44px;
  background: #f97316;
  border-radius: 50% 50% 0 0 / 100% 100% 0 0;
  animation-delay: 0s;
  animation-duration: 2.8s;
}
.char-purple {
  width: 38px; height: 72px;
  background: #7c3aed;
  border-radius: 12px 12px 0 0;
  animation-delay: 0.3s;
  animation-duration: 3.2s;
}
.char-black {
  width: 40px; height: 52px;
  background: #1e1e2e;
  border-radius: 10px 10px 0 0;
  animation-delay: 0.6s;
  animation-duration: 2.6s;
}
.char-yellow {
  width: 48px; height: 48px;
  background: #eab308;
  border-radius: 50% 50% 0 0 / 80% 80% 0 0;
  animation-delay: 0.9s;
  animation-duration: 3s;
}

@keyframes bounce {
  0%, 100% { transform: translateY(0) scaleY(1); }
  15% { transform: translateY(-6px) scaleY(0.96); }
  30% { transform: translateY(0) scaleY(1); }
  45% { transform: translateY(-3px) scaleY(0.98); }
  60% { transform: translateY(0) scaleY(1); }
}

.char-eyes {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.char-orange .char-eyes,
.char-yellow .char-eyes {
  margin-top: 14px;
}

.eye {
  width: 12px; height: 12px;
  background: #fff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.char-orange .eye,
.char-yellow .eye {
  width: 10px; height: 10px;
}

.pupil {
  width: 5px; height: 5px;
  background: #1e1e2e;
  border-radius: 50%;
  transition: transform 0.08s linear;
}

.char-mouth {
  width: 16px; height: 2px;
  background: #a16207;
  border-radius: 1px;
  margin-top: 6px;
}

/* ===== 标题区 ===== */
.login-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}
.login-logo {
  width: 58px; height: 58px;
  object-fit: contain;
  border-radius: 12px;
}
.login-title {
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  margin: 0 0 4px;
  text-shadow: 0 0 20px rgba(124, 58, 237, 0.4);
}
.login-sub {
  color: rgba(255, 255, 255, 0.4);
  font-size: 13px;
}

/* ===== 输入框 ===== */
:deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  box-shadow: none;
  padding: 0 16px;
  transition: all 0.3s;
}
:deep(.el-input__wrapper:hover) {
  border-color: rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.07);
}
:deep(.el-input__wrapper.is-focus) {
  border-color: #7c3aed;
  box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.12), 0 0 12px rgba(124, 58, 237, 0.15);
  background: rgba(255, 255, 255, 0.08);
}
:deep(.el-input__inner) {
  color: #fff;
  height: 46px;
}
:deep(.el-input__inner::placeholder) {
  color: rgba(255, 255, 255, 0.3);
}
:deep(.el-input__prefix-inner) {
  color: rgba(255, 255, 255, 0.35);
}
:deep(.el-input__suffix-inner) {
  color: rgba(255, 255, 255, 0.35);
}
:deep(.el-input__password) {
  color: rgba(255, 255, 255, 0.35);
}

/* ===== 按钮 ===== */
:deep(.el-button--primary) {
  height: 46px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 4px;
  background: linear-gradient(135deg, #4f46e5, #7c3aed, #c026d3);
  background-size: 200% 200%;
  border: none;
  transition: all 0.4s;
  animation: btnGlow 3s ease-in-out infinite;
}
@keyframes btnGlow {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}
:deep(.el-button--primary:hover) {
  background: linear-gradient(135deg, #6366f1, #8b5cf6, #a855f7);
  box-shadow: 0 4px 20px rgba(124, 58, 237, 0.4), 0 0 40px rgba(124, 58, 237, 0.15);
  transform: translateY(-2px);
}
:deep(.el-button--primary:active) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.login-sub {
  color: rgba(255, 255, 255, 0.3);
  font-size: 12px;
}
</style>
