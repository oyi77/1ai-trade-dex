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
const Evals = React.lazy(() => import('./pages/Evals').then(m => ({ default: m.Evals })))
const AgiOps = React.lazy(() => import('./pages/AgiOps'))
const DecisionLog = React.lazy(() => import('./pages/DecisionLog'))
const EdgeTracker = React.lazy(() => import('./pages/EdgeTracker'))
const MarketIntel = React.lazy(() => import('./pages/MarketIntel'))
const PendingApprovals = React.lazy(() => import('./pages/PendingApprovals'))
const Settlements = React.lazy(() => import('./pages/Settlements'))
const TradingTerminal = React.lazy(() => import('./pages/TradingTerminal'))
const WhaleTracker = React.lazy(() => import('./pages/WhaleTracker'))

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
            <Route path="/evals" element={<Evals />} />
            <Route path="/agi-ops" element={<AgiOps />} />
            {/* Standalone pages wired directly */}
            <Route path="/whale-tracker" element={<WhaleTracker />} />
            <Route path="/settlements" element={<Settlements />} />
            <Route path="/market-intel" element={<MarketIntel />} />
            <Route path="/decisions" element={<DecisionLog />} />
            <Route path="/trading-terminal" element={<TradingTerminal />} />
            <Route path="/pending-approvals" element={<PendingApprovals />} />
            <Route path="/edge-tracker" element={<EdgeTracker />} />
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
