import { POLL } from './polling'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'
import './d3-polyfill'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: POLL.SLOW,
      staleTime: POLL.NORMAL,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)

const registerServiceWorkerIfAvailable = async () => {
  try {
    const response = await fetch('/sw.js', {
      cache: 'no-store',
      method: 'HEAD',
    })
    const contentType = response.headers.get('content-type') ?? ''

    if (!response.ok || !contentType.includes('javascript')) {
      return
    }

    await navigator.serviceWorker.register('/sw.js')
  } catch (error) {
    console.info('Service worker registration skipped:', error)
  }
}

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void registerServiceWorkerIfAvailable()
  })
}
