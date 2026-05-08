<template>
  <div class="documents-container">
    <van-nav-bar :title="$t('documents.title')" fixed />

    <div class="documents-content">
      <!-- 上传区域 -->
      <div class="upload-section">
        <h4 class="section-title">{{ $t('documents.uploadTitle') }}</h4>
        <p class="section-hint">{{ $t('documents.uploadHint') }}</p>

        <div class="upload-area">
          <!-- 隐藏的原生文件输入 -->
          <input
            ref="fileInputRef"
            type="file"
            multiple
            accept=".txt,.pdf,.md,.docx"
            class="file-input-hidden"
            :disabled="uploading"
            @change="onFilesSelected"
          />

          <!-- 已选文件列表 -->
          <div v-if="fileList.length > 0" class="selected-files">
            <div v-for="(file, index) in fileList" :key="index" class="selected-file-item">
              <van-icon :name="getFileIcon(file.name)" size="20" />
              <span class="file-name">{{ file.name }}</span>
              <span class="file-size">{{ formatSize(file.size) }}</span>
              <van-icon
                name="cross"
                size="16"
                class="remove-icon"
                @click="removeSelectedFile(index)"
              />
            </div>
          </div>

          <!-- 上传触发按钮 -->
          <div
            class="upload-trigger"
            :class="{ 'upload-trigger--disabled': uploading }"
            @click="triggerFileSelect"
          >
            <van-icon name="plus" size="28" />
            <span class="upload-trigger-text">{{ $t('documents.selectFile') }}</span>
          </div>

          <div class="upload-tip">{{ $t('documents.formatHint') }}</div>
        </div>
      </div>

      <!-- 上传按钮 -->
      <div class="upload-actions" v-if="fileList.length > 0">
        <van-button
          type="primary"
          :loading="uploading"
          :loading-text="$t('documents.uploading')"
          block
          round
          @click="handleUpload"
        >
          {{ $t('documents.upload') }} ({{ fileList.length }})
        </van-button>
      </div>

      <!-- 向量库中的文档 -->
      <div class="stored-section">
        <h4 class="section-title">{{ $t('documents.storedTitle') }}</h4>
        <p class="section-hint">
          {{ $t('documents.storedHint', { count: storedDocuments.total_chunks || 0 }) }}
        </p>

        <van-loading v-if="storedLoading" class="stored-loading" />

        <van-empty
          v-if="!storedLoading && storedDocuments.filenames && storedDocuments.filenames.length === 0"
          :description="$t('documents.noStoredFiles')"
        />

        <div v-if="!storedLoading && storedDocuments.filenames && storedDocuments.filenames.length > 0" class="stored-list">
          <div v-for="(name, index) in storedDocuments.filenames" :key="index" class="stored-item">
            <van-icon :name="getFileIcon(name)" size="20" />
            <span class="stored-name">{{ name }}</span>
            <van-tag type="success" size="small">{{ $t('documents.stored') }}</van-tag>
          </div>
        </div>

        <van-button
          size="small"
          plain
          icon="replay"
          :loading="storedLoading"
          @click="loadStoredDocuments"
        >
          {{ $t('documents.refresh') }}
        </van-button>
      </div>

      <!-- 上传历史 -->
      <van-cell-group inset class="history-section" v-if="uploadedFiles.length > 0">
        <van-cell
          :title="$t('documents.historyTitle')"
          :value="`${uploadedFiles.length} ${$t('documents.files')}`"
        />

        <van-swipe-cell
          v-for="(file, index) in uploadedFiles"
          :key="index"
        >
          <van-cell
            :title="file.name"
            :label="file.time"
            :icon="getFileIcon(file.name)"
            center
          >
            <template #value>
              <van-tag :type="file.status === 'success' ? 'success' : 'danger'" size="small">
                {{ file.status === 'success' ? $t('documents.uploadSuccess') : $t('documents.uploadFailed') }}
              </van-tag>
            </template>
          </van-cell>
          <template #right>
            <van-button
              type="danger"
              size="small"
              @click="removeFile(index)"
            >
              {{ $t('common.delete') }}
            </van-button>
          </template>
        </van-swipe-cell>
      </van-cell-group>

      <!-- 清空所有向量 -->
      <div class="clean-section" v-if="uploadedFiles.length > 0">
        <van-button
          type="danger"
          plain
          block
          round
          @click="handleCleanAll"
        >
          {{ $t('documents.cleanAll') }}
        </van-button>
      </div>
    </div>

    <tab-bar />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { showToast, showDialog, showLoadingToast } from 'vant'
