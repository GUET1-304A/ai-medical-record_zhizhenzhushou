<template>
  <!-- 移除 el-card 组件，直接使用 div 作为根容器 -->
  <h2 class="page-title">语音转文字</h2>
  <div class="speech-to-text-content">
    <div class="card-header"> <!-- 保持 card-header，作为页面标题样式 -->
    </div>
    <div class="recorder-controls">
      <el-button
        type="primary"
        :icon="Microphone"
        @click="startRecording"
        :disabled="isRecording"
      >
        开始录音
      </el-button>
      <el-button
        type="danger"
        :icon="VideoPause"
        @click="stopRecording"
        :disabled="!isRecording"
      >
        停止录音
      </el-button>
      <el-button
        type="success"
        :icon="Upload"
        @click="generateForm"
        :disabled="!transcribedText"
      >
        生成量化表 (基于转写结果)
      </el-button>
    </div>

    <!-- 新增：MP3 文件上传区域 -->
    <el-divider>或上传 MP3 文件</el-divider>
    <div class="upload-controls">
      <input type="file" ref="fileInput" @change="handleFileChange" accept="audio/mp3" style="display: none;">
      <el-button type="info" @click="triggerFileInput">
        选择 MP3 文件
      </el-button>
      <span v-if="selectedFile">{{ selectedFile.name }}</span>
      <el-button 
        type="success" 
        :icon="Upload" 
        @click="uploadSelectedFile" 
        :disabled="!selectedFile"
        style="margin-left: 10px;"
      >
        上传并转写 MP3
      </el-button>
    </div>
    <!-- 结束新增 -->

    <div v-if="transcribedText" class="transcribed-text-container">
      <h4>转写结果：</h4>
      <el-input
        type="textarea"
        :rows="20"
        v-model="transcribedText"
        placeholder="语音转写结果将显示在这里..."
        readonly
      ></el-input>
    </div>
    <div v-else class="transcribed-text-placeholder">
      <p>点击“开始录音”按钮，开始您的问诊对话，完成后点击“停止录音”。</p>
      <p>系统会将录音内容转换为文字，并自动填充到下方的文本框中。</p>
      <p>您也可以通过“选择 MP3 文件”按钮直接上传本地 MP3 音频进行转写。</p>
    </div>

    <el-dialog
      v-model="quantifiedFormDialogVisible"
      title="生成的量化表"
      width="70%"
      class="quantified-form-dialog"
    >
      <div v-if="generatedQuantifiedForm">
        <h4>量化表内容：</h4>
        <div class="dialog-content">
          <ul v-if="generatedQuantifiedForm">
            <li v-for="(value, key) in generatedQuantifiedForm" :key="key">
              <strong>{{ key }}：</strong>
              <span v-if="typeof value === 'object' && value !== null">
                <ul>
                  <li v-for="(subValue, subKey) in value" :key="subKey">
                    <strong style="margin-left: 15px;">{{ subKey }}：</strong>{{ subValue }}
                  </li>
                </ul>
              </span>
              <span v-else>{{ value }}</span>
            </li>
          </ul>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="quantifiedFormDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { ElLoading, ElMessage } from 'element-plus';
import axios from 'axios';
import { Microphone, VideoPause, Upload } from '@element-plus/icons-vue';

// 录音相关状态
let mediaStream = null; // 用于存储媒体流对象
const audioChunks = ref([]); // 存储录音数据块
const isRecording = ref(false); // 录音状态
const transcribedText = ref(''); // 转写结果
let loadingInstance = null; // Element Plus 加载服务的实例

// 新增：文件上传相关状态
const fileInput = ref(null); // 用于引用文件输入框
const selectedFile = ref(null); // 存储选中的文件

// 生成量化表弹窗相关
const quantifiedFormDialogVisible = ref(false);
const generatedQuantifiedForm = ref(null);

/**
 * 将音频数据上传到后端进行转写
 * @param {Blob|File} audioData 包含音频数据的 Blob 或 File 对象
 * @param {string} fileName 上传到后端的文件名
 */
const uploadAudio = async (audioData, fileName) => {
  // 显示加载提示
  loadingInstance = ElLoading.service({
    lock: true,
    text: '正在处理语音并进行转写，请稍候...',
    background: 'rgba(0, 0, 0, 0.7)',
  });

  try {
    const formData = new FormData();
    // audioData 可以是 Blob (来自录音) 也可以是 File (来自文件选择)
    formData.append('audio', audioData, fileName);

    const response = await axios.post('http://127.0.0.1:5000/transcribe-audio', formData);

    transcribedText.value = response.data.transcribedText;
    ElMessage.success('语音转写成功！');
  } catch (error) {
    console.error('语音转写失败:', error);
    let errorMessage = '后端转写失败，请检查后端日志。';
    if (error.response && error.response.data && error.response.data.error) {
      errorMessage = `后端转写失败: ${error.response.data.error}`;
    } else if (error.message) {
      errorMessage = `语音转写过程中发生错误: ${error.message}`;
    }
    ElMessage.error(errorMessage);
  } finally {
    // 无论成功或失败，最后都关闭加载提示
    if (loadingInstance) {
      loadingInstance.close();
    }
    audioChunks.value = []; // 清空录音数据块
    selectedFile.value = null; // 清空选中的文件
  }
};


