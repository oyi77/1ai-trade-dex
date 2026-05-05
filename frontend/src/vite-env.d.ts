/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
  readonly VITE_LANDING_CTA_LABEL?: string
  readonly VITE_LANDING_CTA_URL?: string
  readonly VITE_LANDING_SECONDARY_CTA_LABEL?: string
  readonly VITE_LANDING_SECONDARY_CTA_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
