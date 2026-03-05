/**
 * Enclave Mobile — App entry point
 *
 * Phase 12 P12-1: Project scaffold
 * P12-9:          Push notification bootstrap
 *
 * Wraps the entire app in AuthProvider and renders AppNavigator.
 * AppNavigator decides Login vs Main based on auth state.
 *
 * AppContent sits inside AuthProvider so it can read auth state
 * and activate push notification registration once the user is
 * logged in.
 */
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { useEffect } from 'react'
import { AuthProvider, useAuth } from './src/auth'
import AppNavigator from './src/navigation/AppNavigator'
import { useNotifications } from './src/notifications'
import { performCertPinningCheck } from './src/api'

/**
 * Inner component so we can access AuthContext and the notification
 * hook together (hooks must be inside the Provider tree).
 */
function AppContent() {
  const { token } = useAuth()
  // Registers for push permissions / token when logged in,
  // and cleans up listeners on logout.
  useNotifications(!!token)

  // P12-11: SSL 證書指紋驗證（登入後執行一次）
  useEffect(() => {
    if (token) {
      performCertPinningCheck().catch(() => {
        // cert pinning failure is logged inside performCertPinningCheck
      })
    }
  }, [token])

  return <AppNavigator />
}

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </SafeAreaProvider>
  )
}
