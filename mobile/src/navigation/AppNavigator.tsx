/**
 * Root navigator — decides between Login and Main tabs
 * based on auth state.
 */
import { NavigationContainer } from '@react-navigation/native'
import { createNativeStackNavigator } from '@react-navigation/native-stack'
import { useAuth } from '../auth'
import LoadingScreen from '../components/LoadingScreen'
import LoginScreen from '../screens/LoginScreen'
import MainNavigator from './MainNavigator'
import ChatDetailScreen from '../screens/ChatDetailScreen'
import { navigationRef } from './navigationRef'
import type { Conversation } from '../types'

export type RootStackParamList = {
  Login: undefined
  Main: undefined
  ChatDetail: { conversation: Conversation | null }
}

const Stack = createNativeStackNavigator<RootStackParamList>()

export default function AppNavigator() {
  const { token, loading } = useAuth()

  if (loading) return <LoadingScreen />

  return (
    <NavigationContainer ref={navigationRef}>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {token ? (
          <>
            <Stack.Screen name="Main" component={MainNavigator} />
            <Stack.Screen
              name="ChatDetail"
              component={ChatDetailScreen}
              options={{
                headerShown: true,
                headerBackTitle: '返回',
                headerTintColor: '#2563EB',
                headerStyle: { backgroundColor: '#FFFFFF' },
                title: '',
              }}
            />
          </>
        ) : (
          <Stack.Screen name="Login" component={LoginScreen} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  )
}
