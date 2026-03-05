/**
 * P12-9 — 全域 Navigation Ref
 *
 * 用於在 React 元件外部（如 notifications.ts）觸發頁面導航。
 * 使用方式：在 AppNavigator 的 NavigationContainer 上掛載 ref。
 */
import { createNavigationContainerRef } from '@react-navigation/native'
import type { RootStackParamList } from './AppNavigator'

export const navigationRef = createNavigationContainerRef<RootStackParamList>()

/**
 * 在任意處呼叫，安全導航至指定 Screen。
 * 若 NavigationContainer 尚未掛載則忽略。
 */
export function navigateFromOutside(name: keyof RootStackParamList, params?: object) {
  if (navigationRef.isReady()) {
    // @ts-ignore — params type varies per screen
    navigationRef.navigate(name, params)
  }
}
