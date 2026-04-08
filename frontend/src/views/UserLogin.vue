<template>
  <div class="login-container">
    <el-card class="login-card">
      <template #header>
        <div class="card-header">
          <span>{{ isLogin ? '智诊助手登录' : '智诊助手注册' }}</span>
        </div>
      </template>
      <el-form :model="form" :rules="rules" ref="formRef" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="请输入用户名"></el-input>
        </el-form-item>
        <el-form-item v-if="!isLogin" label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱"></el-input>
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input 
            :type="showPassword ? 'text' : 'password'" 
            v-model="form.password" 
            placeholder="请输入密码"
            :suffix-icon="showPassword ? 'el-icon-view' : 'el-icon-view'
          " @click-suffix="showPassword = !showPassword"></el-input>
          <div v-if="!isLogin" class="password-strength">
            <div class="strength-text">密码强度: {{ getStrengthText(passwordStrength) }}</div>
            <div class="strength-bar">
              <div :class="['strength-level', 'strength-' + passwordStrength]"></div>
            </div>
          </div>
        </el-form-item>
        <el-form-item v-if="!isLogin" label="确认密码" prop="confirmPassword">
          <el-input 
            :type="showConfirmPassword ? 'text' : 'password'" 
            v-model="form.confirmPassword" 
            placeholder="请确认密码"
            :suffix-icon="showConfirmPassword ? 'el-icon-view' : 'el-icon-view'
          " @click-suffix="showConfirmPassword = !showConfirmPassword"></el-input>
        </el-form-item>
        <el-form-item v-if="isLogin" label="验证码" prop="verifyCode">
          <div class="verify-code-wrapper">
            <el-input v-model="form.verifyCode" placeholder="请输入验证码" class="verify-code-input"></el-input>
            <VueCanvasVerify ref="canvasVerifyRef" @getCode="handleCodeChange"
                             :width="120" :height="40" class="canvas-verify-code"></VueCanvasVerify>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSubmit" :loading="loading">{{ isLogin ? '登录' : '注册' }}</el-button>
        </el-form-item>
        <el-form-item class="form-switch">
          <span v-if="isLogin">没有账号？</span>
          <span v-else>已有账号？</span>
          <el-button type="text" @click="toggleForm">{{ isLogin ? '立即注册' : '立即登录' }}</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import VueCanvasVerify from '../components/VueCanvasVerify.vue';

const router = useRouter();
const formRef = ref(null);
const canvasVerifyRef = ref(null);
const isLogin = ref(true);
const showPassword = ref(false);
const showConfirmPassword = ref(false);
const loading = ref(false);
const currentVerifyCode = ref('');

const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
  verifyCode: ''
});

const passwordStrength = computed(() => {
  const password = form.password;
  if (!password) return 0;
  let strength = 0;
  if (password.length >= 8) strength++;
  if (/[A-Z]/.test(password)) strength++;
  if (/[a-z]/.test(password)) strength++;
  if (/[0-9]/.test(password)) strength++;
  if (/[^A-Za-z0-9]/.test(password)) strength++;
  return strength;
});

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 15, message: '长度在 3 到 15 个字符', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱格式', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 20, message: '长度在 8 到 20 个字符', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (!/(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9])(?=.*[^A-Za-z0-9])/.test(value)) {
          callback(new Error('密码必须包含大小写字母、数字和特殊字符'));
        } else {
          callback();
        }
      },
      trigger: 'blur'
    }
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (value !== form.password) {
          callback(new Error('两次输入的密码不一致'));
        } else {
          callback();
        }
      },
      trigger: 'blur'
    }
  ],
  verifyCode: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (!currentVerifyCode.value) {
          callback(new Error('验证码未生成，请刷新页面或检查组件！'));
        } else if (value.toLowerCase() !== currentVerifyCode.value.toLowerCase()) {
          callback(new Error('验证码不正确'));
          form.verifyCode = '';
        } else {
          callback();
        }
      },
      trigger: 'blur'
    }
  ]
};

const handleCodeChange = (code) => {
  currentVerifyCode.value = code;
};

const toggleForm = () => {
  isLogin.value = !isLogin.value;
  // 重置表单
  form.username = '';
  form.email = '';
  form.password = '';
  form.confirmPassword = '';
  form.verifyCode = '';
  if (formRef.value) {
    formRef.value.resetFields();
  }
};

const getStrengthText = (strength) => {
  switch (strength) {
    case 0:
      return '请输入密码';
    case 1:
      return '弱';
    case 2:
      return '较弱';
    case 3:
      return '中等';
    case 4:
      return '强';
    case 5:
      return '很强';
    default:
      return '';
  }
};

const handleSubmit = () => {
  formRef.value.validate(async (valid) => {
    if (valid) {
      loading.value = true;
      try {
        if (isLogin.value) {
          // 登录逻辑
          const response = await fetch('http://localhost:5000/api/login', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              username: form.username,
              password: form.password
            })
          });
          
          const data = await response.json();
          if (data.success) {
            ElMessage.success('登录成功！');
            localStorage.setItem('token', data.token);
            localStorage.setItem('username', data.username);
            router.push('/index');
          } else {
            ElMessage.error(data.message || '登录失败！');
          }
        } else {
          // 注册逻辑
          const response = await fetch('http://localhost:5000/api/register', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json'
            },
            body: JSON.stringify({
              username: form.username,
              email: form.email,
              password: form.password
            })
          });
          
          const data = await response.json();
          if (data.success) {
            ElMessage.success('注册成功！请登录');
            toggleForm();
          } else {
            ElMessage.error(data.message || '注册失败！');
          }
        }
      } catch (error) {
        ElMessage.error('网络错误，请稍后重试');
        console.error(error);
      } finally {
        loading.value = false;
      }
    } else {
      ElMessage.error('请检查输入信息！');
      return false;
    }
  });
};
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background-color: #f0f2f5;
}
.login-card {
  width: 400px;
  padding: 20px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}
.card-header {
  text-align: center;
  font-size: 20px;
  font-weight: bold;
  margin-bottom: 20px;
}
.verify-code-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
}
.verify-code-input {
  flex-grow: 1;
}
.canvas-verify-code {
  width: 120px;
  height: 40px;
  cursor: pointer;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background-color: #f5f5f5;
}
.form-switch {
  text-align: center;
  margin-top: 10px;
}
.password-strength {
  margin-top: 5px;
  font-size: 12px;
}
.strength-bar {
  height: 4px;
  background-color: #f0f0f0;
  border-radius: 2px;
  margin-top: 5px;
  overflow: hidden;
}
.strength-level {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}
.strength-1 { background-color: #ff4d4f; width: 20%; }
.strength-2 { background-color: #faad14; width: 40%; }
.strength-3 { background-color: #faad14; width: 60%; }
.strength-4 { background-color: #52c41a; width: 80%; }
.strength-5 { background-color: #52c41a; width: 100%; }
</style>