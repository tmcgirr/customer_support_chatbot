interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_ALLOWED_ORIGINS?: string;
  readonly VITE_PRIVACY_URL?: string;
  readonly VITE_PORTAL_URL?: string;
  // Vite built-ins (provided at build time).
  readonly MODE: string;
  readonly BASE_URL: string;
  readonly PROD: boolean;
  readonly DEV: boolean;
  readonly SSR: boolean;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
