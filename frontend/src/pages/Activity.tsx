import { NavBar } from '../components/NavBar'
import { ModeSelector } from '../components/dashboard/ModeSelector'
import { ActivityTimeline } from '../components/ActivityTimeline'

export default function Activity() {
  return (
    <div className="min-h-screen bg-black text-neutral-100">
      <NavBar title="Activity Log" />
      <ModeSelector />
      <div className="max-w-7xl mx-auto px-3 sm:px-6 py-6 sm:py-8">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-neutral-100 mb-2">Activity Log</h1>
          <p className="text-sm text-neutral-400">
            Real-time strategy decisions and trading activity
          </p>
        </div>
        <ActivityTimeline />
      </div>
    </div>
  )
}
