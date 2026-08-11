import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
      <Toaster position="top-right" toastOptions={{ duration: 3000 }} />
    </BrowserRouter>
  </React.StrictMode>,
)

// PWA：註冊 service worker（app shell 離線快取；僅 production 避免 dev 快取干擾）
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register(`/sw.js?build=${encodeURIComponent(__PWA_BUILD_ID__)}`)
      .catch(() => {
        // 註冊失敗不影響線上使用
      })
  })
}
