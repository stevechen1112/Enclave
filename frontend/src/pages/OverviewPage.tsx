import HomeDashboardView from '../features/home/HomeDashboardView'
import { useHomeDashboard } from '../features/home/useHomeDashboard'

export default function OverviewPage() {
  return <HomeDashboardView model={useHomeDashboard()} />
}
