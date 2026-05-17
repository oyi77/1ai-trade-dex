import { useEffect, useRef, useMemo, useCallback } from 'react'
import Globe from 'react-globe.gl'
import type { WeatherForecast, WeatherSignal } from '../types'

interface Props {
  forecasts: WeatherForecast[]
  signals: WeatherSignal[]
}

interface CityMarker {
  lat: number
  lng: number
  name: string
  key: string
  region: string
  forecast: WeatherForecast | null
  bestSignal: WeatherSignal | null
  hasActionable: boolean
}

interface ArcData {
  startLat: number
  startLng: number
  endLat: number
  endLng: number
  color: string
}

const CITY_COORDS: Record<string, { lat: number; lng: number; name: string; region: string }> = {
  nyc:         { lat: 40.7128, lng: -74.006,   name: 'New York',    region: 'North America' },
  chicago:     { lat: 41.8781, lng: -87.6298,  name: 'Chicago',     region: 'North America' },
  miami:       { lat: 25.7617, lng: -80.1918,  name: 'Miami',       region: 'North America' },
  dallas:      { lat: 32.7767, lng: -96.797,   name: 'Dallas',      region: 'North America' },
  seattle:     { lat: 47.6062, lng: -122.3321, name: 'Seattle',     region: 'North America' },
  atlanta:     { lat: 33.749,  lng: -84.388,   name: 'Atlanta',     region: 'North America' },
  los_angeles: { lat: 34.0522, lng: -118.2437, name: 'Los Angeles', region: 'North America' },
  denver:      { lat: 39.7392, lng: -104.9903, name: 'Denver',      region: 'North America' },
  london:      { lat: 51.5074, lng: -0.1278,   name: 'London',      region: 'Europe' },
  seoul:       { lat: 37.5665, lng: 126.978,   name: 'Seoul',       region: 'Asia' },
  tokyo:       { lat: 35.6762, lng: 139.6503,  name: 'Tokyo',       region: 'Asia' },
}

// Generate arcs connecting cities within the same region
function buildRegionArcs(markers: CityMarker[]): ArcData[] {
  const arcs: ArcData[] = []
  const byRegion: Record<string, CityMarker[]> = {}
  for (const m of markers) {
    if (!byRegion[m.region]) byRegion[m.region] = []
    byRegion[m.region].push(m)
  }
  for (const cities of Object.values(byRegion)) {
    for (let i = 0; i < cities.length - 1; i++) {
      arcs.push({
        startLat: cities[i].lat,
        startLng: cities[i].lng,
        endLat: cities[i + 1].lat,
        endLng: cities[i + 1].lng,
        color: 'rgba(82, 82, 82, 0.15)',
      })
    }
  }
  // Cross-region arcs (NYC->London, Tokyo->Seattle) to show global reach
  const nycCoords = CITY_COORDS['nyc']
  const lonCoords = CITY_COORDS['london']
  const tkyCoords = CITY_COORDS['tokyo']
  const seaCoords = CITY_COORDS['seattle']
  arcs.push(
    { startLat: nycCoords.lat, startLng: nycCoords.lng, endLat: lonCoords.lat, endLng: lonCoords.lng, color: 'rgba(217, 119, 6, 0.12)' },
    { startLat: tkyCoords.lat, startLng: tkyCoords.lng, endLat: seaCoords.lat, endLng: seaCoords.lng, color: 'rgba(217, 119, 6, 0.12)' },
    { startLat: lonCoords.lat, startLng: lonCoords.lng, endLat: tkyCoords.lat, endLng: tkyCoords.lng, color: 'rgba(217, 119, 6, 0.12)' },
  )
  return arcs
}