import axios from 'axios'
import { apiConfig } from '../config/api'
import { useI18n } from 'vue-i18n'
import TabBar from '../components/TabBar.vue'

const { t } = useI18n()

const fileInputRef = ref(null)
const fileList = ref([])
const uploadedFiles = ref(loadUploadHistory())
const uploading = ref(false)
const storedDocuments = ref({ filenames: [], total_chunks: 0 })
const storedLoading = ref(false)

const ALLOWED_EXTS = ['.txt', '.pdf', '.md', '.docx']
const MAX_FILE_SIZE = 20 * 1024 * 1024

function loadUploadHistory() {
  try {
    const data = localStorage.getItem('upload_history')
    return data ? JSON.parse(data) : []
  } catch {
    return []
  }
}

function saveUploadHistory() {
  localStorage.setItem('upload_history', JSON.stringify(uploadedFiles.value.slice(-50)))
}

async function loadStoredDocuments() {
  storedLoading.value = true
  const token = localStorage.getItem('jwt_token')
  if (!token) {
    storedLoading.value = false
    return
  }
  try {
    const response = await axios.get(apiConfig.endpoints.listUserVectors, {
      headers: { Authorization: `Bearer ${token}` }
    })
    if (response.data?.code === 200 && response.data?.data) {
      storedDocuments.value = response.data.data
    }
  } catch (error) {
    console.error('加载已存储文档失败:', error)
  } finally {
    storedLoading.value = false
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function getFileIcon(name) {
  const ext = name.split('.').pop()?.toLowerCase()
  const icons = { pdf: 'description-o', txt: 'notes-o', md: 'bookmark-o', docx: 'doc-o' }
  return icons[ext] || 'file-o'
}

function triggerFileSelect() {
  if (uploading.value) return
  fileInputRef.value?.click()
}

function onFilesSelected(e) {
  const files = Array.from(e.target.files || [])
  if (files.length === 0) return

  const validFiles = []
  for (const file of files) {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ALLOWED_EXTS.includes(ext)) {
      showToast(`${file.name}: ${t('documents.invalidFormat')}`)
      continue
    }
    if (file.size > MAX_FILE_SIZE) {
      showToast(`${file.name}: ${t('documents.fileTooLarge')}`)
      continue
    }
    if (fileList.value.length + validFiles.length >= 5) {
      showToast(t('documents.maxFilesReached', { max: 5 }))
      break
    }
    validFiles.push(file)
  }

  if (validFiles.length > 0) {
    fileList.value = [...fileList.value, ...validFiles]
  }

  // 清除 input 的 value，使重复选同一个文件也能触发 change
  e.target.value = ''
}

function removeSelectedFile(index) {
  fileList.value.splice(index, 1)
}

async function handleUpload() {
  if (fileList.value.length === 0) {
    showToast(t('documents.noPendingFiles'))
    return
  }

  uploading.value = true
  const toast = showLoadingToast({
    message: t('documents.uploading'),
    forbidClick: true,
    duration: 0
  })

  const token = localStorage.getItem('jwt_token')
  if (!token) {
    toast.close()
    showToast(t('documents.needLogin'))
    uploading.value = false
    return
  }

  const headers = {
    Authorization: `Bearer ${token}`
  }

  let successCount = 0
  const uploaded = []

  for (const file of fileList.value) {
    const formData = new FormData()
    formData.append('file', file)

    try {
      await axios.post(apiConfig.endpoints.uploadSingleFile, formData, { headers })
      successCount++
      uploaded.push({
        name: file.name,
        time: new Date().toLocaleString(),
        status: 'success'
      })
    } catch (error) {
      console.error(`上传 ${file.name} 失败:`, error)
      uploaded.push({
        name: file.name,
        time: new Date().toLocaleString(),
        status: 'failed'
      })
    }
  }

  uploadedFiles.value = [...uploaded, ...uploadedFiles.value]
  saveUploadHistory()

  fileList.value = []

  toast.close()

  if (successCount === uploaded.length) {
    showToast(t('documents.uploadAllSuccess'))
  } else if (successCount > 0) {
    showToast(`${successCount}/${uploaded.length} ` + t('documents.uploadPartialSuccess'))
  } else {
    showToast(t('documents.uploadAllFailed'))
  }

  uploading.value = false

  // 刷新向量库文档列表
  loadStoredDocuments()
}

function removeFile(index) {
  uploadedFiles.value.splice(index, 1)
  saveUploadHistory()
}

async function handleCleanAll() {
  try {
    await showDialog({
      title: t('documents.cleanAllTitle'),
      message: t('documents.cleanAllConfirm'),
      showCancelButton: true,
      confirmButtonText: t('common.confirm'),
      cancelButtonText: t('common.cancel')
    })
  } catch {
    return
  }

  const token = localStorage.getItem('jwt_token')
  if (!token) {
    showToast(t('documents.needLogin'))
    return
  }

  const toast = showLoadingToast({
    message: t('common.loading'),
    forbidClick: true,
    duration: 0
  })

  try {
    await axios.delete(apiConfig.endpoints.cleanVectors, {
      headers: { Authorization: `Bearer ${token}` }
    })
    uploadedFiles.value = []
    saveUploadHistory()
    storedDocuments.value = { filenames: [], total_chunks: 0 }
    toast.close()
    showToast(t('documents.cleanAllSuccess'))
  } catch (error) {
    toast.close()
    showToast(error.response?.data?.detail || t('documents.cleanAllFailed'))
  }
}

onMounted(() => {
  loadStoredDocuments()
})
</script>

<style scoped>
.documents-container {
  min-height: 100vh;
  background-color: var(--background-color, #f7f8fa);
  padding-top: 46px;
  padding-bottom: 60px;
  box-sizing: border-box;
}

.documents-content {
  padding: 12px 0;
}

.upload-section {
  background: #fff;
  margin: 0 16px 12px;
  border-radius: 8px;
  padding: 16px;
}

.section-title {
  margin: 0 0 4px;
  font-size: 16px;
  font-weight: 600;
  color: #323233;
}

.section-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: #969799;
}

.upload-area {
  margin-top: 8px;
}

/* 隐藏原生文件输入 */
.file-input-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

/* 已选文件列表 */
.selected-files {
  margin-bottom: 12px;
}

.selected-file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f7f8fa;
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 14px;
}

