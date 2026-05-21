import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { TradeNotifications } from './components/TradeNotifications'
import { PageLoader } from './components/PageLoader'

const Landing = React.lazy(() => import('./pages/Landing'))
const Dashboard = React.lazy(() => import('./pages/Dashboard'))
const Admin = React.lazy(() => import('./pages/Admin'))
const Activity = React.lazy(() => import('./pages/Activity'))
const Proposals = React.lazy(() => import('./pages/Proposals'))
const ErrorTest = React.lazy(() => import('./pages/ErrorTest'))
const MiroFish = React.lazy(() => import('./pages/MiroFish'))
const LiveStream = React.lazy(() => import('./pages/LiveStream'))
const TradingJournal = React.lazy(() => import('./pages/TradingJournal'))
const Backtest = React.lazy(() => import('./pages/Backtest').then(m => ({ default: m.Backtest })))

/**
 * Redirect component for /docs* paths.
 * Docusaurus is a separate static site at /docs/ — we need a full page
 * navigation (not client-side) so the browser fetches the Docusaurus HTML.
 */
function DocsRedirect() {
  React.useEffect(() => {
    const { pathname, search, hash } = window.location
    // Ensure trailing slash for the base /docs path
    const target = pathname === '/docs' ? '/docs/' + search + hash : pathname + search + hash
    window.location.replace(target)
  }, [])
  return <PageLoader />
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <TradeNotifications />
        <React.Suspense fallback={<PageLoader />}>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/activity" element={<Activity />} />
            <Route path="/proposals" element={<Proposals />} />
            <Route path="/error-test" element={<ErrorTest />} />
            <Route path="/mirofish" element={<MiroFish />} />
            <Route path="/livestream" element={<LiveStream />} />
            <Route path="/journal" element={<TradingJournal />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/agi/*" element={<Navigate to="/admin" replace />} />
            {/* Legacy standalone routes → redirect to Dashboard tabs */}
            <Route path="/whale-tracker" element={<Navigate to="/dashboard" replace />} />
            <Route path="/settlements" element={<Navigate to="/dashboard" replace />} />
            <Route path="/market-intel" element={<Navigate to="/dashboard" replace />} />
            <Route path="/decisions" element={<Navigate to="/dashboard" replace />} />
            <Route path="/trading-terminal" element={<Navigate to="/dashboard" replace />} />
            <Route path="/pending-approvals" element={<Navigate to="/admin" replace />} />
            <Route path="/edge-tracker" element={<Navigate to="/dashboard" replace />} />
            <Route path="/docs/*" element={<DocsRedirect />} />
            <Route path="/docs" element={<DocsRedirect />} />
            {/* Missing routes → map to Dashboard or Settings */}
            <Route path="/signals" element={<Dashboard />} />
            <Route path="/trades" element={<Dashboard />} />
            <Route path="/markets" element={<Dashboard />} />
            <Route path="/settings" element={<Navigate to="/admin" replace />} />
            <Route path="/copy-trading" element={<Dashboard />} />
            <Route path="/weather" element={<Dashboard />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </React.Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