/**
 * 开始录音
 */
const startRecording = async () => {
  transcribedText.value = ''; // 清空之前的转写结果
  audioChunks.value = []; // 清空之前的录音数据块
  selectedFile.value = null; // 清空选中的文件
  try {
    console.log('开始请求麦克风权限...');
    // 请求麦克风权限
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    console.log('麦克风权限获取成功:', mediaStream);

    // 检查音频上下文是否被暂停
    let audioContext;
    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      console.log('音频上下文创建成功:', audioContext);
    } catch (contextErr) {
      console.error('创建音频上下文失败:', contextErr);
      ElMessage.error('创建音频上下文失败，请检查浏览器兼容性。');
      return;
    }
    
    // 检查音频上下文状态
    if (audioContext.state === 'suspended') {
      await audioContext.resume();
      console.log('音频上下文已恢复');
    }

    try {
      // 使用MediaRecorder API作为替代方案，更兼容现代浏览器
      console.log('尝试使用MediaRecorder API...');
      
      // 检查浏览器是否支持MediaRecorder
      if (!window.MediaRecorder) {
        throw new Error('浏览器不支持MediaRecorder API');
      }
      
      // 尝试找到支持的音频格式
      let mimeType = 'audio/mp3';
      if (!MediaRecorder.isTypeSupported(mimeType)) {
        // 如果不支持MP3，尝试其他格式
        const supportedTypes = [
          'audio/webm;codecs=opus',
          'audio/webm',
          'audio/ogg;codecs=opus',
          'audio/ogg'
        ];
        
        for (const type of supportedTypes) {
          if (MediaRecorder.isTypeSupported(type)) {
            mimeType = type;
            console.log(`使用支持的音频格式: ${mimeType}`);
            break;
          }
        }
      }
      
      // 创建MediaRecorder实例
      const mediaRecorder = new MediaRecorder(mediaStream, { mimeType });
      console.log('MediaRecorder创建成功:', mediaRecorder);
      
      // 存储录音数据
      const audioChunks = [];
      
      // 处理数据可用事件
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunks.push(event.data);
          console.log('收到音频数据，大小:', event.data.size);
        }
      };
      
      // 处理录音结束事件
      mediaRecorder.onstop = async () => {
        console.log('录音停止，开始处理音频数据...');
        
        // 创建音频Blob
        const audioBlob = new Blob(audioChunks, { type: mimeType });
        console.log('音频Blob创建成功，大小:', audioBlob.size);
        
        // 调用上传函数处理音频数据
        await uploadAudio(audioBlob, 'recording.webm');
        console.log('音频上传完成');
      };
      
      // 开始录音
      mediaRecorder.start();
      console.log('录音开始成功');
      
      isRecording.value = true;
      ElMessage.success('开始录音...');
      
      // 保存recorder和数据，以便在停止录音时使用
      window.recordingData = {
        mediaRecorder,
        mediaStream,
        audioContext
      };
    } catch (audioErr) {
      console.error('音频处理初始化失败:', audioErr);
      ElMessage.error(`音频处理初始化失败: ${audioErr.message}`);
      // 清理媒体流
      if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
      }
    }
  } catch (err) {
    console.error('无法访问麦克风或录音失败:', err);
    // 更详细的错误信息
    if (err.name === 'NotAllowedError') {
      ElMessage.error('麦克风权限被拒绝，请在浏览器设置中允许麦克风访问。');
    } else if (err.name === 'NotFoundError') {
      ElMessage.error('未找到麦克风设备，请检查设备连接。');
    } else if (err.name === 'NotReadableError') {
      ElMessage.error('麦克风设备被占用，请关闭其他使用麦克风的应用。');
    } else {
      ElMessage.error(`无法开始录音: ${err.message}`);
    }
  }
};

/**
 * 停止录音
 */
const stopRecording = async () => {
  if (isRecording.value && window.recordingData) {
    console.log('开始停止录音...');
    const { mediaRecorder, mediaStream, audioContext } = window.recordingData;
    
    // 停止录音
    isRecording.value = false;
    console.log('录音状态已更新为停止');
    
    try {
      // 停止MediaRecorder
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
        console.log('MediaRecorder已停止');
      }
      
      // 停止媒体流
      if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        console.log('媒体流已停止');
      }
      
      // 关闭音频上下文
      if (audioContext) {
        await audioContext.close();
        console.log('音频上下文已关闭');
      }
      
      ElMessage.success('录音已停止，正在处理音频数据...');
    } catch (stopErr) {
      console.error('停止录音时出错:', stopErr);
      ElMessage.error('停止录音时出错，请重试。');
    } finally {
      // 清理
      delete window.recordingData;
      console.log('录音数据已清理');
    }
  } else {
    console.warn('没有正在进行的录音');
    ElMessage.warning('没有正在进行的录音');
  }
};

