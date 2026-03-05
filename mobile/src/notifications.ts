/**
 * P12-9 — 推播通知模組
 *
 * 使用 Expo Notifications (expo-notifications)。
 * 支援事件類型：
 *   - batch_completed  批次處理完成
 *   - review_pending   新增待審核文件
 *   - system_alert     系統告警（CPU/記憶體/磁碟）
 *
 * 流程：
 *   1. App 啟動 → 請求通知權限
 *   2. 取得 Expo Push Token
 *   3. 向後端 POST /users/me/push-token 登記
 *   4. 後端透過 Expo Push API 推送通知
 *   5. App 前景收到通知 → 顯示 Alert
 */
import { useEffect, useRef } from 'react'
import { Platform, Alert } from 'react-native'
import * as Notifications from 'expo-notifications'
import * as Device from 'expo-device'
import Constants from 'expo-constants'
import api from './api'
import { navigateFromOutside } from './navigation/navigationRef'

// ── 通知外觀設定 ──────────────────────────────────────────────────────────────

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
})

// ── 取得並登記 Push Token ─────────────────────────────────────────────────────

export async function registerForPushNotifications(): Promise<string | null> {
  // 需要實體裝置（模擬器無法收 push）
  if (!Device.isDevice) {
    console.log('[Notifications] 推播通知需要實體裝置，模擬器略過')
    return null
  }

  // 請求權限
  const { status: existingStatus } = await Notifications.getPermissionsAsync()
  let finalStatus = existingStatus

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync()
    finalStatus = status
  }

  if (finalStatus !== 'granted') {
    console.log('[Notifications] 使用者拒絕推播通知權限')
    return null
  }

  // Android 需要建立通知頻道
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('enclave-default', {
      name: 'Enclave 通知',
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#2563EB',
    })

    await Notifications.setNotificationChannelAsync('enclave-alerts', {
      name: 'Enclave 系統告警',
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 500, 200, 500],
      lightColor: '#EF4444',
    })
  }

  try {
    // 取得 Expo Push Token
    const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId
    const { data: token } = await Notifications.getExpoPushTokenAsync({
      projectId: projectId ?? 'enclave-mobile',
    })

    // 向後端登記
    await api.post('/mobile/users/me/push-token', { push_token: token, platform: Platform.OS })
    console.log('[Notifications] Push token 已登記:', token)
    return token
  } catch (err) {
    console.warn('[Notifications] Token 登記失敗:', err)
    return null
  }
}

// ── 取消登記（登出時呼叫）────────────────────────────────────────────────────

export async function unregisterPushNotifications(): Promise<void> {
  try {
    await api.delete('/mobile/users/me/push-token')
  } catch {
    // ignore
  }
}

// ── 通知訊息對應表 ────────────────────────────────────────────────────────────

const NOTIFICATION_TITLES: Record<string, string> = {
  batch_completed: '✅ 批次處理完成',
  review_pending: '📋 有新文件待審核',
  system_alert: '⚠️ 系統告警',
}

// ── React Hook：在 App.tsx 中使用 ─────────────────────────────────────────────

export function useNotifications(isLoggedIn: boolean) {
  const notificationListener = useRef<ReturnType<typeof Notifications.addNotificationReceivedListener>>()
  const responseListener = useRef<ReturnType<typeof Notifications.addNotificationResponseReceivedListener>>()

  useEffect(() => {
    if (!isLoggedIn) return

    // 登入後登記推播
    registerForPushNotifications()

    // 監聽前景通知（App 在前台時收到）
    notificationListener.current = Notifications.addNotificationReceivedListener((notification) => {
      const { title, body, data } = notification.request.content
      const eventType = (data?.event_type as string) ?? ''
      const displayTitle = NOTIFICATION_TITLES[eventType] || title || 'Enclave 通知'
      if (body) {
        Alert.alert(displayTitle, body)
      }
    })

    // 監聽使用者點擊通知（背景/已關閉時收到並點擊）
    responseListener.current = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = response.notification.request.content.data
      const eventType = (data?.event_type as string) ?? ''
      console.log('[Notifications] 使用者點擊通知:', eventType, data)

      // P12-9: 根據事件類型導航至對應頁面
      switch (eventType) {
        case 'batch_completed':
          // 導航到進度儀表板 tab
          navigateFromOutside('Main', { screen: 'ProgressDashboard' })
          break
        case 'review_pending':
          // 導航到審核佇列 tab
          navigateFromOutside('Main', { screen: 'ReviewQueue' })
          break
        case 'system_alert':
          Alert.alert(
            '⚠️ 系統告警',
            (data?.message as string) ?? '系統影響為級事件，請檢查儀表板',
          )
          break
      }
    })

    return () => {
      if (notificationListener.current) {
        Notifications.removeNotificationSubscription(notificationListener.current)
      }
      if (responseListener.current) {
        Notifications.removeNotificationSubscription(responseListener.current)
      }
    }
  }, [isLoggedIn])
}

// ── 本機排程通知（用於測試）──────────────────────────────────────────────────

export async function scheduleTestNotification(): Promise<void> {
  await Notifications.scheduleNotificationAsync({
    content: {
      title: '✅ 批次處理完成',
      body: '本次批次已入庫 23 份文件，0 份失敗。',
      data: { event_type: 'batch_completed' },
    },
    trigger: { seconds: 2 },
  })
}