export function GlobeView({ forecasts, signals }: Props) {
  const globeRef = useRef<any>(null)
  const webGLAvailable = useMemo(() => {
    try {
      const canvas = document.createElement('canvas')
      return !!(canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    } catch {
      return false
    }
  }, [])

  const markers: CityMarker[] = useMemo(() => {
    const keys = forecasts.length > 0
      ? [...new Set(forecasts.map(f => f.city_key))]
      : Object.keys(CITY_COORDS)

    return keys.map(key => {
      const coords = CITY_COORDS[key] || CITY_COORDS[key?.toLowerCase()] || { lat: 0, lng: 0, name: key, region: 'Other' }
      const forecast = forecasts.find(f => f.city_key === key) || null
      const citySignals = signals.filter(s => s.city_key === key)
      const actionableSignals = citySignals.filter(s => s.actionable)
      const bestSignal = actionableSignals.length > 0
        ? actionableSignals.reduce((a, b) => Math.abs(a.edge ?? 0) > Math.abs(b.edge ?? 0) ? a : b)
        : citySignals.length > 0
          ? citySignals.reduce((a, b) => Math.abs(a.edge ?? 0) > Math.abs(b.edge ?? 0) ? a : b)
          : null

      return {
        lat: coords.lat,
        lng: coords.lng,
        name: forecast?.city_name || coords.name,
        key,
        region: coords.region,
        forecast,
        bestSignal,
        hasActionable: actionableSignals.length > 0,
      }
    })
  }, [forecasts, signals])

  const arcs = useMemo(() => buildRegionArcs(markers), [markers])

  const actionableCount = markers.filter(m => m.hasActionable).length
  const signalCount = markers.filter(m => m.bestSignal !== null).length

  useEffect(() => {
    const currentGlobe = globeRef.current
    if (globeRef.current) {
      globeRef.current.pointOfView({ lat: 25, lng: 20, altitude: 2.2 }, 1000)
      globeRef.current.controls().autoRotate = true
      globeRef.current.controls().autoRotateSpeed = 0.3
      globeRef.current.controls().enableZoom = false
    }
    return () => {
      // Clean up WebGL context to prevent "Too many active WebGL contexts" memory leak
      if (currentGlobe) {
        try {
          const renderer = currentGlobe.renderer()
          if (renderer) {
            renderer.dispose()
            renderer.forceContextLoss()
          }
        } catch {
// Best-effort cleanup only; some test/browser renderers do not expose disposal hooks.
        }
      }
    }
  }, [])

  const handleInteraction = useCallback(() => {
    if (globeRef.current) {
      globeRef.current.controls().autoRotate = false
      setTimeout(() => {
        if (globeRef.current) {
          globeRef.current.controls().autoRotate = true
        }
      }, 5000)
    }
  }, [])

  const markerElement = useCallback((d: object) => {
    const m = d as CityMarker

    const wrapper = document.createElement('div')
    wrapper.style.cssText = 'position:relative;cursor:pointer;'

    // Pulsing dot
    const dotSize = m.hasActionable ? 12 : m.bestSignal ? 9 : 6
    const dotColor = m.hasActionable ? '#22c55e' : m.bestSignal ? '#d97706' : '#737373'

    const dot = document.createElement('div')
    dot.style.cssText = `width:${dotSize}px;height:${dotSize}px;border-radius:50%;background:${dotColor};box-shadow:0 0 ${dotSize + 4}px ${dotColor}80;transition:all 0.3s;`
    wrapper.appendChild(dot)

    if (m.hasActionable) {
      const pulse = document.createElement('div')
      pulse.style.cssText = `position:absolute;top:${-(dotSize * 0.5)}px;left:${-(dotSize * 0.5)}px;width:${dotSize * 2}px;height:${dotSize * 2}px;border-radius:50%;border:1px solid ${dotColor};opacity:0.5;animation:globePulse 2s infinite;`
      wrapper.appendChild(pulse)
    }

    // City label (always visible)
    const label = document.createElement('div')
    label.style.cssText = 'position:absolute;left:16px;top:-8px;white-space:nowrap;font-size:9px;font-family:ui-monospace,monospace;pointer-events:none;text-shadow:0 0 4px #000,0 0 8px #000;'

    const nameSpan = document.createElement('span')
    nameSpan.style.cssText = `color:${m.hasActionable ? '#22c55e' : '#d4d4d4'};font-weight:${m.hasActionable ? '700' : '500'};letter-spacing:0.5px;`
    nameSpan.textContent = m.name
    label.appendChild(nameSpan)

    // Inline temp if available
    if (m.forecast) {
      const tempSpan = document.createElement('span')
      tempSpan.style.cssText = 'color:#737373;margin-left:6px;font-size:8px;'
      tempSpan.textContent = `${m.forecast.mean_high?.toFixed(0) ?? '--'}°F`
      label.appendChild(tempSpan)
    }

    wrapper.appendChild(label)

    // Hover card
    const card = document.createElement('div')
    card.style.cssText = 'display:none;position:absolute;left:16px;top:14px;background:rgb(10,10,10);border:1px solid #333;padding:10px 12px;white-space:nowrap;font-family:ui-monospace,monospace;font-size:10px;z-index:100;min-width:160px;pointer-events:none;box-shadow:0 4px 12px rgba(0,0,0,0.8);'

    const title = document.createElement('div')
    title.style.cssText = 'font-weight:700;color:#e5e5e5;margin-bottom:2px;font-size:11px;letter-spacing:0.5px;'
    title.textContent = m.name
    card.appendChild(title)

    const regionTag = document.createElement('div')
    regionTag.style.cssText = 'font-size:8px;color:#525252;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;'
    regionTag.textContent = m.region
    card.appendChild(regionTag)

    const addRow = (lbl: string, val: string, color: string = '#a3a3a3') => {
      const row = document.createElement('div')
      row.style.cssText = 'display:flex;justify-content:space-between;gap:16px;margin-top:3px;'
      const l = document.createElement('span')
      l.style.cssText = 'color:#525252;font-size:9px;'
      l.textContent = lbl
      const v = document.createElement('span')
      v.style.cssText = `color:${color};font-variant-numeric:tabular-nums;font-size:10px;`
      v.textContent = val
      row.appendChild(l)
      row.appendChild(v)
      card.appendChild(row)
    }

    if (m.forecast) {
      addRow('High', `${m.forecast.mean_high?.toFixed(1) ?? '--'}°F`, '#ef4444')
      addRow('Low', `${m.forecast.mean_low?.toFixed(1) ?? '--'}°F`, '#3b82f6')
      if (m.forecast.ensemble_agreement != null) {
        const pct = (m.forecast.ensemble_agreement * 100).toFixed(0)
        const agreeColor = m.forecast.ensemble_agreement >= 0.8 ? '#22c55e' : m.forecast.ensemble_agreement >= 0.6 ? '#d97706' : '#ef4444'
        addRow('Ensemble', `${pct}% agree`, agreeColor)
      }
      if (m.forecast.target_date) {
        addRow('Target', m.forecast.target_date, '#525252')
      }
    } else {
      const noData = document.createElement('div')
      noData.style.cssText = 'color:#404040;font-size:9px;font-style:italic;margin-top:2px;'
      noData.textContent = 'Awaiting forecast data...'
      card.appendChild(noData)
    }

    if (m.bestSignal) {
      const sep = document.createElement('div')
      sep.style.cssText = 'border-top:1px solid #262626;margin:6px 0;'
      card.appendChild(sep)

      const edge = m.bestSignal.edge ?? 0
      const edgePct = (edge * 100).toFixed(1)
      const edgeColor = edge > 0.08 ? '#22c55e' : edge > 0.04 ? '#d97706' : '#a3a3a3'
      addRow('Edge', `${edge > 0 ? '+' : ''}${edgePct}%`, edgeColor)

      if (m.bestSignal.direction) {
        addRow('Direction', m.bestSignal.direction.toUpperCase(), m.bestSignal.direction === 'over' ? '#ef4444' : '#3b82f6')
      }

      if (m.hasActionable) {
        const badge = document.createElement('div')
        badge.style.cssText = 'margin-top:6px;padding:3px 8px;background:rgba(34,197,94,0.1);color:#22c55e;font-size:9px;text-align:center;border:1px solid rgba(34,197,94,0.2);letter-spacing:1px;font-weight:600;'
        badge.textContent = 'ACTIONABLE SIGNAL'
        card.appendChild(badge)
      }
    }

    wrapper.appendChild(card)

    wrapper.addEventListener('mouseenter', () => {
      card.style.display = 'block'
      dot.style.transform = 'scale(1.5)'
      dot.style.boxShadow = `0 0 ${dotSize + 8}px ${dotColor}`
    })
    wrapper.addEventListener('mouseleave', () => {
      card.style.display = 'none'
      dot.style.transform = 'scale(1)'
      dot.style.boxShadow = `0 0 ${dotSize + 4}px ${dotColor}80`
    })

    return wrapper
  }, [])

  if (!webGLAvailable) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center bg-black text-neutral-600">
        <div className="text-[10px] uppercase tracking-wider mb-1">Globe Unavailable</div>
        <div className="text-[9px] text-neutral-700">WebGL not supported in this browser</div>
      </div>
    )
  }

  return (
    <div className="globe-container w-full h-full relative">
      <style>{`
        @keyframes globePulse {
          0% { transform: scale(1); opacity: 0.5; }
          50% { transform: scale(2); opacity: 0; }
          100% { transform: scale(1); opacity: 0; }
        }
      `}</style>

      {/* Legend overlay */}
      <div className="absolute top-2 left-2 z-10 pointer-events-none">
        <div className="text-[9px] font-mono space-y-1">
          <div className="text-neutral-600 uppercase tracking-widest mb-1">Weather Markets</div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full bg-green-500 shadow-[0_0_4px_#22c55e]" />
            <span className="text-green-500">Actionable ({actionableCount})</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-2 h-2 rounded-full bg-amber-500 shadow-[0_0_4px_#d97706]" />
            <span className="text-amber-500">Signal ({signalCount})</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-neutral-600" />
            <span className="text-neutral-600">Monitoring</span>
          </div>
        </div>
      </div>

      {/* Info badge */}
      <div className="absolute bottom-2 left-2 z-10 pointer-events-none">
        <div className="text-[8px] font-mono text-neutral-700">
          {markers.length} cities with active Polymarket/Kalshi weather contracts
        </div>
      </div>

      <Globe
        ref={globeRef}
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
        backgroundColor="rgba(0,0,0,0)"
        atmosphereColor="#1a1a2e"
        atmosphereAltitude={0.15}
        htmlElementsData={markers}
        htmlElement={markerElement}
        htmlAltitude={0.01}
        arcsData={arcs}
        arcStartLat={(d: any) => d.startLat}
        arcStartLng={(d: any) => d.startLng}
        arcEndLat={(d: any) => d.endLat}
        arcEndLng={(d: any) => d.endLng}
        arcColor={(d: any) => d.color}
        arcStroke={0.3}
        arcDashLength={0.4}
        arcDashGap={0.2}
        arcDashAnimateTime={4000}
        onGlobeClick={handleInteraction}
        width={undefined}
        height={undefined}
      />
    </div>
  )
}