/**
 * 触发文件输入框点击
 */
const triggerFileInput = () => {
  fileInput.value.click();
};

/**
 * 处理文件选择
 * @param {Event} event 文件选择事件
 */
const handleFileChange = (event) => {
  const file = event.target.files[0];
  if (!file) {
    selectedFile.value = null;
    return;
  }
  
  // 检查文件格式
  if (!file.type === 'audio/mp3' && !file.name.endsWith('.mp3')) {
    selectedFile.value = null;
    ElMessage.error('请选择一个 MP3 格式的音频文件。');
    return;
  }
  
  // 检查文件大小（限制为10MB）
  const maxSize = 10 * 1024 * 1024; // 10MB
  if (file.size > maxSize) {
    selectedFile.value = null;
    ElMessage.error('文件大小不能超过10MB。');
    return;
  }
  
  selectedFile.value = file;
  transcribedText.value = ''; // 清空之前的转写结果
  ElMessage.info(`已选择文件: ${file.name}`);
};

/**
 * 上传选中的 MP3 文件
 */
const uploadSelectedFile = async () => {
  if (selectedFile.value) {
    await uploadAudio(selectedFile.value, selectedFile.value.name);
  } else {
    ElMessage.warning('请先选择一个 WAV 文件。');
  }
};


/**
 * 根据转写结果生成量化表
 */
const generateForm = async () => {
  if (!transcribedText.value) {
    ElMessage.warning('没有可用于生成量化表的转写内容！');
    return;
  }

  ElMessage.info('正在根据转写内容生成量化表...');
  try {
    const response = await axios.post('http://127.0.0.1:5000/generate-form', {
      conversation_text: transcribedText.value,
    }, {
      headers: {
        'Content-Type': 'application/json',
      },
    });

    generatedQuantifiedForm.value = response.data;
    quantifiedFormDialogVisible.value = true; // 显示量化表弹窗
    ElMessage.success('量化表生成成功！');
  } catch (error) {
    console.error('生成量化表失败:', error);
    let errorMessage = '生成量化表失败，请检查后端日志。';
    if (error.response && error.response.data && error.response.data.error) {
      errorMessage = `生成量化表失败: ${error.response.data.error}`;
    } else if (error.message) {
      errorMessage = `生成量化表过程中发生错误: ${error.message}`;
    }
    ElMessage.error(errorMessage);
    generatedQuantifiedForm.value = null;
  }
};
</script>

<style scoped>
.page-title {
  color: #333;
  margin-bottom: 20px;
  border-bottom: 1px solid #eee;
  padding-bottom: 10px;
}

.speech-to-text-content {
  /* 确保内容区域有与 main-content 相同的内边距，或根据需要调整 */
  padding: 0px; /* main-content 已经有20px padding，这里可以设为0或根据需要调整 */
  max-width: 100%; /* 确保占满父容器宽度 */
  margin: 0 auto; /* 居中内容 */
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 18px;
  font-weight: bold;
  padding-bottom: 15px;
  margin-bottom: 20px; /* 增加与下方内容的间距 */
}

.recorder-controls {
  margin-bottom: 20px;
  display: flex;
  justify-content: center; /* 按钮居中 */
  gap: 10px;
}

.upload-controls { /* 新增样式 */
  margin-top: 20px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: center; /* 上传控件居中 */
  gap: 10px;
  padding: 15px;
  border: 1px dashed #dcdfe6;
  border-radius: 8px;
  background-color: #f8f8f8;
}

.transcribed-text-container {
  margin-top: 20px;
}

.transcribed-text-container h4 {
  margin-bottom: 10px;
  color: #333;
}

.transcribed-text-placeholder {
  margin-top: 30px;
  padding: 20px;
  background-color: #f0f2f5;
  border-radius: 8px;
  text-align: center;
  color: #666;
  font-size: 15px;
  line-height: 1.8;
}

.transcribed-text-placeholder p:last-child {
  margin-bottom: 0;
}

/* 量化表弹窗样式 */
.quantified-form-dialog .el-dialog__header {
  border-bottom: 1px solid #eee;
  padding-bottom: 15px;
  margin-bottom: 15px;
}

.quantified-form-dialog h4 {
  color: #333;
  margin-top: 20px;
  margin-bottom: 10px;
  border-bottom: 1px dashed #ddd;
  padding-bottom: 5px;
}

.dialog-content {
  background-color: #f9f9f9;
  padding: 15px;
  border-radius: 5px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.6;
  color: #444;
  max-height: 400px;
  overflow-y: auto;
}

.dialog-content ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.dialog-content li {
  margin-bottom: 8px;
}
</style>
