/**
 * Bottom tab navigator — mirrors web Layout.tsx nav items
 * Visible tabs depend on user role (same logic as web RoleGuard).
 */
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs'
import { Ionicons } from '@expo/vector-icons'
import { useAuth } from '../auth'
import ChatListScreen from '../screens/ChatListScreen'
import DocumentsScreen from '../screens/DocumentsScreen'
import ReviewQueueScreen from '../screens/ReviewQueueScreen'
import GenerateScreen from '../screens/GenerateScreen'
import ProgressDashboardScreen from '../screens/ProgressDashboardScreen'

export type MainTabParamList = {
  ChatList: undefined
  Documents: undefined
  Generate: undefined
  ReviewQueue: undefined
  ProgressDashboard: undefined
}

const Tab = createBottomTabNavigator<MainTabParamList>()

const BLUE = '#2563EB'
const GRAY = '#6B7280'

export default function MainNavigator() {
  const { user } = useAuth()
  const isAdmin = user?.is_superuser || user?.role === 'admin' || user?.role === 'owner'
  const isManager = isAdmin || user?.role === 'manager' || user?.role === 'hr'

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        tabBarActiveTintColor: BLUE,
        tabBarInactiveTintColor: GRAY,
        tabBarStyle: {
          borderTopColor: '#E5E7EB',
          backgroundColor: '#FFFFFF',
          height: 60,
          paddingBottom: 8,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '500' },
        headerStyle: { backgroundColor: '#FFFFFF' },
        headerTitleStyle: { color: '#111827', fontWeight: '700', fontSize: 17 },
        headerTintColor: BLUE,
        tabBarIcon: ({ color, size }) => {
          const icons: Record<string, keyof typeof Ionicons.glyphMap> = {
            ChatList: 'chatbubble-ellipses-outline',
            Documents: 'document-text-outline',
            Generate: 'sparkles-outline',
            ReviewQueue: 'checkmark-circle-outline',
            ProgressDashboard: 'bar-chart-outline',
          }
          return <Ionicons name={icons[route.name] ?? 'ellipse-outline'} size={size} color={color} />
        },
      })}
    >
      <Tab.Screen name="ChatList"   component={ChatListScreen}  options={{ title: 'AI 問答',  tabBarLabel: 'AI 問答' }} />
      <Tab.Screen name="Generate"   component={GenerateScreen}  options={{ title: '內容生成', tabBarLabel: '內容生成' }} />
      <Tab.Screen name="Documents"  component={DocumentsScreen} options={{ title: '文件管理', tabBarLabel: '文件' }} />
      {isManager && (
        <Tab.Screen
          name="ReviewQueue"
          component={ReviewQueueScreen}
          options={{ title: '審核佇列', tabBarLabel: '審核' }}
        />
      )}
      {isManager && (
        <Tab.Screen
          name="ProgressDashboard"
          component={ProgressDashboardScreen}
          options={{ title: '處理進度', tabBarLabel: '進度' }}
        />
      )}
    </Tab.Navigator>
  )
}
