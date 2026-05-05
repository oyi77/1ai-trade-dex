import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import Landing from '../pages/Landing'

function mockNavigatorLanguage(language: string) {
  Object.defineProperty(window.navigator, 'language', {
    configurable: true,
    value: language,
  })
  Object.defineProperty(window.navigator, 'languages', {
    configurable: true,
    value: [language],
  })
}

function mockGeoCountry(countryCode: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ country: countryCode }),
    }),
  )
}

function mockIntersectionObserver() {
  class MockIntersectionObserver implements IntersectionObserver {
    readonly root: Element | Document | null = null
    readonly rootMargin = '0px'
    readonly thresholds: ReadonlyArray<number> = [0]

    disconnect() {}
    observe() {}
    takeRecords(): IntersectionObserverEntry[] {
      return []
    }
    unobserve() {}
  }

  vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
}

function renderLanding() {
  return render(
    <MemoryRouter>
      <Landing />
    </MemoryRouter>,
  )
}

describe('Landing multilingual support', () => {
  beforeEach(() => {
    localStorage.clear()
    mockIntersectionObserver()
    mockNavigatorLanguage('en-US')
    mockGeoCountry('US')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  test('defaults to Indonesian when IP country resolves to Indonesia', async () => {
    mockNavigatorLanguage('en-US')
    mockGeoCountry('ID')

    renderLanding()

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /polyedge berevolusi/i })).toBeInTheDocument()
    })
    expect(screen.getByText(/bukan bot trading/i)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /landing language/i })).toHaveValue('id')
  })

  test('lets visitors switch the dossier language to Russian', async () => {
    renderLanding()

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /landing language/i }), 'ru')

    expect(screen.getByRole('heading', { name: /polyedge эволюционирует/i })).toBeInTheDocument()
    expect(screen.getByText(/не торговый бот/i)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /landing language/i })).toHaveValue('ru')
  })
})