.selected-file-item .file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #323233;
}

.selected-file-item .file-size {
  color: #969799;
  font-size: 12px;
  flex-shrink: 0;
}

.selected-file-item .remove-icon {
  color: #969799;
  cursor: pointer;
  flex-shrink: 0;
}

.selected-file-item .remove-icon:hover {
  color: #ee0a24;
}

/* 上传触发按钮 */
.upload-trigger {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 80px;
  height: 80px;
  background: #f7f8fa;
  border: 2px dashed #dcdee0;
  border-radius: 8px;
  color: #969799;
  gap: 8px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  user-select: none;
}

.upload-trigger:hover {
  border-color: #1989fa;
}

.upload-trigger:active {
  background: #ebedf0;
}

.upload-trigger--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.upload-trigger-text {
  font-size: 12px;
  color: #969799;
}

.upload-tip {
  padding: 8px 0 0;
  font-size: 12px;
  color: #969799;
}

/* 向量库已存储文档 */
.stored-section {
  background: #fff;
  margin: 0 16px 12px;
  border-radius: 8px;
  padding: 16px;
}

.stored-loading {
  display: flex;
  justify-content: center;
  padding: 24px 0;
}

.stored-list {
  margin: 8px 0 12px;
}

.stored-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f7f8fa;
  border-radius: 6px;
  margin-bottom: 6px;
  font-size: 14px;
}

.stored-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #323233;
}

.upload-actions {
  padding: 0 16px;
  margin-bottom: 16px;
}

.history-section {
  margin-bottom: 12px;
}

.clean-section {
  padding: 0 16px;
  margin-top: 20px;
}
</style>
